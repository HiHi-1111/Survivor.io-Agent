# State-transition optimizer

The transition layer answers one question before damage optimization begins:

> Can this account legally move from build A to build B, and what resources are returned,
> lost, consumed, or permanently committed?

It does not calculate damage.

## State

A `BuildState` contains:

- `resources`: Gold, Designs, cores, shards, chips, cookies, and other fungible inventory
- `objects`: individual equipment, pets, tech parts, mounts, and collectibles
- `flags`: permanent or temporary unlock conditions
- `mode`: the current optimization scenario
- `history`: exact action receipts
- `checkpoints`: named history positions used for reset planning

## Action

A `TransitionAction` may consume or produce resources and objects, patch an object's state,
require or create flags, depend on earlier actions, restrict itself to modes, and declare
an account or temporary lifetime scope.

The engine rejects negative quantities, duplicate action IDs, missing inventory, missing
objects, missing flags, and missing dependencies.

## Refund behavior

| Kind | Behavior |
|---|---|
| `full` | Return exact recorded inputs and restore the previous target state. |
| `partial` | Return only verified percentages or fixed resources and record the loss. |
| `none` | Block rollback because the action is a one-way gate. |
| `conditional` | Require exact verified metadata before refunding. |
| `unknown` | Block rollback until current sources establish the return table. |

Partial rules block any consumed resource whose return behavior is not explicitly listed.

## Dependency protection

An action cannot be refunded while a later active action:

- explicitly depends on it
- modifies the same target
- consumes an object it produced

This prevents duplicated items and illegal inventory states.

## Reset planning

`plan_reset_to_index` tests rollback in reverse order on a cloned state. It reports legal
rollback order, blockers, returns, irreversible losses, and reset-item costs. The original
state is not changed.

## Natural battle reset

In-battle skill picks are committed during a run but disappear when the run restarts.
Actions marked `lifetime_scope="battle_run"` or `"mode_attempt"` can be cleared by a
natural reset only when they did not consume permanent inventory.

A natural reset is not a refund and cannot recover account resources.

## Conservative initial rules

The first registry includes:

- 100% Equipment Level Down return of Gold and Designs
- irreversible selector and random-container opening
- irreversible equipment salvage conversion
- unknown grade-merge, Astral Forge, Cosmic Cast, and Chaos Fusion reversal
- partial Xeno Pet Cookie return at 90%
- conditional 1:1 favorite-toy return through Pet Affection reset
- one-way pet merge, Xeno skill reroll, mount component merge, and component refine
- reversible loadout, tech support assignment, component placement, and custom collection
  assignment
- unknown Survivor, awakening, mount-star, collectible, and chip return tables

Unknown rules remain blocked until a source proves the exact current behavior.

## JSON example

```json
{
  "action_id": "upgrade-kunai-20",
  "rule_id": "equipment.level_upgrade",
  "target_id": "kunai",
  "consumes": {
    "gold": 4000,
    "weapon_design": 40
  },
  "target_patch": {
    "level": 20
  }
}
```

The receipt stores the exact inputs, so Equipment Level Down can return those same
resources without reconstructing them from an approximate cost curve.
