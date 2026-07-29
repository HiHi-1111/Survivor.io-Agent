from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agents import Agent, Runner, WebSearchTool, function_tool
from composio import Composio
from composio_openai_agents import OpenAIAgentsProvider
from dotenv import load_dotenv

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
            "You are a Survivor.io research and project assistant. Use web search for "
            "current claims and distinguish official sources, community sources, "
            "estimates, and unknowns. The damage formula is not verified, so never "
            "invent damage calculations. For optimizer work, use the transition tools "
            "to enforce inventory conservation, dependencies, refunds, partial losses, "
            "one-way gates, and natural battle resets. Unknown refund behavior is a "
            "hard blocker. Prefer read-only tools. Never send, publish, delete, purchase, "
            "merge, or modify an external system without explicit approval for that "
            "exact action. Never reveal credentials or private data."
        ),
        tools=[
            WebSearchTool(),
            simulate_resource_transition,
            preview_resource_refund,
            plan_build_reset,
            list_verified_transition_rules,
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
