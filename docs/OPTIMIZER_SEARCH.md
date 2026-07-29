# Unlock-aware profile optimizer

The optimizer searches legal account states and uses the **local sIO Tools calculator bundle**
as the damage oracle. It does not contain a replacement damage formula.

## Flow

1. Parse a profile containing inventory, owned objects, resources, current action ledger,
   and one exact sIO calculator payload per game mode.
2. Replay the ledger through the state-transition engine.
3. Recompute automatic unlocks.
4. Enumerate affordable and legal purchases, configuration changes, and verified refunds.
5. Let the constrained AI advisor and learned gate policy order or prune obviously poor paths.
6. Score selected profiles with the real calculator module from the local sIO bundle.
7. Train a log-space surrogate and action-tag bandit from exact sIO results.
8. Return only a profile whose score was verified by sIO.

## Automatic unlock invariants

### Collectible sets

A set with an exact member list is automatically active when all members are owned. The
profile cannot manually suppress this flag. Removing or deconstructing a member removes the
flag on the next recomputation.

### Xeno Pet access

The Xeno system flag is derived from four distinct normal-pet awakening types at Y5 or
higher. If a legal reset drops the account below four qualifying types, the Xeno flag and
its dependent actions disappear. Search requests may mark this flag as protected.

## Profile requirements

A profile has:

- `base_state.resources`: currencies and materials
- `base_state.objects`: equipment, pets, tech parts, mounts, collectibles, and selectors
- `ledger`: exact historic actions when refunds should be explored
- `calculator_inputs`: current sIO payload per mode
- `goals`: modes, weights, and required unlocks
- `protected_unlocks`: gates that the search may not lose

Without a ledger, the optimizer can explore new spending but cannot reconstruct historical
refund returns.

## Action catalog

Each candidate action contains:

- a legal `TransitionAction`
- resource and unlock requirements
- exact `sio_mutation` paths for verified calculator input changes
- an optional inverse mutation for refunds
- tags for the search policy
- source status and URLs

Calculator mutations must be structured source data. The compiler does not translate prose
into stats.

## AI boundary

The AI advisor may only:

- adjust candidate priority
- set exploration probability
- prune a path for a stated logical reason

It cannot provide damage, DPS, a winner, a replacement score, or a multiplier. The exact
sIO output decides the winner.

## Learning and reduced sIO usage

The optimizer caches identical payloads. It also trains:

- a hashed, pairwise, log-space surrogate of sIO output
- a per-mode action-tag bandit based on exact parent-to-child gains

These models rank which states should receive the limited sIO call budget. Once the
surrogate has enough samples, candidates whose upper prediction bound is below the best
exact result can be skipped. A minimum number of exact calls and periodic exploration are
retained to detect model drift. Final results are always exact-oracle states.

## Local sIO adapter

Set `SIO_BUNDLE_DIR` to an extracted browser snapshot containing
`_next/static/chunks`. The Node runner loads the bundle's calculator module `67727.f` at
runtime. The repository does not copy the calculator source. Every result includes a SHA-256
fingerprint of the bundle used.
