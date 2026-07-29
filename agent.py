from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agents import Agent, Runner, WebSearchTool, function_tool
from composio import Composio
from composio_openai_agents import OpenAIAgentsProvider
from dotenv import load_dotenv

from survivor_optimizer.optimizer_tools import (
    list_profile_purchase_options_json,
    optimize_profile_with_sio_json,
    validate_optimizer_profile_json,
)
from survivor_optimizer.tools import (
    list_transition_rules_json,
    plan_reset_json,
    preview_refund_json,
    simulate_transition_json,
)

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)


@function_tool
def simulate_resource_transition(state_json: str, action_json: str) -> str:
    """Simulate one legal inventory/build transition without damage formulas."""
    return simulate_transition_json(state_json=state_json, action_json=action_json)


@function_tool
def preview_resource_refund(
    state_json: str,
    actions_json: str,
    action_id: str,
) -> str:
    """Replay an action ledger and preview the legal refund for one action."""
    return preview_refund_json(
        state_json=state_json,
        actions_json=actions_json,
        action_id=action_id,
    )


@function_tool
def plan_build_reset(
    state_json: str,
    actions_json: str,
    checkpoint_index: int,
) -> str:
    """Plan a reset and report blockers, returned resources, and losses."""
    return plan_reset_json(
        state_json=state_json,
        actions_json=actions_json,
        checkpoint_index=checkpoint_index,
    )


@function_tool
def list_verified_transition_rules() -> str:
    """List encoded reversible, partial, irreversible, and unknown rules."""
    return list_transition_rules_json()


@function_tool
def validate_optimizer_profile(
    profile_json: str,
    catalog_json: str = "",
    repository_root: str = ".",
) -> str:
    """Validate inventory, ledger, automatic unlocks, and optimizer goals."""
    return validate_optimizer_profile_json(
        profile_json=profile_json,
        catalog_json=catalog_json,
        repository_root=repository_root,
    )


@function_tool
def list_optimizer_options(
    profile_json: str,
    request_json: str,
    catalog_json: str = "",
    repository_root: str = ".",
) -> str:
    """List legal purchases, configuration changes, and real refund branches."""
    return list_profile_purchase_options_json(
        profile_json=profile_json,
        request_json=request_json,
        catalog_json=catalog_json,
        repository_root=repository_root,
    )


@function_tool
def optimize_profile_with_sio(
    profile_json: str,
    request_json: str,
    catalog_json: str = "",
    repository_root: str = ".",
    sio_bundle_dir: str = "",
    model_path: str = "",
    gate_path: str = "",
) -> str:
    """Search legal profiles and return only a build exactly scored by sIO."""
    return optimize_profile_with_sio_json(
        profile_json=profile_json,
        request_json=request_json,
        catalog_json=catalog_json,
        repository_root=repository_root,
        sio_bundle_dir=sio_bundle_dir,
        model_path=model_path,
        gate_path=gate_path,
    )


def build_agent() -> Agent:
    missing = [
        key
        for key in ("OPENAI_API_KEY", "COMPOSIO_API_KEY")
        if not os.getenv(key)
    ]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

    composio = Composio(provider=OpenAIAgentsProvider())
    user_id = os.getenv("SURVIVOR_USER_ID", "survivor_admin_001")
    session = composio.create(user_id=user_id)

    return Agent(
        name="Survivor.io Assistant",
        instructions=(
            "You are a Survivor.io research and optimization assistant. Use web search "
            "for current claims and distinguish official sources, community sources, "
            "estimates, and unknowns. Never infer calculator mutations from prose. "
            "Validate a profile and enumerate legal actions before optimization. The AI "
            "may guide search order and prune logically invalid or clearly poor paths, "
            "but it may never provide damage, a winner, or a replacement multiplier. "
            "Only the local sIO calculator oracle may score profiles or decide the best "
            "build. Recompute automatic unlocks after every state change, including "
            "collection sets and the four-type Y5 Xeno gate. Preserve required unlocks, "
            "inventory conservation, dependencies, refunds, partial losses, one-way "
            "actions, and natural battle resets. A one-way action is not a zero-return "
            "refund. Prefer read-only tools. Never send, publish, delete, purchase, merge, "
            "or modify an external system without explicit approval for that exact action. "
            "Never reveal credentials or private data."
        ),
        tools=[
            WebSearchTool(),
            simulate_resource_transition,
            preview_resource_refund,
            plan_build_reset,
            list_verified_transition_rules,
            validate_optimizer_profile,
            list_optimizer_options,
            optimize_profile_with_sio,
            *session.tools(),
        ],
    )


async def chat() -> None:
    agent = build_agent()
    print("Survivor.io Assistant ready. Type 'exit' to stop.")

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            return
        if not user_input:
            continue

        try:
            result = await Runner.run(starting_agent=agent, input=user_input)
            print(f"\nAgent: {result.final_output}")
        except Exception as exc:
            print(f"\nError: {exc}")


if __name__ == "__main__":
    asyncio.run(chat())
