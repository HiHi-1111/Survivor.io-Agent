from __future__ import annotations

import json

import pytest

from survivor_optimizer import (
    BuildState,
    GameObject,
    RefundBlockedError,
    StateTransitionEngine,
    TransitionAction,
    VERIFIED_RULES,
)
from survivor_optimizer.tools import plan_reset_json, simulate_transition_json


@pytest.fixture()
def engine() -> StateTransitionEngine:
    return StateTransitionEngine(VERIFIED_RULES)


def test_equipment_level_down_returns_all_resources(
    engine: StateTransitionEngine,
) -> None:
    state = BuildState(
        resources={"gold": 10_000, "weapon_design": 100},
        objects={
            "kunai": GameObject(
                object_id="kunai",
                system="equipment",
                state={"level": 1},
            )
        },
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="upgrade-kunai",
            rule_id="equipment.level_upgrade",
            target_id="kunai",
            consumes={"gold": 4_000, "weapon_design": 40},
            target_patch={"level": 20},
        ),
    )
    preview = engine.refund(state, "upgrade-kunai")
    assert preview.returned_resources == {"gold": 4_000, "weapon_design": 40}
    assert state.resources == {"gold": 10_000, "weapon_design": 100}
    assert state.objects["kunai"].state["level"] == 1


def test_xeno_cookie_refund_is_90_percent(engine: StateTransitionEngine) -> None:
    state = BuildState(
        resources={"pet_cookie": 20_000},
        objects={
            "capy": GameObject(
                object_id="capy",
                system="xeno_pet",
                state={"level": 1},
            )
        },
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="level-capy",
            rule_id="xeno.cookie_investment",
            target_id="capy",
            consumes={"pet_cookie": 10_001},
            target_patch={"level": 30},
        ),
    )
    preview = engine.refund(state, "level-capy")
    assert preview.returned_resources == {"pet_cookie": 9_000}
    assert preview.lost_resources == {"pet_cookie": 1_001}
    assert state.resources["pet_cookie"] == 18_999


def test_partial_refund_blocks_unverified_resources(
    engine: StateTransitionEngine,
) -> None:
    state = BuildState(
        resources={"pet_cookie": 1_000, "xeno_core": 1},
        objects={
            "capy": GameObject(
                object_id="capy",
                system="xeno_pet",
                state={"level": 1},
            )
        },
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="mixed-investment",
            rule_id="xeno.cookie_investment",
            target_id="capy",
            consumes={"pet_cookie": 1_000, "xeno_core": 1},
            target_patch={"level": 10},
        ),
    )
    preview = engine.preview_refund(state, "mixed-investment")
    assert not preview.allowed
    assert any("xeno_core" in blocker for blocker in preview.blockers)


def test_unknown_rule_is_a_hard_blocker(engine: StateTransitionEngine) -> None:
    state = BuildState(
        resources={"excellent_weapon": 1},
        objects={
            "weapon": GameObject(
                object_id="weapon",
                system="equipment",
                state={"grade": "Excellent"},
            )
        },
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="merge-weapon",
            rule_id="equipment.merge_grade",
            target_id="weapon",
            consumes={"excellent_weapon": 1},
            target_patch={"grade": "Excellent+1"},
        ),
    )
    preview = engine.preview_refund(state, "merge-weapon")
    assert not preview.allowed
    assert "Refund behavior is not verified" in preview.blockers
    with pytest.raises(RefundBlockedError):
        engine.refund(state, "merge-weapon")


def test_selector_choice_is_irreversible(engine: StateTransitionEngine) -> None:
    state = BuildState(resources={"s_selector": 1})
    engine.apply(
        state,
        TransitionAction(
            action_id="choose-lightchaser",
            rule_id="choice.consume",
            consumes={"s_selector": 1},
            produces_objects=(
                GameObject(
                    object_id="lightchaser-1",
                    system="equipment",
                    state={"grade": "Excellent"},
                ),
            ),
        ),
    )
    preview = engine.preview_refund(state, "choose-lightchaser")
    assert not preview.allowed
    assert "Rule is irreversible" in preview.blockers


