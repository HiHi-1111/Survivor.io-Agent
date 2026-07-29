from __future__ import annotations

import copy
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping


class TransitionError(ValueError):
    """Base error raised when a state transition is illegal."""


class InsufficientResourceError(TransitionError):
    pass


class MissingRequirementError(TransitionError):
    pass


class RefundBlockedError(TransitionError):
    pass


class DependencyBlockedError(TransitionError):
    pass


class RefundKind(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RefundPolicy:
    kind: RefundKind
    resource_refund_ratios: dict[str, float] = field(default_factory=dict)
    fixed_returns: dict[str, int] = field(default_factory=dict)
    reset_costs: dict[str, int] = field(default_factory=dict)
    unknown_resource_policy: str = "block"
    required_action_metadata: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.unknown_resource_policy not in {"block", "zero", "full"}:
            raise ValueError("unknown_resource_policy must be block, zero, or full")
        for resource, ratio in self.resource_refund_ratios.items():
            if ratio < 0 or ratio > 1:
                raise ValueError(f"Refund ratio for {resource!r} must be between 0 and 1")
        for mapping_name, values in (
            ("fixed_returns", self.fixed_returns),
            ("reset_costs", self.reset_costs),
        ):
            for resource, quantity in values.items():
                if quantity < 0:
                    raise ValueError(f"{mapping_name}[{resource!r}] cannot be negative")


@dataclass(frozen=True)
class TransitionRule:
    rule_id: str
    system: str
    action_kind: str
    refund_policy: RefundPolicy
    verification_status: str
    source_urls: tuple[str, ...] = ()
    notes: str = ""


@dataclass
class GameObject:
    object_id: str
    system: str
    state: dict[str, Any] = field(default_factory=dict)
    tags: set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GameObject":
        return cls(
            object_id=str(data["object_id"]),
            system=str(data.get("system", "unknown")),
            state=copy.deepcopy(dict(data.get("state", {}))),
            tags=set(data.get("tags", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "system": self.system,
            "state": copy.deepcopy(self.state),
            "tags": sorted(self.tags),
        }


@dataclass(frozen=True)
class TransitionAction:
    action_id: str
    rule_id: str
    target_id: str | None = None
    consumes: dict[str, int] = field(default_factory=dict)
    produces: dict[str, int] = field(default_factory=dict)
    consumes_objects: tuple[str, ...] = ()
    produces_objects: tuple[GameObject, ...] = ()
    target_patch: dict[str, Any] = field(default_factory=dict)
    requires_flags: tuple[str, ...] = ()
    forbids_flags: tuple[str, ...] = ()
    creates_flags: tuple[str, ...] = ()
    removes_flags: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    mode_scope: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    lifetime_scope: str = "account"

    def __post_init__(self) -> None:
        for mapping_name, values in (("consumes", self.consumes), ("produces", self.produces)):
            for resource, quantity in values.items():
                if not isinstance(quantity, int) or quantity < 0:
                    raise ValueError(
                        f"{mapping_name}[{resource!r}] must be a non-negative integer"
                    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransitionAction":
        return cls(
            action_id=str(data["action_id"]),
            rule_id=str(data["rule_id"]),
            target_id=data.get("target_id"),
            consumes={str(k): int(v) for k, v in dict(data.get("consumes", {})).items()},
            produces={str(k): int(v) for k, v in dict(data.get("produces", {})).items()},
            consumes_objects=tuple(str(v) for v in data.get("consumes_objects", [])),
            produces_objects=tuple(
                GameObject.from_dict(v) for v in data.get("produces_objects", [])
            ),
            target_patch=copy.deepcopy(dict(data.get("target_patch", {}))),
            requires_flags=tuple(str(v) for v in data.get("requires_flags", [])),
            forbids_flags=tuple(str(v) for v in data.get("forbids_flags", [])),
            creates_flags=tuple(str(v) for v in data.get("creates_flags", [])),
            removes_flags=tuple(str(v) for v in data.get("removes_flags", [])),
            depends_on=tuple(str(v) for v in data.get("depends_on", [])),
            mode_scope=tuple(str(v) for v in data.get("mode_scope", [])),
            metadata=copy.deepcopy(dict(data.get("metadata", {}))),
            lifetime_scope=str(data.get("lifetime_scope", "account")),
        )


@dataclass
class ActionReceipt:
    action: TransitionAction
    rule: TransitionRule
    consumed_objects: dict[str, GameObject]
    previous_target: GameObject | None
    previous_flags: set[str]
    history_index: int
    active: bool = True

    @property
    def action_id(self) -> str:
        return self.action.action_id


@dataclass
class RefundPreview:
    action_id: str
    allowed: bool
    returned_resources: dict[str, int] = field(default_factory=dict)
    lost_resources: dict[str, int] = field(default_factory=dict)
    reset_costs: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ResetPlan:
    checkpoint_index: int
    rollback_order: list[str]
    previews: list[RefundPreview]
    blockers: list[str]
    total_returns: dict[str, int]
    total_losses: dict[str, int]
    total_reset_costs: dict[str, int]

    @property
    def legal(self) -> bool:
        return not self.blockers


@dataclass
class BuildState:
    resources: dict[str, int] = field(default_factory=dict)
    objects: dict[str, GameObject] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    mode: str | None = None
    history: list[ActionReceipt] = field(default_factory=list)
    checkpoints: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BuildState":
        objects = {
            str(key): GameObject.from_dict(value)
            for key, value in dict(data.get("objects", {})).items()
        }
        return cls(
            resources={str(k): int(v) for k, v in dict(data.get("resources", {})).items()},
            objects=objects,
            flags=set(data.get("flags", [])),
            mode=data.get("mode"),
            checkpoints={str(k): int(v) for k, v in dict(data.get("checkpoints", {})).items()},
        )

    def to_dict(self, include_history: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "resources": dict(sorted(self.resources.items())),
            "objects": {
                key: value.to_dict() for key, value in sorted(self.objects.items())
            },
            "flags": sorted(self.flags),
            "mode": self.mode,
            "checkpoints": dict(sorted(self.checkpoints.items())),
        }
        if include_history:
            result["history"] = [
                {
                    "action_id": receipt.action.action_id,
                    "rule_id": receipt.rule.rule_id,
                    "target_id": receipt.action.target_id,
                    "active": receipt.active,
                    "history_index": receipt.history_index,
                    "depends_on": list(receipt.action.depends_on),
                }
                for receipt in self.history
            ]
        return result

    def clone(self) -> "BuildState":
        return copy.deepcopy(self)


class StateTransitionEngine:
    """Apply, refund, branch, and reset legal game-state transitions.

    The engine contains no damage formula. It only validates transformations and
    tracks which resources are conserved, returned, or lost.
    """

    def __init__(self, rules: Iterable[TransitionRule]):
        rule_list = list(rules)
        self.rules = {rule.rule_id: rule for rule in rule_list}
        if len(self.rules) != len(rule_list):
            raise ValueError("Duplicate rule IDs are not allowed")

    def get_rule(self, rule_id: str) -> TransitionRule:
        try:
            return self.rules[rule_id]
        except KeyError as exc:
            raise MissingRequirementError(f"Unknown transition rule: {rule_id}") from exc

    def validate_action(self, state: BuildState, action: TransitionAction) -> None:
        self.get_rule(action.rule_id)
        if any(receipt.action_id == action.action_id for receipt in state.history):
            raise TransitionError(f"Action ID already exists in history: {action.action_id}")
        if action.mode_scope and state.mode not in set(action.mode_scope):
            raise MissingRequirementError(
                f"Action {action.action_id} is only legal in modes {action.mode_scope}; "
                f"current mode is {state.mode!r}"
            )
        missing_flags = sorted(set(action.requires_flags) - state.flags)
        if missing_flags:
            raise MissingRequirementError(f"Missing required flags: {missing_flags}")
        forbidden = sorted(set(action.forbids_flags) & state.flags)
        if forbidden:
            raise MissingRequirementError(f"Forbidden flags are active: {forbidden}")
        missing_dependencies = [
            dependency
            for dependency in action.depends_on
            if not self._active_receipt(state, dependency)
        ]
        if missing_dependencies:
            raise MissingRequirementError(
                f"Missing active action dependencies: {missing_dependencies}"
            )
        for resource, required in action.consumes.items():
            available = state.resources.get(resource, 0)
            if available < required:
                raise InsufficientResourceError(
                    f"Need {required} {resource}; only {available} available"
                )
        for object_id in action.consumes_objects:
            if object_id not in state.objects:
                raise MissingRequirementError(f"Missing object to consume: {object_id}")
        for obj in action.produces_objects:
            if obj.object_id in state.objects:
                raise TransitionError(f"Produced object already exists: {obj.object_id}")
        if (
            action.target_id is not None
            and action.target_patch
            and action.target_id not in state.objects
        ):
            raise MissingRequirementError(f"Missing target object: {action.target_id}")

    def apply(self, state: BuildState, action: TransitionAction) -> ActionReceipt:
        self.validate_action(state, action)
        rule = self.get_rule(action.rule_id)
        consumed_objects = {
            object_id: copy.deepcopy(state.objects[object_id])
            for object_id in action.consumes_objects
        }
        previous_target = (
            copy.deepcopy(state.objects[action.target_id])
            if action.target_id is not None and action.target_id in state.objects
            else None
        )
        previous_flags = set(state.flags)

        for resource, quantity in action.consumes.items():
            state.resources[resource] = state.resources.get(resource, 0) - quantity
        for resource, quantity in action.produces.items():
            state.resources[resource] = state.resources.get(resource, 0) + quantity
        for object_id in action.consumes_objects:
            del state.objects[object_id]
        for obj in action.produces_objects:
            state.objects[obj.object_id] = copy.deepcopy(obj)
        if action.target_id is not None and action.target_patch:
            self._deep_patch(state.objects[action.target_id].state, action.target_patch)
        state.flags.difference_update(action.removes_flags)
        state.flags.update(action.creates_flags)

        receipt = ActionReceipt(
            action=copy.deepcopy(action),
            rule=rule,
            consumed_objects=consumed_objects,
            previous_target=previous_target,
            previous_flags=previous_flags,
            history_index=len(state.history),
        )
        state.history.append(receipt)
        return receipt

    def checkpoint(self, state: BuildState, name: str) -> int:
        if not name.strip():
            raise ValueError("Checkpoint name cannot be blank")
        state.checkpoints[name] = len(state.history)
        return state.checkpoints[name]

    def preview_refund(self, state: BuildState, action_id: str) -> RefundPreview:
        receipt = self._active_receipt(state, action_id)
        if receipt is None:
            return RefundPreview(
                action_id=action_id,
                allowed=False,
                blockers=["Action is not active"],
            )

        blockers = self._rollback_blockers(state, receipt)
        policy = receipt.rule.refund_policy
        if policy.kind == RefundKind.NONE:
            blockers.append("Rule is irreversible")
        elif policy.kind == RefundKind.UNKNOWN:
            blockers.append("Refund behavior is not verified")
        elif policy.kind == RefundKind.CONDITIONAL:
            for key, expected in policy.required_action_metadata.items():
                if receipt.action.metadata.get(key) != expected:
                    blockers.append(
                        f"Conditional refund requires metadata {key}={expected!r}"
                    )

        returned, lost, policy_blockers = self._calculate_returns(receipt)
        blockers.extend(policy_blockers)
        for resource, quantity in policy.reset_costs.items():
            if state.resources.get(resource, 0) < quantity:
                blockers.append(
                    f"Reset requires {quantity} {resource}; only "
                    f"{state.resources.get(resource, 0)} available"
                )
        for resource, quantity in receipt.action.produces.items():
            if state.resources.get(resource, 0) < quantity:
                blockers.append(
                    f"Produced resource {resource} has been spent; need {quantity} to reverse"
                )
        return RefundPreview(
            action_id=action_id,
            allowed=not blockers,
            returned_resources=returned,
            lost_resources=lost,
            reset_costs=dict(policy.reset_costs),
            blockers=blockers,
            notes=policy.notes or receipt.rule.notes,
        )

    def refund(self, state: BuildState, action_id: str) -> RefundPreview:
        preview = self.preview_refund(state, action_id)
        if not preview.allowed:
            raise RefundBlockedError(
                f"Cannot refund {action_id}: {'; '.join(preview.blockers)}"
            )
        receipt = self._active_receipt(state, action_id)
        assert receipt is not None

        for resource, quantity in preview.reset_costs.items():
            state.resources[resource] -= quantity
        for resource, quantity in receipt.action.produces.items():
            state.resources[resource] -= quantity
        for resource, quantity in preview.returned_resources.items():
            state.resources[resource] = state.resources.get(resource, 0) + quantity
        for obj in receipt.action.produces_objects:
            if obj.object_id not in state.objects:
                raise RefundBlockedError(
                    f"Produced object {obj.object_id} is missing; state changed outside ledger"
                )
            del state.objects[obj.object_id]
        for object_id, obj in receipt.consumed_objects.items():
            if object_id in state.objects:
                raise RefundBlockedError(
                    f"Cannot restore consumed object {object_id}; that ID already exists"
                )
            state.objects[object_id] = copy.deepcopy(obj)
        if receipt.action.target_id is not None and receipt.previous_target is not None:
            state.objects[receipt.action.target_id] = copy.deepcopy(receipt.previous_target)
        state.flags = set(receipt.previous_flags)
        receipt.active = False
        return preview

    def plan_reset_to_index(self, state: BuildState, checkpoint_index: int) -> ResetPlan:
        if checkpoint_index < 0 or checkpoint_index > len(state.history):
            raise ValueError("checkpoint_index is outside the action history")
        simulation = state.clone()
        rollback_ids = [
            receipt.action_id
            for receipt in reversed(simulation.history[checkpoint_index:])
            if receipt.active
        ]
        previews: list[RefundPreview] = []
        blockers: list[str] = []
        total_returns: defaultdict[str, int] = defaultdict(int)
        total_losses: defaultdict[str, int] = defaultdict(int)
        total_costs: defaultdict[str, int] = defaultdict(int)

        for action_id in rollback_ids:
            preview = self.preview_refund(simulation, action_id)
            previews.append(preview)
            for resource, quantity in preview.returned_resources.items():
                total_returns[resource] += quantity
            for resource, quantity in preview.lost_resources.items():
                total_losses[resource] += quantity
            for resource, quantity in preview.reset_costs.items():
                total_costs[resource] += quantity
            if not preview.allowed:
                blockers.append(f"{action_id}: {'; '.join(preview.blockers)}")
                break
            self.refund(simulation, action_id)

        return ResetPlan(
            checkpoint_index=checkpoint_index,
            rollback_order=rollback_ids,
            previews=previews,
            blockers=blockers,
            total_returns=dict(total_returns),
            total_losses=dict(total_losses),
            total_reset_costs=dict(total_costs),
        )

    def plan_reset_to_checkpoint(self, state: BuildState, checkpoint_name: str) -> ResetPlan:
        if checkpoint_name not in state.checkpoints:
            raise MissingRequirementError(f"Unknown checkpoint: {checkpoint_name}")
        return self.plan_reset_to_index(state, state.checkpoints[checkpoint_name])

    def execute_reset_to_index(self, state: BuildState, checkpoint_index: int) -> ResetPlan:
        plan = self.plan_reset_to_index(state, checkpoint_index)
        if not plan.legal:
            raise RefundBlockedError("Reset plan is blocked: " + "; ".join(plan.blockers))
        for action_id in plan.rollback_order:
            if self._active_receipt(state, action_id) is not None:
                self.refund(state, action_id)
        return plan

    def reset_ephemeral_scope(self, state: BuildState, scope: str) -> list[str]:
        """Clear temporary run state without touching permanent inventory."""
        if scope not in {"battle_run", "mode_attempt"}:
            raise ValueError("Only battle_run and mode_attempt are natural reset scopes")
        reset_ids: list[str] = []
        for receipt in reversed(state.history):
            if not receipt.active or receipt.action.lifetime_scope != scope:
                continue
            action = receipt.action
            if action.consumes or action.produces or action.consumes_objects:
                raise RefundBlockedError(
                    f"Ephemeral action {action.action_id} changed permanent inventory and "
                    "cannot be cleared by a natural reset"
                )
            for obj in action.produces_objects:
                state.objects.pop(obj.object_id, None)
            if action.target_id is not None and receipt.previous_target is not None:
                state.objects[action.target_id] = copy.deepcopy(receipt.previous_target)
            state.flags = set(receipt.previous_flags)
            receipt.active = False
            reset_ids.append(action.action_id)
        return reset_ids

    def simulate_actions(
        self,
        state: BuildState,
        actions: Iterable[TransitionAction],
    ) -> BuildState:
        branch = state.clone()
        for action in actions:
            self.apply(branch, action)
        return branch

    def compare_resource_delta(
        self,
        before: BuildState,
        after: BuildState,
    ) -> dict[str, int]:
        keys = set(before.resources) | set(after.resources)
        return {
            key: after.resources.get(key, 0) - before.resources.get(key, 0)
            for key in sorted(keys)
            if after.resources.get(key, 0) != before.resources.get(key, 0)
        }

    def _calculate_returns(
        self,
        receipt: ActionReceipt,
    ) -> tuple[dict[str, int], dict[str, int], list[str]]:
        policy = receipt.rule.refund_policy
        returned: dict[str, int] = {}
        lost: dict[str, int] = {}
        blockers: list[str] = []
        if policy.kind == RefundKind.FULL:
            returned = dict(receipt.action.consumes)
        elif policy.kind in {RefundKind.PARTIAL, RefundKind.CONDITIONAL}:
            for resource, quantity in receipt.action.consumes.items():
                if resource in policy.resource_refund_ratios:
                    ratio = policy.resource_refund_ratios[resource]
                elif policy.unknown_resource_policy == "full":
                    ratio = 1.0
                elif policy.unknown_resource_policy == "zero":
                    ratio = 0.0
                else:
                    blockers.append(
                        f"No verified refund rule for consumed resource {resource}"
                    )
                    continue
                amount = math.floor(quantity * ratio)
                returned[resource] = amount
                lost[resource] = quantity - amount
            for resource, quantity in policy.fixed_returns.items():
                returned[resource] = returned.get(resource, 0) + quantity
        elif policy.kind in {RefundKind.NONE, RefundKind.UNKNOWN}:
            lost = dict(receipt.action.consumes)
        return returned, {key: value for key, value in lost.items() if value}, blockers

    def _rollback_blockers(self, state: BuildState, receipt: ActionReceipt) -> list[str]:
        blockers: list[str] = []
        later_active = [
            item for item in state.history[receipt.history_index + 1 :] if item.active
        ]
        dependent_ids = [
            item.action_id
            for item in later_active
            if receipt.action_id in item.action.depends_on
        ]
        if dependent_ids:
            blockers.append(f"Active dependent actions exist: {dependent_ids}")
        if receipt.action.target_id is not None:
            same_target = [
                item.action_id
                for item in later_active
                if item.action.target_id == receipt.action.target_id
            ]
            if same_target:
                blockers.append(f"Later actions modified the same target: {same_target}")
        produced_ids = {obj.object_id for obj in receipt.action.produces_objects}
        object_consumers = [
            item.action_id
            for item in later_active
            if produced_ids.intersection(item.action.consumes_objects)
        ]
        if object_consumers:
            blockers.append(
                f"Produced objects were consumed by later actions: {object_consumers}"
            )
        return blockers

    @staticmethod
    def _active_receipt(state: BuildState, action_id: str) -> ActionReceipt | None:
        for receipt in reversed(state.history):
            if receipt.action_id == action_id and receipt.active:
                return receipt
        return None

    @classmethod
    def _deep_patch(cls, target: dict[str, Any], patch: Mapping[str, Any]) -> None:
        for key, value in patch.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                cls._deep_patch(target[key], value)
            else:
                target[key] = copy.deepcopy(value)


def result_to_json(value: Any) -> str:
    """Serialize engine dataclasses into stable JSON."""

    def default(obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, set):
            return sorted(obj)
        if isinstance(obj, GameObject):
            return obj.to_dict()
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        raise TypeError(f"Cannot serialize {type(obj).__name__}")

    return json.dumps(value, default=default, ensure_ascii=False, sort_keys=True, indent=2)
