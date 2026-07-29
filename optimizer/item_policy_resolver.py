from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ItemPolicyResolution:
    unlock_policy_id: str
    unlock_requirement: str
    unlock_gate_type: str
    unlock_verification: str
    default_refund_policy_id: str
    action_profile: str
    policy_confidence: str


def _contains(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def resolve_item_policy(item: Mapping[str, str]) -> ItemPolicyResolution:
    """Assign every catalog row an unlock rule and conservative refund policy."""
    name = item.get("Item_Name", "")
    description = item.get("Description", "")
    category = item.get("Primary_Category", "")
    subcategory = item.get("Subcategory", "")
    kind = item.get("Item_Kind", "")
    lifecycle = item.get("Lifecycle", "")
    is_choice = item.get("Is_Choice_Item", "") == "Yes"
    is_random = item.get("Is_Random_Reward", "") == "Yes"
    text = f"{name} {description} {subcategory}".lower()

    if name == "Xeno Pet Elixir":
        unlock = (
            "UL_XENO_MAX_LEVEL",
            "Own the item and a max-level Xeno Pet with an eligible assist-skill slot.",
            "Target state",
            "Exact localized description",
        )
        policy = ("RP_XENO_SKILL_REROLL_ONE_WAY", "Xeno skill reroll", "Exact item description")
    elif name == "Survivor Reset Vial":
        unlock = (
            "UL_SURVIVOR_RESET",
            "Own the reset item or free-reset feature and an eligible Survivor above the reset floor.",
            "Target state",
            "Exact localized description",
        )
        policy = ("RP_DIRECT_CONSUMABLE_ONE_WAY", "Reset trigger item", "Exact item description")
    elif name == "Legend Collectible Deconstructor":
        unlock = (
            "UL_LEGEND_COLLECTIBLE_RESET",
            "Own the item and an eligible Legend Collectible above 1 Gold Star.",
            "Target state",
            "Exact localized description",
        )
        policy = ("RP_DIRECT_CONSUMABLE_ONE_WAY", "Reset trigger item", "Exact item description")
    else:
        if "resonance chip" in text:
            unlock = (
                "UL_TECH_RESONANCE",
                "Own a Legend Tech Part to unlock Tech Resonance, then obtain the item.",
                "System gate",
                "Drive rule",
            )
        elif "xeno pet" in text or subcategory.startswith("Xeno Pet"):
            unlock = (
                "UL_XENO_SYSTEM",
                "Maintain four different normal-pet awakening types at Y5 and obtain the item.",
                "Account-state gate",
                "Drive rule",
            )
        elif "mount" in text:
            unlock = (
                "UL_MOUNT_SYSTEM",
                "Clear Main Chapter 80 and meet the item- or mount-specific acquisition requirement.",
                "Chapter and item gate",
                "Mount source",
            )
        elif category == "Tech Parts" or "tech part" in text:
            unlock = (
                "UL_TECH_SYSTEM",
                "Clear the Chapter 6 Tech Part unlock path and obtain the item.",
                "Chapter gate",
                "Drive rule",
            )
        elif category == "Pets" or "pet toy" in text or subcategory == "Normal Pet Material":
            unlock = (
                "UL_NORMAL_PET_SYSTEM",
                "Clear Main Chapter 9 and obtain the item.",
                "Chapter gate",
                "Drive rule",
            )
        elif subcategory == "Clan Currency":
            unlock = (
                "UL_CLAN_SYSTEM",
                "Clear Main Chapter 3 and obtain the currency.",
                "Chapter gate",
                "Drive rule",
            )
        elif _contains(text, "astral", "relic core", "eternal core", "void core", "chaos core", "base tech material"):
            unlock = (
                "UL_ASTRAL_FORGE",
                "Own at least one Legend equipment piece to unlock Astral Forge, then obtain the item.",
                "Progression gate",
                "Forge source",
            )
        elif category == "Equipment":
            unlock = (
                "UL_EQUIPMENT_ITEM",
                "Unlock Equipment access and obtain or open the item.",
                "System and ownership gate",
                "Category rule",
            )
        elif category == "Collectibles":
            unlock = (
                "UL_COLLECTIBLE_SYSTEM",
                "Have collectible chest, event, or exchange access and own the item; exact chapter is unresolved.",
                "System and ownership gate",
                "Drive explicitly says not to invent a chapter",
            )
        elif category == "Survivors":
            unlock = (
                "UL_SURVIVOR_OWNERSHIP",
                "Unlock or obtain the Survivor through its shard, event, purchase, or reward source.",
                "Ownership gate",
                "Item-specific",
            )
        elif category == "Cosmetics":
            unlock = (
                "UL_COSMETIC_OWNERSHIP",
                "Obtain the cosmetic through its event, purchase, exchange, or reward source.",
                "Ownership or event gate",
                "Item-specific",
            )
        elif category == "Keys":
            unlock = (
                "UL_LINKED_CHEST",
                "Own the key and access its linked chest.",
                "Ownership and system gate",
                "Localized description or category",
            )
        elif lifecycle in {"Limited / Event", "Upcoming / Event"} or category == "Event Items":
            unlock = (
                "UL_ACTIVE_EVENT",
                "Own the item while its linked event or exchange remains active.",
                "Time-limited gate",
                "Lifecycle classification",
            )
        elif category == "Currencies":
            unlock = (
                "UL_LINKED_SHOP_OR_MODE",
                "Own the currency and unlock its linked shop, mode, clan, or event.",
                "System and ownership gate",
                "Category rule",
            )
        elif category == "Upgrade Materials":
            unlock = (
                "UL_TARGET_SYSTEM",
                "Own the material and unlock the target upgrade system named by the item.",
                "Target-system gate",
                "Localized description or category",
            )
        elif is_choice:
            unlock = (
                "UL_SELECTOR_TARGET",
                "Own the selector and have at least one eligible unlocked option.",
                "Ownership and target gate",
                "Selector rule",
            )
        elif is_random or kind in {"Container", "Random Container"}:
            unlock = (
                "UL_CONTAINER",
                "Own the container and access any linked opening system.",
                "Ownership gate",
                "Container rule",
            )
        else:
            unlock = (
                "UL_ITEM_OWNERSHIP",
                "Obtain the item; no additional verified system gate is stored.",
                "Ownership gate",
                "Conservative fallback",
            )

        if lifecycle in {"Limited / Event", "Upcoming / Event"} or category == "Event Items":
            policy = ("RP_EVENT_EXPIRY", "Event item or currency", "Lifecycle rule")
        elif is_choice:
            policy = ("RP_SELECTOR_ONE_WAY", "Choice selector", "Conservative selector rule")
        elif is_random or kind in {"Container", "Random Container", "Key"} or category == "Keys":
            policy = ("RP_RANDOM_OPEN_ONE_WAY", "Random container or key", "Conservative opening rule")
        elif category in {"Currencies", "Upgrade Materials"}:
            policy = ("RP_SPEND_TARGET_DEPENDENT", "Spendable resource", "Target-dependent rule")
        elif category == "Utility Consumables":
            policy = ("RP_DIRECT_CONSUMABLE_ONE_WAY", "Direct-use consumable", "Conservative use rule")
        elif category in {"Cosmetics", "Survivors"} or kind in {"Character", "Cosmetic", "Collectible"}:
            policy = ("RP_NOT_APPLICABLE", "Owned asset or reference record", "No spend action")
        else:
            policy = ("RP_UNKNOWN_BLOCKED", "Unclassified action", "Safety default")

    return ItemPolicyResolution(
        unlock_policy_id=unlock[0],
        unlock_requirement=unlock[1],
        unlock_gate_type=unlock[2],
        unlock_verification=unlock[3],
        default_refund_policy_id=policy[0],
        action_profile=policy[1],
        policy_confidence=policy[2],
    )


def resolve_catalog_rows(rows: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    resolved: list[dict[str, str]] = []
    for row in rows:
        policy = resolve_item_policy(row)
        resolved.append(
            {
                **dict(row),
                "Unlock_Policy_ID": policy.unlock_policy_id,
                "Unlock_Requirement": policy.unlock_requirement,
                "Unlock_Gate_Type": policy.unlock_gate_type,
                "Unlock_Verification": policy.unlock_verification,
                "Default_Refund_Policy_ID": policy.default_refund_policy_id,
                "Default_Action_Profile": policy.action_profile,
                "Policy_Confidence": policy.policy_confidence,
            }
        )
    return resolved


def load_and_resolve_catalog(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        return resolve_catalog_rows(csv.DictReader(file))
