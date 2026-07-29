from __future__ import annotations

from .transitions import RefundKind, RefundPolicy, TransitionRule

APP_STORE = "https://apps.apple.com/us/app/survivor-io/id1528941310"
ASTRAL_WIKI = "https://survivorio.fandom.com/wiki/Astral_forge"
LEVEL_DOWN = "https://gamerdigest.com/survivor-io-level-down-items/"
MERGING_WIKI = "https://survivorio.fandom.com/wiki/Merging"
SS_WIKI = "https://survivorio.fandom.com/wiki/SS_equipment"
XENO_GUIDE = "https://clashiverse.com/survivor-io-xeno-pets-tier-list/"
DRIVE_GUIDE = (
    "https://docs.google.com/document/d/"
    "1BJK2oTB44WENmvroWX__wf5ZUuwZIeAYgCMsorrUU7c"
)
SURVIVOR_SYNERGY = (
    "https://www.facebook.com/SurvivorHabby/posts/"
    "hello-survivors-hqs-got-a-major-update-for-the-survivor-arsenal-"
    "its-the-new-surv/576506065079099/"
)


def _rule(
    rule_id: str,
    system: str,
    action_kind: str,
    refund_kind: RefundKind,
    verification: str,
    *,
    sources: tuple[str, ...] = (),
    notes: str = "",
    ratios: dict[str, float] | None = None,
    fixed_returns: dict[str, int] | None = None,
    reset_costs: dict[str, int] | None = None,
    unknown_policy: str = "block",
    required_metadata: dict[str, object] | None = None,
) -> TransitionRule:
    return TransitionRule(
        rule_id=rule_id,
        system=system,
        action_kind=action_kind,
        refund_policy=RefundPolicy(
            kind=refund_kind,
            resource_refund_ratios=ratios or {},
            fixed_returns=fixed_returns or {},
            reset_costs=reset_costs or {},
            unknown_resource_policy=unknown_policy,
            required_action_metadata=required_metadata or {},
            notes=notes,
        ),
        verification_status=verification,
        source_urls=sources,
    )


