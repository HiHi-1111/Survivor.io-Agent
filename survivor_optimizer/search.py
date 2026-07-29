from __future__ import annotations

import copy
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Mapping

from .catalog import (
    ActionCatalog,
    CandidateGenerator,
    CandidateOperation,
    DerivedUnlockEngine,
)
from .learning import (
    AdaptiveGatePolicy,
    FeatureEncoder,
    OnlineLogSurrogate,
    Prediction,
    SafePathAdvisor,
    choose_with_exploration,
)
from .oracle import CachedOracle, DamageOracle
from .profile import OptimizationProfile, action_to_dict, canonical_profile_hash
from .transitions import BuildState, StateTransitionEngine


@dataclass(frozen=True)
class OptimizationRequest:
    mode: str
    max_depth: int = 5
    beam_width: int = 12
    oracle_budget: int = 120
    candidates_per_depth: int = 36
    final_verify_count: int = 5
    exploration_probability: float = 0.12
    surrogate_prune_confidence: float = 0.90
    surrogate_margin_ratio: float = 0.01
    minimum_exact_per_depth: int = 2
    allow_irreversible: bool = True
    allow_unknown_refund_forward: bool = True
    preserve_unlocks: tuple[str, ...] = ()
    min_improvement_ratio: float = 0.0
    random_seed: int = 1

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OptimizationRequest:
        request = cls(
            mode=str(data.get("mode", "ee")),
            max_depth=int(data.get("max_depth", 5)),
            beam_width=int(data.get("beam_width", 12)),
            oracle_budget=int(data.get("oracle_budget", 120)),
            candidates_per_depth=int(data.get("candidates_per_depth", 36)),
            final_verify_count=int(data.get("final_verify_count", 5)),
            exploration_probability=float(data.get("exploration_probability", 0.12)),
            surrogate_prune_confidence=float(
                data.get("surrogate_prune_confidence", 0.90)
            ),
            surrogate_margin_ratio=float(data.get("surrogate_margin_ratio", 0.01)),
            minimum_exact_per_depth=int(data.get("minimum_exact_per_depth", 2)),
            allow_irreversible=bool(data.get("allow_irreversible", True)),
            allow_unknown_refund_forward=bool(
                data.get("allow_unknown_refund_forward", True)
            ),
            preserve_unlocks=tuple(str(v) for v in data.get("preserve_unlocks", [])),
            min_improvement_ratio=float(data.get("min_improvement_ratio", 0.0)),
            random_seed=int(data.get("random_seed", 1)),
        )
        if request.max_depth < 0 or request.beam_width <= 0 or request.oracle_budget <= 0:
            raise ValueError("Depth must be non-negative and widths/budgets must be positive")
        if request.minimum_exact_per_depth <= 0:
            raise ValueError("minimum_exact_per_depth must be positive")
        if not 0 <= request.surrogate_prune_confidence <= 1:
            raise ValueError("surrogate_prune_confidence must be between 0 and 1")
        if request.surrogate_margin_ratio < 0:
            raise ValueError("surrogate_margin_ratio cannot be negative")
        return request


@dataclass
class SearchNode:
    state: BuildState
    calculator_payload: dict[str, Any]
    path: list[CandidateOperation] = field(default_factory=list)
    exact_score: float | None = None
    prediction: Prediction | None = None
    priority: float = 0.0
    parent_exact_score: float | None = None

    @property
    def action_ids(self) -> list[str]:
        return [operation.operation_id for operation in self.path]


@dataclass
class OptimizationResult:
    mode: str
    baseline_score: float
    best_score: float
    best_state: dict[str, Any]
    best_calculator_payload: dict[str, Any]
    best_path: list[dict[str, Any]]
    oracle_calls: int
    oracle_cache_hits: int
    explored_states: int
    pruned_states: int
    model_samples: int
    model_residual_ema: float
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__dict__)


