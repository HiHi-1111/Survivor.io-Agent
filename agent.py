from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agents import Agent, Runner, WebSearchTool, function_tool
from composio import Composio
from composio_openai_agents import OpenAIAgentsProvider
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)


def calculate_damage_value(
    base_damage: float,
    attack_bonus_percent: float,
    multiplier: float = 1.0,
) -> float:
    """Calculate estimated damage from base damage, attack bonus, and multiplier."""
    if base_damage < 0 or multiplier < 0:
        raise ValueError("Damage values cannot be negative")
    return base_damage * (1 + attack_bonus_percent / 100) * multiplier


@function_tool
def calculate_damage(
    base_damage: float,
    attack_bonus_percent: float,
    multiplier: float = 1.0,
) -> float:
    """Calculate estimated damage from base damage, attack bonus, and multiplier."""
    return calculate_damage_value(base_damage, attack_bonus_percent, multiplier)


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
            "current claims and clearly distinguish official sources, community sources, "
            "estimates, and unknowns. Prefer read-only tools. Never send, publish, delete, "
            "purchase, merge, or modify an external system without explicit approval for "
            "that exact action. Never reveal credentials or private data."
        ),
        tools=[WebSearchTool(), calculate_damage, *session.tools()],
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


