from __future__ import annotations

import os

import pytest

from survivor_optimizer import (
    ActionCatalog,
    AdaptiveGatePolicy,
    BuildState,
    CandidateOperation,
    CollectionSetDefinition,
    DerivedUnlockEngine,
    FeatureEncoder,
    GameObject,
    OnlineLogSurrogate,
    OptimizationProfile,
    OptimizationRequest,
    OptimizerAction,
    ProfileOptimizer,
    RefundKind,
    RefundPolicy,
    SafePathAdvisor,
    SIOBundleOracle,
    SioMutation,
    StateTransitionEngine,
    TransitionAction,
    TransitionRule,
)


class FakeOracle:
    def __init__(self) -> None:
        self.calls = 0

    def score(self, payload):
        return self.score_many([payload])[0]

    def score_many(self, payloads):
        self.calls += len(payloads)
        return [float(payload.get("stats", {}).get("power", 0)) for payload in payloads]


def rules():
    return (
        TransitionRule(
            rule_id="upgrade",
            system="test",
            action_kind="upgrade",
            refund_policy=RefundPolicy(kind=RefundKind.FULL),
            verification_status="test",
        ),
        TransitionRule(
            rule_id="one_way",
            system="test",
            action_kind="one way",
            refund_policy=RefundPolicy(kind=RefundKind.NONE),
            verification_status="test",
        ),
    )


def test_collection_set_is_automatic_when_all_members_are_owned():
    state = BuildState(
        objects={
            name: GameObject(
                object_id=name,
                system="collectible",
                state={"name": name, "owned": True},
            )
            for name in ("A", "B", "C", "D")
        },
        flags={"manual:other"},
    )
    catalog = ActionCatalog(
        collection_sets=[
            CollectionSetDefinition(
                set_id="SET1",
                set_name="Test Set",
                members=("A", "B", "C", "D"),
            )
        ]
    )
    unlocks = DerivedUnlockEngine(catalog)
    unlocks.recompute(state)
    assert "auto:collection_set:SET1" in state.flags
    state.flags.discard("auto:collection_set:SET1")
    unlocks.recompute(state)
    assert "auto:collection_set:SET1" in state.flags


def test_xeno_gate_is_derived_and_removed_when_a_pet_drops_below_y5():
    pets = {}
    for index in range(4):
        pets[f"pet-{index}"] = GameObject(
            object_id=f"pet-{index}",
            system="normal_pet",
            state={"pet_type": f"type-{index}", "awakening_stage": "Y5"},
        )
    state = BuildState(objects=pets)
    unlocks = DerivedUnlockEngine(ActionCatalog())
    unlocks.recompute(state)
    assert "auto:system:xeno_pet" in state.flags
    state.objects["pet-0"].state["awakening_stage"] = "Y4"
    unlocks.recompute(state)
    assert "auto:system:xeno_pet" not in state.flags


def test_ai_advisor_cannot_replace_calculator_score():
    advisor = SafePathAdvisor(callback=lambda _request: {"score": 999999})
    state = BuildState()
    with pytest.raises(ValueError):
        advisor.decide(state, CandidateOperation("x", "apply"), "ee")


def test_exact_oracle_decides_winner_even_when_advisor_prefers_bad_path():
    engine = StateTransitionEngine(rules())
    actions = [
        OptimizerAction(
            action_key="bad",
            transition=TransitionAction(action_id="bad", rule_id="upgrade"),
            sio_mutation=SioMutation(deltas={"stats.power": 1}),
            tags=("bad",),
        ),
        OptimizerAction(
            action_key="good",
            transition=TransitionAction(action_id="good", rule_id="upgrade"),
            sio_mutation=SioMutation(deltas={"stats.power": 10}),
            tags=("good",),
        ),
    ]
    catalog = ActionCatalog(actions=actions)

    def callback(request):
        return {"priority_adjustment": 100 if "bad" in request["tags"] else -100}

    optimizer = ProfileOptimizer(
        engine,
        catalog,
        FakeOracle(),
        surrogate=OnlineLogSurrogate(min_confident_samples=2),
        encoder=FeatureEncoder(),
        gate_policy=AdaptiveGatePolicy(),
        advisor=SafePathAdvisor(callback),
    )
    profile = OptimizationProfile.from_dict(
        {
            "profile_id": "p",
            "state": {},
            "calculator": {"stats": {"power": 100}},
            "mode": "ee",
        }
    )
    result = optimizer.optimize(
        profile,
        OptimizationRequest(
            mode="ee",
            max_depth=1,
            beam_width=2,
            candidates_per_depth=2,
            oracle_budget=10,
            exploration_probability=0,
        ),
    )
    assert result.best_score == 110
    assert result.best_path[0]["action_key"] == "good"


def test_protected_unlock_prunes_refund_that_would_remove_it():
    engine = StateTransitionEngine(rules())
    profile = OptimizationProfile.from_dict(
        {
            "profile_id": "p",
            "state": {},
            "ledger": [
                {
                    "action_id": "gate",
                    "rule_id": "upgrade",
                    "creates_flags": ["required:gate"],
                    "metadata": {"sio_inverse_mutation": {}},
                }
            ],
            "calculator": {"stats": {"power": 10}},
            "mode": "ee",
            "protected_unlocks": ["required:gate"],
        }
    )
    optimizer = ProfileOptimizer(engine, ActionCatalog(), FakeOracle())
    result = optimizer.optimize(
        profile,
        OptimizationRequest(mode="ee", max_depth=1, oracle_budget=5),
    )
    assert result.best_path == []


@pytest.mark.skipif(not os.getenv("SIO_BUNDLE_DIR"), reason="SIO_BUNDLE_DIR not set")
def test_supplied_sio_bundle_runner_calls_real_calculator_module():
    oracle = SIOBundleOracle(bundle_dir=os.environ["SIO_BUNDLE_DIR"])
    base = oracle.score(
        {
            "stats": {"critRate": 100, "critDamage": 200},
            "attack": {"atkBase": 100, "atkFinal": 0},
            "calculation": "multiplier",
            "game_mode": "ee",
        }
    )
    boosted = oracle.score(
        {
            "stats": {"critRate": 100, "critDamage": 200, "skillDamage": 100},
            "attack": {"atkBase": 100, "atkFinal": 0},
            "calculation": "multiplier",
            "game_mode": "ee",
        }
    )
    assert base == pytest.approx(200)
    assert boosted == pytest.approx(400)
    assert len(oracle.bundle_fingerprint()) == 64