class ProfileOptimizer:
    """Beam search whose final objective always comes from the sIO oracle.

    AI and learned models may only prune or order candidates. A candidate cannot become
    the reported winner unless it has been scored by the exact oracle.
    """

    def __init__(
        self,
        transition_engine: StateTransitionEngine,
        catalog: ActionCatalog,
        oracle: DamageOracle,
        *,
        surrogate: OnlineLogSurrogate | None = None,
        encoder: FeatureEncoder | None = None,
        gate_policy: AdaptiveGatePolicy | None = None,
        advisor: SafePathAdvisor | None = None,
    ) -> None:
        self.transition_engine = transition_engine
        self.catalog = catalog
        self.unlock_engine = DerivedUnlockEngine(catalog)
        self.generator = CandidateGenerator(transition_engine, catalog, self.unlock_engine)
        self.oracle = oracle if isinstance(oracle, CachedOracle) else CachedOracle(oracle)
        self.surrogate = surrogate or OnlineLogSurrogate()
        self.encoder = encoder or FeatureEncoder(dimensions=self.surrogate.dimensions)
        self.gate_policy = gate_policy or AdaptiveGatePolicy()
        self.advisor = advisor or SafePathAdvisor()

    def optimize(
        self,
        profile: OptimizationProfile,
        request: OptimizationRequest,
    ) -> OptimizationResult:
        random_source = random.Random(request.random_seed)
        state = profile.materialize(self.transition_engine)
        state.mode = request.mode
        self.unlock_engine.recompute(state)
        payload = profile.calculator_for_mode(request.mode)
        protected = set(profile.protected_unlocks) | set(request.preserve_unlocks)
        for goal in profile.goals:
            if goal.mode == request.mode:
                protected.update(goal.required_unlocks)
        missing_protected = protected - state.flags
        if missing_protected:
            raise ValueError(
                "Profile does not satisfy required unlocks: "
                f"{sorted(missing_protected)}"
            )

        baseline_score = self.oracle.score(payload)
        baseline_features = self.encoder.encode(state, payload, request.mode)
        self.surrogate.update(baseline_features, baseline_score)
        base_node = SearchNode(
            state=state,
            calculator_payload=payload,
            exact_score=baseline_score,
            parent_exact_score=baseline_score,
        )
        beam = [base_node]
        exact_nodes = [base_node]
        seen = {canonical_profile_hash(state, payload)}
        explored = 1
        pruned = 0
        warnings: list[str] = []
        surrogate_pruned = 0

        for _depth in range(request.max_depth):
            proposed: list[SearchNode] = []
            for parent in beam:
                operations = self.generator.generate(
                    parent.state,
                    request.mode,
                    protected_unlocks=protected,
                    allow_irreversible=request.allow_irreversible,
                    allow_unknown_refund_forward=request.allow_unknown_refund_forward,
                )
                for operation in operations:
                    advisor = self.advisor.decide(parent.state, operation, request.mode)
                    if advisor.prune:
                        pruned += 1
                        continue
                    child = self._apply_operation(parent, operation)
                    self.unlock_engine.recompute(child.state)
                    if protected - child.state.flags:
                        pruned += 1
                        continue
                    key = canonical_profile_hash(child.state, child.calculator_payload)
                    if key in seen:
                        continue
                    seen.add(key)
                    features = self.encoder.encode(
                        child.state, child.calculator_payload, request.mode
                    )
                    prediction = self.surrogate.predict(features)
                    child.prediction = prediction
                    child.priority = (
                        advisor.priority_adjustment
                        + self.gate_policy.priority(request.mode, operation.tags)
                        + math.log(max(prediction.value, 1e-12))
                    )
                    child.parent_exact_score = parent.exact_score
                    proposed.append(child)
                    explored += 1

            if not proposed or self.oracle.calls >= request.oracle_budget:
                break
            proposed.sort(key=lambda node: node.priority, reverse=True)
            best_exact_so_far = max(
                float(node.exact_score or 0.0) for node in exact_nodes
            )
            competitive: list[SearchNode] = []
            confidently_dominated: list[SearchNode] = []
            for node in proposed:
                prediction = node.prediction
                if (
                    prediction is not None
                    and prediction.confidence >= request.surrogate_prune_confidence
                    and prediction.upper
                    < best_exact_so_far * (1.0 + request.surrogate_margin_ratio)
                ):
                    confidently_dominated.append(node)
                else:
                    competitive.append(node)

            minimum = min(request.minimum_exact_per_depth, len(proposed))
            if len(competitive) < minimum:
                needed = minimum - len(competitive)
                competitive.extend(confidently_dominated[:needed])
                confidently_dominated = confidently_dominated[needed:]
            surrogate_pruned += len(confidently_dominated)
            pruned += len(confidently_dominated)

            budget_left = request.oracle_budget - self.oracle.calls
            exact_count = min(
                request.candidates_per_depth, budget_left, len(competitive)
            )
            selected = choose_with_exploration(
                competitive,
                exact_count,
                request.exploration_probability,
                random_source,
            )
            # Periodically challenge a learned pruning decision so the surrogate can
            # correct drift. This can replace, but never add, an exact sIO call.
            if (
                selected
                and confidently_dominated
                and random_source.random() < request.exploration_probability
            ):
                selected[-1] = random_source.choice(confidently_dominated)
            payloads = [node.calculator_payload for node in selected]
            scores = self.oracle.score_many(payloads)
            for node, score in zip(selected, scores, strict=True):
                node.exact_score = score
                features = self.encoder.encode(
                    node.state, node.calculator_payload, request.mode
                )
                self.surrogate.update(features, score)
                parent_score = node.parent_exact_score or baseline_score
                tags = node.path[-1].tags if node.path else ()
                self.gate_policy.observe(request.mode, tags, parent_score, score)
                exact_nodes.append(node)
            selected.sort(key=lambda node: float(node.exact_score or 0), reverse=True)
            beam = selected[: request.beam_width]
            if not beam:
                break

        exact_nodes.sort(key=lambda node: float(node.exact_score or 0), reverse=True)
        best = exact_nodes[0]
        if best.exact_score is None:
            raise RuntimeError("Optimizer attempted to return an unverified candidate")
        if best.exact_score < baseline_score * (1 + request.min_improvement_ratio):
            best = base_node
        if not profile.ledger:
            warnings.append(
                "Profile has no action ledger, so historical refund branches were not available."
            )
        if self.surrogate.samples < self.surrogate.min_confident_samples:
            warnings.append(
                "The learned sIO surrogate is still warming up; it was used only for ordering."
            )
        elif surrogate_pruned:
            warnings.append(
                f"The learned surrogate skipped {surrogate_pruned} confidently dominated "
                "states; periodic exact sIO exploration remained enabled."
            )

        return OptimizationResult(
            mode=request.mode,
            baseline_score=baseline_score,
            best_score=float(best.exact_score),
            best_state=best.state.to_dict(),
            best_calculator_payload=copy.deepcopy(best.calculator_payload),
            best_path=[operation_to_dict(operation) for operation in best.path],
            oracle_calls=self.oracle.calls,
            oracle_cache_hits=self.oracle.cache_hits,
            explored_states=explored,
            pruned_states=pruned,
            model_samples=self.surrogate.samples,
            model_residual_ema=self.surrogate.residual_ema,
            warnings=warnings,
        )

    def _apply_operation(
        self, parent: SearchNode, operation: CandidateOperation
    ) -> SearchNode:
        state = parent.state.clone()
        payload = copy.deepcopy(parent.calculator_payload)
        if operation.kind == "apply":
            if operation.action is None:
                raise ValueError("Apply operation is missing its action")
            self.transition_engine.apply(state, operation.action.transition)
            payload = operation.action.sio_mutation.apply(payload)
        elif operation.kind == "refund":
            if not operation.refund_action_id:
                raise ValueError("Refund operation is missing its action ID")
            receipt = next(
                (
                    receipt
                    for receipt in reversed(state.history)
                    if receipt.active and receipt.action_id == operation.refund_action_id
                ),
                None,
            )
            if receipt is None:
                raise ValueError(f"Refund action not found: {operation.refund_action_id}")
            inverse = receipt.action.metadata.get("sio_inverse_mutation", {})
            self.transition_engine.refund(state, operation.refund_action_id)
            from .catalog import SioMutation

            payload = SioMutation.from_dict(inverse).apply(payload)
        else:
            raise ValueError(f"Unsupported candidate operation kind: {operation.kind}")
        return SearchNode(
            state=state,
            calculator_payload=payload,
            path=[*parent.path, operation],
        )


