from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import ActionCatalog, CandidateGenerator, DerivedUnlockEngine
from .learning import AdaptiveGatePolicy, FeatureEncoder, OnlineLogSurrogate, SafePathAdvisor
from .oracle import SIOBundleOracle
from .profile import OptimizationProfile
from .rules import VERIFIED_RULES
from .search import OptimizationRequest, ProfileOptimizer, operation_to_dict
from .transitions import StateTransitionEngine


def _load_object(value: str, name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must decode to a JSON object")
    return parsed


def _combined_catalog(catalog_json: str | None, repository_root: str | Path) -> ActionCatalog:
    discovered = ActionCatalog.discover_repository_data(repository_root)
    if not catalog_json:
        return discovered
    supplied = ActionCatalog.from_dict(_load_object(catalog_json, "catalog_json"))
    return ActionCatalog(
        actions=[*discovered.actions, *supplied.actions],
        collection_sets=[*discovered.collection_sets, *supplied.collection_sets],
        derived_rules=[*discovered.derived_rules, *supplied.derived_rules],
        normal_pet_type_by_name={
            **discovered.normal_pet_type_by_name,
            **supplied.normal_pet_type_by_name,
        },
    )


def validate_optimizer_profile_json(
    profile_json: str,
    catalog_json: str = "",
    repository_root: str = ".",
) -> str:
    profile = OptimizationProfile.from_dict(_load_object(profile_json, "profile_json"))
    catalog = _combined_catalog(catalog_json or None, repository_root)
    engine = StateTransitionEngine(VERIFIED_RULES)
    state = profile.materialize(engine)
    unlocks = DerivedUnlockEngine(catalog)
    derived = unlocks.recompute(state)
    payload = {
        "ok": True,
        "profile_id": profile.profile_id,
        "state": state.to_dict(),
        "derived_unlocks": sorted(derived),
        "goals": [goal.mode for goal in profile.goals],
        "refund_search_available": bool(profile.ledger),
        "warnings": []
        if profile.ledger
        else [
            "No action ledger was supplied; exact historical refund branches are unavailable."
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def list_profile_purchase_options_json(
    profile_json: str,
    request_json: str,
    catalog_json: str = "",
    repository_root: str = ".",
) -> str:
    profile = OptimizationProfile.from_dict(_load_object(profile_json, "profile_json"))
    request = OptimizationRequest.from_dict(_load_object(request_json, "request_json"))
    catalog = _combined_catalog(catalog_json or None, repository_root)
    engine = StateTransitionEngine(VERIFIED_RULES)
    state = profile.materialize(engine)
    state.mode = request.mode
    unlocks = DerivedUnlockEngine(catalog)
    unlocks.recompute(state)
    generator = CandidateGenerator(engine, catalog, unlocks)
    protected = set(profile.protected_unlocks) | set(request.preserve_unlocks)
    operations = generator.generate(
        state,
        request.mode,
        protected_unlocks=protected,
        allow_irreversible=request.allow_irreversible,
        allow_unknown_refund_forward=request.allow_unknown_refund_forward,
    )
    return json.dumps(
        {
            "ok": True,
            "mode": request.mode,
            "derived_unlocks": sorted(
                flag for flag in state.flags if flag.startswith("auto:")
            ),
            "operations": [operation_to_dict(operation) for operation in operations],
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def optimize_profile_with_sio_json(
    profile_json: str,
    request_json: str,
    catalog_json: str = "",
    repository_root: str = ".",
    sio_bundle_dir: str = "",
    model_path: str = "",
    gate_path: str = "",
) -> str:
    profile = OptimizationProfile.from_dict(_load_object(profile_json, "profile_json"))
    request = OptimizationRequest.from_dict(_load_object(request_json, "request_json"))
    catalog = _combined_catalog(catalog_json or None, repository_root)
    model = OnlineLogSurrogate.load(model_path) if model_path else OnlineLogSurrogate()
    if gate_path and Path(gate_path).exists():
        gate = AdaptiveGatePolicy.from_dict(
            json.loads(Path(gate_path).read_text(encoding="utf-8"))
        )
    else:
        gate = AdaptiveGatePolicy()
    oracle = SIOBundleOracle(bundle_dir=sio_bundle_dir or None)
    optimizer = ProfileOptimizer(
        StateTransitionEngine(VERIFIED_RULES),
        catalog,
        oracle,
        surrogate=model,
        encoder=FeatureEncoder(dimensions=model.dimensions),
        gate_policy=gate,
        advisor=SafePathAdvisor(),
    )
    result = optimizer.optimize(profile, request)
    if model_path:
        model.save(model_path)
    if gate_path:
        Path(gate_path).write_text(
            json.dumps(gate.to_dict(), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    payload = result.to_dict()
    payload["sio_bundle_fingerprint"] = oracle.bundle_fingerprint()
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
