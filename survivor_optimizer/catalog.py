from __future__ import annotations

import copy
import csv
import json
import operator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .transitions import BuildState, StateTransitionEngine, TransitionAction


_OPERATORS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "ge": operator.ge,
    "gt": operator.gt,
    "le": operator.le,
    "lt": operator.lt,
}


@dataclass(frozen=True)
class Requirement:
    kind: str
    key: str = ""
    value: Any = None
    operator: str = "eq"
    quantity: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Requirement:
        return cls(
            kind=str(data["kind"]),
            key=str(data.get("key", data.get("resource", data.get("object_id", "")))),
            value=copy.deepcopy(data.get("value")),
            operator=str(data.get("operator", "eq")),
            quantity=int(data.get("quantity", 0)),
        )

    def evaluate(self, state: BuildState) -> bool:
        if self.kind == "flag":
            return self.key in state.flags
        if self.kind == "not_flag":
            return self.key not in state.flags
        if self.kind == "resource":
            return state.resources.get(self.key, 0) >= self.quantity
        if self.kind == "object_exists":
            return self.key in state.objects
        if self.kind == "object_tag":
            return any(self.key in obj.tags for obj in state.objects.values())
        if self.kind == "object_count":
            count = sum(1 for obj in state.objects.values() if self.key in obj.tags)
            return count >= self.quantity
        if self.kind == "object_state":
            object_id, _, path = self.key.partition(":")
            obj = state.objects.get(object_id)
            if obj is None:
                return False
            actual = _get_path(obj.state, path)
            if self.operator not in _OPERATORS:
                raise ValueError(f"Unsupported requirement operator: {self.operator}")
            try:
                return bool(_OPERATORS[self.operator](actual, self.value))
            except TypeError:
                return False
        raise ValueError(f"Unsupported requirement kind: {self.kind}")


