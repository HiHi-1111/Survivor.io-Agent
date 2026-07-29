from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from survivor_optimizer.catalog import ActionCatalog
from survivor_optimizer.learning import AdaptiveGatePolicy, FeatureEncoder, SafePathAdvisor
from survivor_optimizer.oracle import SIOBundleOracle
from survivor_optimizer.profile import OptimizationProfile
from survivor_optimizer.rules import VERIFIED_RULES
from survivor_optimizer.search import OptimizationRequest, ProfileOptimizer
from survivor_optimizer.torch_surrogate import TorchBatchSurrogate
from survivor_optimizer.transitions import StateTransitionEngine


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_catalog(repository_root: Path, catalog_path: Path | None) -> ActionCatalog:
    discovered = ActionCatalog.discover_repository_data(repository_root)
    if catalog_path is None:
        return discovered
    supplied = ActionCatalog.from_dict(_read_object(catalog_path))
    return ActionCatalog(
        actions=[*discovered.actions, *supplied.actions],
        collection_sets=[*discovered.collection_sets, *supplied.collection_sets],
        derived_rules=[*discovered.derived_rules, *supplied.derived_rules],
        normal_pet_type_by_name={
            **discovered.normal_pet_type_by_name,
            **supplied.normal_pet_type_by_name,
        },
    )


def _load_gate(path: Path) -> AdaptiveGatePolicy:
    if not path.exists():
        return AdaptiveGatePolicy()
    return AdaptiveGatePolicy.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _save_gate(path: Path, gate: AdaptiveGatePolicy) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(gate.to_dict(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the Survivor.io optimizer locally with exact sIO scoring."
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--sio-bundle", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--epochs-per-episode", type=int, default=3)
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--model", type=Path, default=Path("training/surrogate.pt"))
    parser.add_argument("--gate", type=Path, default=Path("training/gates.json"))
    parser.add_argument("--log", type=Path, default=Path("training/runs.jsonl"))
    parser.add_argument("--checkpoint-every", type=int, default=5)
    parser.add_argument("--torch-threads", type=int, default=max(1, (os.cpu_count() or 8) - 2))
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.episodes <= 0 or args.epochs_per_episode <= 0:
        raise ValueError("episodes and epochs-per-episode must be positive")

    import torch

    torch.set_num_threads(max(1, args.torch_threads))
    if hasattr(torch, "set_num_interop_threads"):
        torch.set_num_interop_threads(max(1, min(4, args.torch_threads)))

    profile = OptimizationProfile.from_dict(_read_object(args.profile))
    base_request = OptimizationRequest.from_dict(_read_object(args.request))
    catalog = _load_catalog(args.repository_root, args.catalog)
    gate = _load_gate(args.gate)
    if args.model.exists():
        surrogate = TorchBatchSurrogate.load(
            args.model,
            device=args.device,
            compile_model=args.compile,
        )
    else:
        surrogate = TorchBatchSurrogate(
            device=args.device,
            compile_model=args.compile,
        )

    oracle = SIOBundleOracle(bundle_dir=args.sio_bundle)
    optimizer = ProfileOptimizer(
        StateTransitionEngine(VERIFIED_RULES),
        catalog,
        oracle,
        surrogate=surrogate,
        encoder=FeatureEncoder(dimensions=surrogate.dimensions),
        gate_policy=gate,
        advisor=SafePathAdvisor(),
    )
    print(
        json.dumps(
            {
                "device": surrogate.device,
                "device_name": surrogate.device_name,
                "torch_threads": args.torch_threads,
                "sio_bundle_fingerprint": oracle.bundle_fingerprint(),
                "starting_samples": surrogate.samples,
            },
            indent=2,
        )
    )

    random_source = random.Random(args.seed)
    best_score = 0.0
    started = time.time()
    for episode in range(1, args.episodes + 1):
        episode_request = replace(
            base_request,
            random_seed=random_source.randrange(1, 2**31 - 1),
        )
        before_calls = optimizer.oracle.calls
        result = optimizer.optimize(profile, episode_request)
        training = surrogate.train_pending(epochs=args.epochs_per_episode)
        best_score = max(best_score, result.best_score)
        record = {
            "episode": episode,
            "mode": result.mode,
            "baseline_score": result.baseline_score,
            "best_score": result.best_score,
            "global_best_score": best_score,
            "oracle_calls": optimizer.oracle.calls - before_calls,
            "oracle_cache_hits": optimizer.oracle.cache_hits,
            "explored_states": result.explored_states,
            "pruned_states": result.pruned_states,
            "model_samples": surrogate.samples,
            "model_residual_ema": surrogate.residual_ema,
            "train_examples": int(training["examples"]),
            "train_loss": training["loss"],
            "elapsed_seconds": round(time.time() - started, 3),
            "best_path": result.best_path,
        }
        _append_jsonl(args.log, record)
        print(json.dumps(record, ensure_ascii=False))
        if episode % args.checkpoint_every == 0 or episode == args.episodes:
            surrogate.save(args.model)
            _save_gate(args.gate, gate)


if __name__ == "__main__":
    main()
