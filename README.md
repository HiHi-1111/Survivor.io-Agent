# Survivor.io AI Assistant

A Python research and optimization agent for Survivor.io.

## Current capabilities

- Research current Survivor.io information with live web search
- Store and retrieve verified game knowledge
- Model legal inventory and build state transitions
- Track full refunds, partial refunds, one-way gates, dependencies, and unknown rules
- Recompute automatic unlocks after every state change
- Parse an account profile and enumerate affordable legal actions
- Search refund-and-rebuild paths for different game modes
- Score candidate profiles with the local sIO Tools calculator bundle
- Learn a pruning surrogate from exact sIO results while preserving exact final verification
- Train the surrogate locally with CPU search/sIO scoring and NVIDIA CUDA acceleration
- Connect external services safely through Composio

The repository does not contain a hand-written replacement damage formula. The optimizer
calls the calculator module from a user-supplied sIO Tools bundle and treats that output as
the only damage oracle.

## Quick start

1. Install Python 3.10+, Node.js, and `uv`.
2. Copy `.env.example` to `.env`.
3. Add your API keys to `.env`.
4. Extract the supplied sIO Tools snapshot and set `SIO_BUNDLE_DIR` to its directory.
5. Install dependencies:

```bash
uv sync
```

6. Run tests:

```bash
uv run pytest
```

7. Run the agent:

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
- `none`: irreversible one-way conversion, not a refund
- `conditional`: refundable only when explicit verified conditions are present
- `unknown`: hard blocker until the current return table is verified

See [`docs/STATE_TRANSITIONS.md`](docs/STATE_TRANSITIONS.md) for schemas and examples.

## Profile optimizer

The profile optimizer:

1. replays the account ledger
2. recomputes collection-set, Xeno, and other derived unlocks
3. lists affordable purchases, loadout changes, and verified refund paths
4. allows AI only to order or prune the search tree
5. scores selected candidates with sIO
6. returns only an exactly scored profile

Identical calculator payloads are cached. A persisted surrogate and per-mode action policy
learn from exact sIO results and can reduce future calculator calls using confidence bounds
and periodic exact exploration.

See [`docs/OPTIMIZER_SEARCH.md`](docs/OPTIMIZER_SEARCH.md) for profile, catalog, unlock, and
sIO adapter details.

## Local CPU and GPU training

The local training runner uses the CPU for legal-state search and exact sIO calculations,
then trains a neural surrogate on an NVIDIA GPU with mixed precision. It saves resumable
model checkpoints, gate statistics, and JSONL episode logs.

```bash
uv run python scripts/check_training_hardware.py
uv run python scripts/train_optimizer.py --help
```

See [`docs/LOCAL_TRAINING.md`](docs/LOCAL_TRAINING.md) for Windows, RTX 4070, checkpoint,
and resume instructions.

## Safety model

Read-only research and local simulations can run automatically. Sending messages,
publishing content, deleting data, spending money, or changing external systems requires
explicit approval for that exact action.
