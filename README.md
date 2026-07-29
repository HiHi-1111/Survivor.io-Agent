# Survivor.io AI Assistant

A Python research and optimization agent for Survivor.io.

## Current capabilities

- Research current Survivor.io information with live web search
- Store and retrieve verified game knowledge
- Model legal inventory and build state transitions
- Track full refunds, partial refunds, one-way gates, dependencies, and unknown rules
- Branch a build for different modes without mutating the original account state
- Reset temporary battle-run state separately from permanent account progression
- Connect external services safely through Composio

The project intentionally does **not** contain a trusted damage formula yet. Unknown damage
and refund behavior remains blocked until it is verified.

## Quick start

1. Install Python 3.10+ and `uv`.
2. Copy `.env.example` to `.env`.
3. Add your API keys to `.env`.
4. Install dependencies:

```bash
uv sync
```

5. Run tests:

```bash
uv run pytest
```

6. Run the agent:

```bash
uv run python agent.py
```

## Transition engine

The `survivor_optimizer` package treats each upgrade or reset as a state transition.
Every action records exact consumed resources, produced resources, object mutations,
dependencies, mode restrictions, and its refund rule.

Refund classes:

- `full`: exact recorded inputs can be returned
- `partial`: only verified percentages or fixed returns are returned
- `none`: irreversible one-way conversion
- `conditional`: refundable only when explicit verified conditions are present
- `unknown`: hard blocker until the current return table is verified

See [`docs/STATE_TRANSITIONS.md`](docs/STATE_TRANSITIONS.md) for schemas and examples.

## Safety model

Read-only research and local simulations can run automatically. Sending messages,
publishing content, deleting data, spending money, or changing external systems requires
explicit approval for that exact action.
