from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .transitions import BuildState, StateTransitionEngine, TransitionAction


@dataclass(frozen=True)
class ModeGoal:
    """One game mode the optimizer must score with the sIO calculator."""

    mode: str
    weight: float = 1.0
    required_unlocks: tuple[str, ...] = ()
    calculator_overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModeGoal:
        weight = float(data.get("weight", 1.0))
        if weight <= 0:
            raise ValueError("ModeGoal.weight must be positive")
        return cls(
            mode=str(data["mode"]),
            weight=weight,
            required_unlocks=tuple(str(v) for v in data.get("required_unlocks", [])),
            calculator_overrides=copy.deepcopy(dict(data.get("calculator_overrides", {}))),
        )


@dataclass
class OptimizationProfile:
    """Serializable account state plus exact sIO calculator inputs.

    The ledger is optional. Without it the optimizer can explore forward spending and
    loadout changes, but it cannot safely invent refund returns for historic upgrades.
    """

    profile_id: str
    base_state: BuildState
    ledger: list[TransitionAction] = field(default_factory=list)
    calculator_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    goals: list[ModeGoal] = field(default_factory=list)
    protected_unlocks: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OptimizationProfile:
        goals = [ModeGoal.from_dict(v) for v in data.get("goals", [])]
        if not goals:
            default_mode = str(data.get("mode", "ee"))
            goals = [ModeGoal(mode=default_mode)]
        calculator_inputs = {
            str(mode): copy.deepcopy(dict(payload))
            for mode, payload in dict(data.get("calculator_inputs", {})).items()
        }
        if not calculator_inputs and "calculator" in data:
            calculator_inputs[goals[0].mode] = copy.deepcopy(dict(data["calculator"]))
        return cls(
            profile_id=str(data.get("profile_id", "profile")),
            base_state=BuildState.from_dict(dict(data.get("base_state", data.get("state", {})))),
            ledger=[TransitionAction.from_dict(v) for v in data.get("ledger", [])],
            calculator_inputs=calculator_inputs,
            goals=goals,
            protected_unlocks=set(str(v) for v in data.get("protected_unlocks", [])),
            metadata=copy.deepcopy(dict(data.get("metadata", {}))),
        )

    def materialize(self, engine: StateTransitionEngine) -> BuildState:
        state = self.base_state.clone()
        for action in self.ledger:
            engine.apply(state, action)
        return state

    def calculator_for_mode(self, mode: str) -> dict[str, Any]:
        payload = copy.deepcopy(self.calculator_inputs.get(mode, {}))
        for goal in self.goals:
            if goal.mode == mode:
                _deep_patch(payload, goal.calculator_overrides)
                break
        payload.setdefault("game_mode", mode)
        return payload

    def clone(self) -> OptimizationProfile:
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "base_state": self.base_state.to_dict(include_history=False),
            "ledger": [action_to_dict(v) for v in self.ledger],
            "calculator_inputs": copy.deepcopy(self.calculator_inputs),
            "goals": [
                {
                    "mode": goal.mode,
                    "weight": goal.weight,
                    "required_unlocks": list(goal.required_unlocks),
                    "calculator_overrides": copy.deepcopy(goal.calculator_overrides),
                }
                for goal in self.goals
            ],
            "protected_unlocks": sorted(self.protected_unlocks),
            "metadata": copy.deepcopy(self.metadata),
        }


def action_to_dict(action: TransitionAction) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "rule_id": action.rule_id,
        "target_id": action.target_id,
        "consumes": dict(action.consumes),
        "produces": dict(action.produces),
        "consumes_objects": list(action.consumes_objects),
        "produces_objects": [obj.to_dict() for obj in action.produces_objects],
        "target_patch": copy.deepcopy(action.target_patch),
        "requires_flags": list(action.requires_flags),
        "forbids_flags": list(action.forbids_flags),
        "creates_flags": list(action.creates_flags),
        "removes_flags": list(action.removes_flags),
        "depends_on": list(action.depends_on),
        "mode_scope": list(action.mode_scope),
        "metadata": copy.deepcopy(action.metadata),
        "lifetime_scope": action.lifetime_scope,
    }


def canonical_profile_hash(state: BuildState, calculator_payload: Mapping[str, Any]) -> str:
    body = {
        "state": state.to_dict(include_history=False),
        "calculator": calculator_payload,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_profile(path: str | Path) -> OptimizationProfile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Profile JSON must contain an object")
    return OptimizationProfile.from_dict(data)


def _deep_patch(target: dict[str, Any], patch: Mapping[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_patch(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