VERIFIED_RULES: tuple[TransitionRule, ...] = (
    _rule(
        "loadout.change",
        "loadout",
        "configuration",
        RefundKind.FULL,
        "engine rule; no inventory is consumed",
        notes="Equipping or assigning owned objects changes configuration only.",
    ),
    _rule(
        "battle.skill_pick",
        "battle",
        "ephemeral progression",
        RefundKind.NONE,
        "verified community wiki behavior",
        sources=("https://survivorio.fandom.com/wiki/Skills",),
        notes=(
            "Committed for the current run. Use lifetime_scope='battle_run'; "
            "a natural run reset clears it."
        ),
    ),
    _rule(
        "equipment.level_upgrade",
        "equipment",
        "level upgrade",
        RefundKind.FULL,
        "exact mechanic quoted from the in-game Level Down screen",
        sources=(LEVEL_DOWN,),
        notes="Level Down returns 100% of Designs and Gold and returns the item to level 1.",
    ),
    _rule(
        "equipment.merge_grade",
        "equipment",
        "grade merge",
        RefundKind.UNKNOWN,
        "merge cost verified; complete reversal table not verified",
        sources=(MERGING_WIKI,),
        notes="Block grade rollback until current return outputs are verified.",
    ),
    _rule(
        "equipment.salvage",
        "equipment",
        "salvage conversion",
        RefundKind.NONE,
        "verified system behavior",
        sources=(ASTRAL_WIKI,),
        notes="Consumes equipment and creates the explicit forge-material outputs.",
    ),
    _rule(
        "equipment.astral_forge",
        "equipment",
        "astral forge",
        RefundKind.UNKNOWN,
        "forge inputs verified; reversal not verified",
        sources=(ASTRAL_WIKI,),
    ),
    _rule(
        "equipment.cosmic_cast",
        "equipment",
        "SS cosmic cast",
        RefundKind.UNKNOWN,
        "creation cost verified; reverse-cast behavior unknown",
        sources=(SS_WIKI,),
    ),
    _rule(
        "equipment.chaos_fusion",
        "equipment",
        "chaos fusion",
        RefundKind.UNKNOWN,
        "feature verified; refund behavior unknown",
        sources=(APP_STORE,),
    ),
    _rule(
        "choice.consume",
        "inventory",
        "selector choice",
        RefundKind.NONE,
        "container behavior",
        notes="The unopened selector is consumed when one reward is selected.",
    ),
    _rule(
        "random_container.open",
        "inventory",
        "random container",
        RefundKind.NONE,
        "container behavior",
        notes="Opening commits a one-way random outcome.",
    ),
    _rule(
        "survivor.level_upgrade",
        "survivor",
        "level investment",
        RefundKind.UNKNOWN,
        "free reset officially announced; exact return map not verified",
        sources=(APP_STORE,),
    ),
    _rule(
        "survivor.awakening",
        "survivor",
        "awakening investment",
        RefundKind.UNKNOWN,
        "refund behavior unknown",
        sources=(APP_STORE,),
    ),
    _rule(
        "survivor.synergy_overage_refund",
        "survivor",
        "automatic overage refund",
        RefundKind.FULL,
        "official announcement",
        sources=(SURVIVOR_SYNERGY,),
        notes=(
            "Only record resources explicitly identified as overage above the automatic "
            "level-120 conversion; exclude the activation cost."
        ),
    ),
    _rule(
        "pet.merge",
        "normal_pet",
        "pet merge",
        RefundKind.NONE,
        "longstanding community-documented behavior",
        sources=(MERGING_WIKI,),
        notes="Normal pet merge is treated as a one-way gate.",
    ),
    _rule(
        "pet.awakening",
        "normal_pet",
        "awakening investment",
        RefundKind.UNKNOWN,
        "exact material returns not verified",
        sources=(APP_STORE,),
    ),
    _rule(
        "pet.affection.favorite_gift",
        "normal_pet",
        "affection gift",
        RefundKind.CONDITIONAL,
        "Discord-derived guide plus official reset feature",
        sources=(DRIVE_GUIDE, APP_STORE),
        notes="Favorite toys are returned at a 1:1 ratio through Pet Affection reset.",
        unknown_policy="full",
        required_metadata={"favorite_toy": True},
    ),
    _rule(
        "pet.affection.other_gift",
        "normal_pet",
        "affection gift",
        RefundKind.UNKNOWN,
        "non-favorite toy return behavior not verified",
        sources=(DRIVE_GUIDE, APP_STORE),
    ),
    _rule(
        "xeno.cookie_investment",
        "xeno_pet",
        "pet level investment",
        RefundKind.PARTIAL,
        "current community guide agrees with Discord-derived guide",
        sources=(XENO_GUIDE, DRIVE_GUIDE),
        notes="Dismissing an upgraded Xeno Pet returns 90% of invested Pet Cookies.",
        ratios={"pet_cookie": 0.90},
    ),
    _rule(
        "xeno.dismiss",
        "xeno_pet",
        "dismissal conversion",
        RefundKind.NONE,
        "current community guide",
        sources=(XENO_GUIDE,),
        notes="The action must list its exact crystal and cookie outputs.",
    ),
    _rule(
        "xeno.skill_elixir",
        "xeno_pet",
        "skill reset",
        RefundKind.NONE,
        "Discord-derived guide",
        sources=(DRIVE_GUIDE,),
        notes="Single-use item that replaces one selected skill on one level-90 pet.",
    ),
    _rule(
        "xeno.skill_reforge",
        "xeno_pet",
        "random reforge",
        RefundKind.NONE,
        "Discord-derived guide",
        sources=(DRIVE_GUIDE,),
        notes="Spent currency and the previous random roll are not recoverable.",
    ),
    _rule(
        "tech.merge",
        "tech_part",
        "grade merge",
        RefundKind.UNKNOWN,
        "merge costs verified; unmerge behavior not verified",
        sources=(MERGING_WIKI,),
    ),
    _rule(
        "tech.twinborn_fusion",
        "tech_part",
        "Twinborn fusion",
        RefundKind.UNKNOWN,
        "mode behavior known; material reversal unknown",
        sources=(DRIVE_GUIDE,),
    ),
    _rule(
        "tech.resonance_support_assignment",
        "tech_part",
        "resonance loadout",
        RefundKind.FULL,
        "Discord-derived guide and official save-function note",
        sources=(DRIVE_GUIDE, APP_STORE),
        notes="Redistributing owned assist parts changes configuration only.",
    ),
    _rule(
        "tech.resonance_chip_investment",
        "tech_part",
        "chip investment",
        RefundKind.UNKNOWN,
        "slot-specific investment verified; refund rule not found",
        sources=(DRIVE_GUIDE,),
    ),
    _rule(
        "mount.component_place",
        "mount",
        "component placement",
        RefundKind.FULL,
        "Discord-derived guide",
        sources=(DRIVE_GUIDE,),
        notes="Moving an owned component between boards is reversible.",
    ),
    _rule(
        "mount.component_merge",
        "mount",
        "component merge",
        RefundKind.NONE,
        "Discord-derived guide",
        sources=(DRIVE_GUIDE,),
        notes="Consumes components and randomizes the resulting stat.",
    ),
    _rule(
        "mount.component_refine",
        "mount",
        "component refine",
        RefundKind.NONE,
        "Discord-derived guide",
        sources=(DRIVE_GUIDE,),
        notes="Consumes essence and replaces the previous stat with a random result.",
    ),
    _rule(
        "mount.star_upgrade",
        "mount",
        "mount star upgrade",
        RefundKind.UNKNOWN,
        "upgrade known; refund table not verified",
        sources=(APP_STORE, DRIVE_GUIDE),
    ),
    _rule(
        "collectible.star_upgrade",
        "collectible",
        "collectible star upgrade",
        RefundKind.UNKNOWN,
        "deconstructor announced; exact eligibility and returns unknown",
        sources=(APP_STORE,),
    ),
    _rule(
        "collectible.deconstruct",
        "collectible",
        "deconstruction conversion",
        RefundKind.NONE,
        "feature officially announced",
        sources=(APP_STORE,),
        notes="The action must list exact verified outputs; conversion is one-way.",
    ),
    _rule(
        "collectible.custom_slot_assignment",
        "collectible",
        "display assignment",
        RefundKind.FULL,
        "Discord-derived guide",
        sources=(DRIVE_GUIDE,),
        notes="Changing which owned collectible is displayed is reversible.",
    ),
)


def get_rule_registry() -> dict[str, TransitionRule]:
    return {rule.rule_id: rule for rule in VERIFIED_RULES}
