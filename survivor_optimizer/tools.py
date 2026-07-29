from __future__ import annotations

import json
from typing import Any

from .rules import VERIFIED_RULES
from .transitions import (
    BuildState,
    StateTransitionEngine,
    TransitionAction,
    TransitionError,
    result_to_json,
)


def _load_json_object(value: str, field_name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must decode to a JSON object")
    return parsed


def _load_json_actions(value: str) -> list[TransitionAction]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"actions_json is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, list):
        raise ValueError("actions_json must decode to a JSON array")
    return [TransitionAction.from_dict(item) for item in parsed]


def simulate_transition_json(state_json: str, action_json: str) -> str:
    """Validate and simulate one inventory/build transition without damage math."""
    try:
        state = BuildState.from_dict(_load_json_object(state_json, "state_json"))
        action = TransitionAction.from_dict(_load_json_object(action_json, "action_json"))
        engine = StateTransitionEngine(VERIFIED_RULES)
        before = state.clone()
        receipt = engine.apply(state, action)
        payload = {
            "ok": True,
            "action_id": receipt.action_id,
            "rule_id": receipt.rule.rule_id,
            "verification_status": receipt.rule.verification_status,
            "resource_delta": engine.compare_resource_delta(before, state),
            "state": state.to_dict(),
        }
    except (TransitionError, ValueError, KeyError, TypeError) as exc:
        payload = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    return result_to_json(payload)


def preview_refund_json(
    state_json: str,
    actions_json: str,
    action_id: str,
) -> str:
    """Replay an action ledger and preview whether one action can be refunded."""
    try:
        state = BuildState.from_dict(_load_json_object(state_json, "state_json"))
        engine = StateTransitionEngine(VERIFIED_RULES)
        for action in _load_json_actions(actions_json):
            engine.apply(state, action)
        preview = engine.preview_refund(state, action_id)
        payload = {"ok": True, "preview": preview}
    except (TransitionError, ValueError, KeyError, TypeError) as exc:
        payload = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    return result_to_json(payload)


def plan_reset_json(
    state_json: str,
    actions_json: str,
    checkpoint_index: int,
) -> str:
    """Replay a ledger and plan a legal reset to a history index."""
    try:
        state = BuildState.from_dict(_load_json_object(state_json, "state_json"))
        engine = StateTransitionEngine(VERIFIED_RULES)
        for action in _load_json_actions(actions_json):
            engine.apply(state, action)
        plan = engine.plan_reset_to_index(state, checkpoint_index)
        payload = {"ok": True, "plan": {**plan.__dict__, "legal": plan.legal}}
    except (TransitionError, ValueError, KeyError, TypeError) as exc:
        payload = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    return result_to_json(payload)


def list_transition_rules_json() -> str:
    """Return all encoded rules with verification status and sources."""
    payload = [
        {
            "rule_id": rule.rule_id,
            "system": rule.system,
            "action_kind": rule.action_kind,
            "refund_kind": rule.refund_policy.kind.value,
            "verification_status": rule.verification_status,
            "notes": rule.notes or rule.refund_policy.notes,
            "source_urls": list(rule.source_urls),
        }
        for rule in VERIFIED_RULES
    ]
    return result_to_json(payload)