def test_dependency_order_is_enforced(engine: StateTransitionEngine) -> None:
    state = BuildState(
        resources={"gold": 10_000, "weapon_design": 100},
        objects={
            "kunai": GameObject(
                object_id="kunai",
                system="equipment",
                state={"level": 1},
            )
        },
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="level-10",
            rule_id="equipment.level_upgrade",
            target_id="kunai",
            consumes={"gold": 1_000, "weapon_design": 10},
            target_patch={"level": 10},
        ),
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="level-20",
            rule_id="equipment.level_upgrade",
            target_id="kunai",
            consumes={"gold": 2_000, "weapon_design": 20},
            target_patch={"level": 20},
            depends_on=("level-10",),
        ),
    )
    assert not engine.preview_refund(state, "level-10").allowed
    engine.refund(state, "level-20")
    engine.refund(state, "level-10")
    assert state.resources == {"gold": 10_000, "weapon_design": 100}


def test_reset_plan_stops_at_one_way_gate(engine: StateTransitionEngine) -> None:
    state = BuildState(
        resources={"gold": 5_000, "weapon_design": 50, "selector": 1},
        objects={
            "kunai": GameObject(
                object_id="kunai",
                system="equipment",
                state={"level": 1},
            )
        },
    )
    engine.checkpoint(state, "clean")
    engine.apply(
        state,
        TransitionAction(
            action_id="level-kunai",
            rule_id="equipment.level_upgrade",
            target_id="kunai",
            consumes={"gold": 1_000, "weapon_design": 10},
            target_patch={"level": 10},
        ),
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="open-selector",
            rule_id="choice.consume",
            consumes={"selector": 1},
        ),
    )
    plan = engine.plan_reset_to_checkpoint(state, "clean")
    assert not plan.legal
    assert plan.rollback_order == ["open-selector", "level-kunai"]


def test_mode_branch_does_not_change_base(engine: StateTransitionEngine) -> None:
    base = BuildState(
        resources={"gold": 2_000, "weapon_design": 20},
        objects={
            "kunai": GameObject(
                object_id="kunai",
                system="equipment",
                state={"level": 1},
            )
        },
        mode="enders_echo",
    )
    candidate = engine.simulate_actions(
        base,
        [
            TransitionAction(
                action_id="branch-upgrade",
                rule_id="equipment.level_upgrade",
                target_id="kunai",
                consumes={"gold": 1_000, "weapon_design": 10},
                target_patch={"level": 10},
                mode_scope=("enders_echo",),
            )
        ],
    )
    assert base.objects["kunai"].state["level"] == 1
    assert candidate.objects["kunai"].state["level"] == 10


def test_natural_battle_restart_clears_only_ephemeral_state(
    engine: StateTransitionEngine,
) -> None:
    state = BuildState(
        objects={
            "run": GameObject(
                object_id="run",
                system="battle",
                state={"skills": []},
            )
        }
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="pick-rpg",
            rule_id="battle.skill_pick",
            target_id="run",
            target_patch={"skills": ["RPG"]},
            lifetime_scope="battle_run",
        ),
    )
    assert engine.reset_ephemeral_scope(state, "battle_run") == ["pick-rpg"]
    assert state.objects["run"].state["skills"] == []


def test_favorite_toy_requires_verified_metadata(
    engine: StateTransitionEngine,
) -> None:
    state = BuildState(
        resources={"yellow_pet_toy": 1},
        objects={
            "murica": GameObject(
                object_id="murica",
                system="normal_pet",
                state={"affection": 0},
            )
        },
    )
    engine.apply(
        state,
        TransitionAction(
            action_id="gift-murica",
            rule_id="pet.affection.favorite_gift",
            target_id="murica",
            consumes={"yellow_pet_toy": 1},
            target_patch={"affection": 1},
            metadata={"favorite_toy": True},
        ),
    )
    engine.refund(state, "gift-murica")
    assert state.resources["yellow_pet_toy"] == 1


def test_agent_json_tools() -> None:
    state_json = json.dumps(
        {
            "resources": {"gold": 1_000, "weapon_design": 10},
            "objects": {
                "kunai": {
                    "object_id": "kunai",
                    "system": "equipment",
                    "state": {"level": 1},
                }
            },
        }
    )
    action_json = json.dumps(
        {
            "action_id": "level-kunai",
            "rule_id": "equipment.level_upgrade",
            "target_id": "kunai",
            "consumes": {"gold": 500, "weapon_design": 5},
            "target_patch": {"level": 5},
        }
    )
    result = json.loads(simulate_transition_json(state_json, action_json))
    assert result["ok"] is True

    plan = json.loads(plan_reset_json(state_json, f"[{action_json}]", 0))
    assert plan["ok"] is True
    assert plan["plan"]["legal"] is True