@dataclass(frozen=True)
class SioMutation:
    """Exact changes to calculator input associated with a verified action.

    Paths use dotted notation, for example ``stats.critRate``. The optimizer never
    derives these mutations from prose; they must be supplied by verified data.
    """

    deltas: dict[str, float] = field(default_factory=dict)
    sets: dict[str, Any] = field(default_factory=dict)
    removes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> SioMutation:
        data = data or {}
        return cls(
            deltas={str(k): float(v) for k, v in dict(data.get("deltas", {})).items()},
            sets=copy.deepcopy(dict(data.get("sets", {}))),
            removes=tuple(str(v) for v in data.get("removes", [])),
        )

    def apply(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(dict(payload))
        for path, value in self.sets.items():
            _set_path(result, path, copy.deepcopy(value))
        for path, delta in self.deltas.items():
            current = _get_path(result, path, default=0)
            if not isinstance(current, (int, float)):
                raise ValueError(f"Cannot apply numeric delta to non-numeric path {path!r}")
            _set_path(result, path, current + delta)
        for path in self.removes:
            _remove_path(result, path)
        return result

    @property
    def is_empty(self) -> bool:
        return not self.deltas and not self.sets and not self.removes


@dataclass(frozen=True)
class OptimizerAction:
    action_key: str
    transition: TransitionAction
    requirements: tuple[Requirement, ...] = ()
    sio_mutation: SioMutation = field(default_factory=SioMutation)
    inverse_sio_mutation: SioMutation = field(default_factory=SioMutation)
    tags: tuple[str, ...] = ()
    source_status: str = ""
    source_urls: tuple[str, ...] = ()
    allows_unknown_refund: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OptimizerAction:
        transition_data = dict(data.get("transition", data))
        transition_data.setdefault("action_id", str(data.get("action_key", transition_data.get("action_id"))))
        return cls(
            action_key=str(data.get("action_key", transition_data["action_id"])),
            transition=TransitionAction.from_dict(transition_data),
            requirements=tuple(Requirement.from_dict(v) for v in data.get("requirements", [])),
            sio_mutation=SioMutation.from_dict(data.get("sio_mutation")),
            inverse_sio_mutation=SioMutation.from_dict(data.get("inverse_sio_mutation")),
            tags=tuple(str(v) for v in data.get("tags", [])),
            source_status=str(data.get("source_status", "")),
            source_urls=tuple(str(v) for v in data.get("source_urls", [])),
            allows_unknown_refund=bool(data.get("allows_unknown_refund", False)),
        )

    def available(self, state: BuildState, mode: str) -> bool:
        if self.transition.mode_scope and mode not in self.transition.mode_scope:
            return False
        return all(requirement.evaluate(state) for requirement in self.requirements)


@dataclass(frozen=True)
class CollectionSetDefinition:
    set_id: str
    set_name: str
    members: tuple[str, ...]
    exact_members: bool = True


@dataclass(frozen=True)
class DerivedUnlockRule:
    flag: str
    requirements: tuple[Requirement, ...]


@dataclass
class ActionCatalog:
    actions: list[OptimizerAction] = field(default_factory=list)
    collection_sets: list[CollectionSetDefinition] = field(default_factory=list)
    derived_rules: list[DerivedUnlockRule] = field(default_factory=list)
    normal_pet_type_by_name: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ActionCatalog:
        return cls(
            actions=[OptimizerAction.from_dict(v) for v in data.get("actions", [])],
            collection_sets=[
                CollectionSetDefinition(
                    set_id=str(v["set_id"]),
                    set_name=str(v.get("set_name", v["set_id"])),
                    members=tuple(str(member) for member in v.get("members", [])),
                    exact_members=bool(v.get("exact_members", True)),
                )
                for v in data.get("collection_sets", [])
            ],
            derived_rules=[
                DerivedUnlockRule(
                    flag=str(v["flag"]),
                    requirements=tuple(Requirement.from_dict(r) for r in v.get("requirements", [])),
                )
                for v in data.get("derived_rules", [])
            ],
            normal_pet_type_by_name={
                str(k): str(v) for k, v in dict(data.get("normal_pet_type_by_name", {})).items()
            },
        )

    @classmethod
    def load(cls, path: str | Path) -> ActionCatalog:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Action catalog must be a JSON object")
        return cls.from_dict(data)

    @classmethod
    def discover_repository_data(cls, root: str | Path) -> ActionCatalog:
        """Build deterministic unlock rules from normalized repository CSV files.

        This compiler intentionally does not convert prose into calculator stats. It only
        imports exact member lists and pet type metadata for logical unlock gates.
        """

        root = Path(root)
        catalog = cls()
        collection_path = _first_existing(
            root / "data" / "survivor_io_collection_sets_summary.csv",
            root / "survivor_io_collection_sets_summary.csv",
        )
        if collection_path:
            with collection_path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    status = row.get("Data_Status", "")
                    members = tuple(
                        row.get(f"Collectible_{index}", "").strip()
                        for index in range(1, 5)
                        if row.get(f"Collectible_{index}", "").strip()
                    )
                    exact = "member list transcribed" in status.lower() or "exact garrytools" in status.lower()
                    if members:
                        catalog.collection_sets.append(
                            CollectionSetDefinition(
                                set_id=row.get("Set_ID", row.get("Set_Name", "")),
                                set_name=row.get("Set_Name", ""),
                                members=members,
                                exact_members=exact,
                            )
                        )
        pet_path = _first_existing(
            root / "data" / "survivor_io_normal_pets_summary.csv",
            root / "survivor_io_normal_pets_summary.csv",
        )
        if pet_path:
            with pet_path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    pet = row.get("Pet", "").strip()
                    group = row.get("Awakening_Type_Group", "").strip()
                    if pet and group and "No supported" not in group:
                        catalog.normal_pet_type_by_name[pet] = group
        return catalog

    def available_actions(self, state: BuildState, mode: str) -> list[OptimizerAction]:
        return [action for action in self.actions if action.available(state, mode)]


class DerivedUnlockEngine:
    """Recomputes unlocks that are consequences of inventory state.

    Auto-derived flags are removed and rebuilt every time. This prevents impossible
    states such as owning every collectible in a set while marking that set locked.
    """

    AUTO_PREFIX = "auto:"

    def __init__(self, catalog: ActionCatalog):
        self.catalog = catalog

    def recompute(self, state: BuildState) -> set[str]:
        state.flags = {flag for flag in state.flags if not flag.startswith(self.AUTO_PREFIX)}
        derived: set[str] = set()
        owned_collectibles = self._owned_collectibles(state)
        for definition in self.catalog.collection_sets:
            if not definition.exact_members:
                continue
            if definition.members and all(member in owned_collectibles for member in definition.members):
                derived.add(f"auto:collection_set:{definition.set_id}")
                derived.add(f"auto:collection_set_name:{definition.set_name}")

        pet_types = set()
        for obj in state.objects.values():
            if obj.system not in {"normal_pet", "pet"}:
                continue
            pet_name = str(obj.state.get("name", obj.object_id))
            pet_type = str(
                obj.state.get("pet_type")
                or self.catalog.normal_pet_type_by_name.get(pet_name, "")
            )
            stage_order = _awakening_stage_order(obj.state)
            if pet_type and stage_order >= 5:
                pet_types.add(pet_type)
        if len(pet_types) >= 4:
            derived.add("auto:system:xeno_pet")

        for rule in self.catalog.derived_rules:
            if all(requirement.evaluate(state) for requirement in rule.requirements):
                derived.add(f"auto:{rule.flag}")

        state.flags.update(derived)
        return derived

    @staticmethod
    def _owned_collectibles(state: BuildState) -> set[str]:
        owned: set[str] = set()
        for obj in state.objects.values():
            if obj.system != "collectible":
                continue
            count = int(obj.state.get("count", 1 if obj.state.get("owned", True) else 0))
            if count <= 0:
                continue
            owned.add(str(obj.state.get("name", obj.object_id)))
        return owned


@dataclass(frozen=True)
class CandidateOperation:
    operation_id: str
    kind: str
    action: OptimizerAction | None = None
    refund_action_id: str | None = None
    tags: tuple[str, ...] = ()


class CandidateGenerator:
    def __init__(
        self,
        engine: StateTransitionEngine,
        catalog: ActionCatalog,
        unlocks: DerivedUnlockEngine,
    ) -> None:
        self.engine = engine
        self.catalog = catalog
        self.unlocks = unlocks

    def generate(
        self,
        state: BuildState,
        mode: str,
        *,
        protected_unlocks: Iterable[str] = (),
        allow_irreversible: bool = True,
        allow_unknown_refund_forward: bool = True,
    ) -> list[CandidateOperation]:
        self.unlocks.recompute(state)
        protected = set(protected_unlocks)
        candidates: list[CandidateOperation] = []
        for action in self.catalog.available_actions(state, mode):
            rule = self.engine.get_rule(action.transition.rule_id)
            kind = rule.refund_policy.kind.value
            if kind == "none" and not allow_irreversible:
                continue
            if kind == "unknown" and not allow_unknown_refund_forward and not action.allows_unknown_refund:
                continue
            branch = state.clone()
            try:
                self.engine.apply(branch, action.transition)
                self.unlocks.recompute(branch)
            except ValueError:
                continue
            if protected - branch.flags:
                continue
            candidates.append(
                CandidateOperation(
                    operation_id=f"apply:{action.action_key}",
                    kind="apply",
                    action=action,
                    tags=action.tags,
                )
            )

        for receipt in reversed(state.history):
            if not receipt.active:
                continue
            preview = self.engine.preview_refund(state, receipt.action_id)
            if not preview.allowed:
                continue
            restores_state = bool(
                preview.returned_resources
                or receipt.consumed_objects
                or receipt.previous_target is not None
                or receipt.previous_flags != state.flags
            )
            if not restores_state:
                continue
            branch = state.clone()
            try:
                self.engine.refund(branch, receipt.action_id)
                self.unlocks.recompute(branch)
            except ValueError:
                continue
            if protected - branch.flags:
                continue
            candidates.append(
                CandidateOperation(
                    operation_id=f"refund:{receipt.action_id}",
                    kind="refund",
                    refund_action_id=receipt.action_id,
                    tags=(f"system:{receipt.rule.system}", "refund"),
                )
            )
        return candidates


def _awakening_stage_order(state: Mapping[str, Any]) -> int:
    if "awakening_order" in state:
        return int(state["awakening_order"])
    stage = str(state.get("awakening_stage", state.get("awakening", ""))).upper()
    mapping = {"Y1": 1, "Y2": 2, "Y3": 3, "Y4": 4, "Y5": 5,
               "R1": 6, "R2": 7, "R3": 8, "R4": 9, "R5": 10}
    return mapping.get(stage, 0)


def _first_existing(*paths: Path) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _get_path(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    if not path:
        return current
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _remove_path(data: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