def operation_to_dict(operation: CandidateOperation) -> dict[str, Any]:
    result = {
        "operation_id": operation.operation_id,
        "kind": operation.kind,
        "tags": list(operation.tags),
    }
    if operation.action is not None:
        result["action_key"] = operation.action.action_key
        result["transition"] = action_to_dict(operation.action.transition)
        result["source_status"] = operation.action.source_status
        result["source_urls"] = list(operation.action.source_urls)
    if operation.refund_action_id:
        result["refund_action_id"] = operation.refund_action_id
    return result


def optimize_profile_json(
    profile_json: str,
    action_catalog_json: str,
    request_json: str,
    optimizer: ProfileOptimizer,
) -> str:
    profile_data = json.loads(profile_json)
    catalog_data = json.loads(action_catalog_json)
    request_data = json.loads(request_json)
    profile = OptimizationProfile.from_dict(profile_data)
    optimizer.catalog = ActionCatalog.from_dict(catalog_data)
    optimizer.unlock_engine = DerivedUnlockEngine(optimizer.catalog)
    optimizer.generator = CandidateGenerator(
        optimizer.transition_engine,
        optimizer.catalog,
        optimizer.unlock_engine,
    )
    result = optimizer.optimize(profile, OptimizationRequest.from_dict(request_data))
    return json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
