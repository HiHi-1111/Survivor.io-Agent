from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .catalog import CandidateOperation
from .transitions import BuildState


@dataclass(frozen=True)
class Prediction:
    value: float
    lower: float
    upper: float
    confidence: float


class FeatureEncoder:
    """Hash profile, inventory, unlock, and sIO inputs into a fixed feature vector.

    The target is log damage. Pairwise hashed interactions let the model learn repeated
    sIO relationships without embedding a hand-written damage formula.
    """

    def __init__(self, dimensions: int = 512, pairwise_limit: int = 36) -> None:
        if dimensions < 32:
            raise ValueError("Feature dimensions must be at least 32")
        self.dimensions = dimensions
        self.pairwise_limit = pairwise_limit

    def encode(
        self,
        state: BuildState,
        calculator_payload: Mapping[str, Any],
        mode: str,
    ) -> list[float]:
        vector = [0.0] * self.dimensions
        numeric: list[tuple[str, float]] = []
        for path, value in _flatten(calculator_payload):
            if isinstance(value, bool):
                self._add(vector, f"calc:{path}={value}", 1.0)
            elif isinstance(value, (int, float)) and math.isfinite(float(value)):
                transformed = math.copysign(math.log1p(abs(float(value))), float(value))
                numeric.append((f"calc:{path}", transformed))
                self._add(vector, f"calc:{path}", transformed)
            elif value is not None:
                self._add(vector, f"calc:{path}={value}", 1.0)

        for resource, quantity in sorted(state.resources.items()):
            self._add(vector, f"resource:{resource}", math.log1p(max(0, quantity)))
        for flag in sorted(state.flags):
            self._add(vector, f"flag:{flag}", 1.0)
        for obj in state.objects.values():
            self._add(vector, f"system:{obj.system}", 1.0)
            for tag in obj.tags:
                self._add(vector, f"object_tag:{tag}", 1.0)
            for path, value in _flatten(obj.state):
                if isinstance(value, bool):
                    self._add(vector, f"obj:{obj.system}:{path}={value}", 1.0)
                elif isinstance(value, (int, float)) and math.isfinite(float(value)):
                    self._add(
                        vector,
                        f"obj:{obj.system}:{path}",
                        math.copysign(math.log1p(abs(float(value))), float(value)),
                    )
                elif value is not None:
                    self._add(vector, f"obj:{obj.system}:{path}={value}", 1.0)
        self._add(vector, f"mode:{mode}", 1.0)

        # Hashed pairwise interactions learn products such as chance × bonus and
        # conditional bonus × uptime without encoding a game-specific formula.
        numeric = sorted(
            numeric, key=lambda item: abs(item[1]), reverse=True
        )[: self.pairwise_limit]
        for left_index, (left_name, left_value) in enumerate(numeric):
            for right_name, right_value in numeric[left_index + 1 :]:
                self._add(
                    vector,
                    f"pair:{left_name}|{right_name}",
                    left_value * right_value,
                )
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    def _add(self, vector: list[float], key: str, value: float) -> None:
        digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
        raw = int.from_bytes(digest, "big")
        index = raw % self.dimensions
        sign = -1.0 if raw & (1 << 63) else 1.0
        vector[index] += sign * value


@dataclass
class OnlineLogSurrogate:
    dimensions: int = 512
    learning_rate: float = 0.04
    l2: float = 1e-5
    min_confident_samples: int = 40
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    samples: int = 0
    residual_ema: float = 1.0

    def __post_init__(self) -> None:
        if not self.weights:
            self.weights = [0.0] * self.dimensions
        if len(self.weights) != self.dimensions:
            raise ValueError("Surrogate weight count does not match dimensions")

    def predict(self, features: Sequence[float]) -> Prediction:
        log_value = self.bias + sum(
            weight * value
            for weight, value in zip(self.weights, features, strict=True)
        )
        uncertainty = max(0.03, self.residual_ema)
        confidence = min(0.99, self.samples / max(1, self.min_confident_samples))
        value = math.exp(max(-30.0, min(80.0, log_value)))
        lower = math.exp(max(-30.0, min(80.0, log_value - 2.0 * uncertainty)))
        upper = math.exp(max(-30.0, min(80.0, log_value + 2.0 * uncertainty)))
        return Prediction(value=value, lower=lower, upper=upper, confidence=confidence)

    def update(self, features: Sequence[float], exact_value: float) -> None:
        if exact_value <= 0:
            return
        target = math.log(exact_value)
        predicted = self.bias + sum(
            weight * value
            for weight, value in zip(self.weights, features, strict=True)
        )
        error = max(-8.0, min(8.0, target - predicted))
        rate = self.learning_rate / math.sqrt(1.0 + self.samples / 25.0)
        self.bias += rate * error
        for index, value in enumerate(features):
            if value:
                self.weights[index] += rate * (
                    error * value - self.l2 * self.weights[index]
                )
        absolute = abs(error)
        self.residual_ema = 0.92 * self.residual_ema + 0.08 * absolute
        self.samples += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "min_confident_samples": self.min_confident_samples,
            "weights": self.weights,
            "bias": self.bias,
            "samples": self.samples,
            "residual_ema": self.residual_ema,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OnlineLogSurrogate:
        return cls(
            dimensions=int(data.get("dimensions", 512)),
            learning_rate=float(data.get("learning_rate", 0.04)),
            l2=float(data.get("l2", 1e-5)),
            min_confident_samples=int(data.get("min_confident_samples", 40)),
            weights=[float(v) for v in data.get("weights", [])],
            bias=float(data.get("bias", 0.0)),
            samples=int(data.get("samples", 0)),
            residual_ema=float(data.get("residual_ema", 1.0)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), separators=(",", ":")), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> OnlineLogSurrogate:
        target = Path(path)
        if not target.exists():
            return cls()
        return cls.from_dict(json.loads(target.read_text(encoding="utf-8")))


@dataclass
class GateStats:
    count: int = 0
    mean_log_gain: float = 0.0
    positive_count: int = 0

    def observe(self, log_gain: float) -> None:
        self.count += 1
        self.mean_log_gain += (log_gain - self.mean_log_gain) / self.count
        if log_gain > 0:
            self.positive_count += 1


@dataclass
class AdaptiveGatePolicy:
    stats: dict[str, GateStats] = field(default_factory=dict)

    def observe(
        self, mode: str, tags: Sequence[str], parent_score: float, child_score: float
    ) -> None:
        if parent_score <= 0 or child_score <= 0:
            return
        log_gain = math.log(child_score / parent_score)
        for tag in set(tags) or {"untagged"}:
            key = f"{mode}:{tag}"
            self.stats.setdefault(key, GateStats()).observe(log_gain)

    def priority(self, mode: str, tags: Sequence[str]) -> float:
        values = []
        for tag in set(tags) or {"untagged"}:
            stat = self.stats.get(f"{mode}:{tag}")
            if stat is None:
                values.append(0.2)
                continue
            exploration = math.sqrt(
                math.log(2 + sum(v.count for v in self.stats.values()))
                / (1 + stat.count)
            )
            positive_rate = stat.positive_count / max(1, stat.count)
            values.append(stat.mean_log_gain + 0.15 * exploration + 0.05 * positive_rate)
        return max(values, default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: {
                "count": value.count,
                "mean_log_gain": value.mean_log_gain,
                "positive_count": value.positive_count,
            }
            for key, value in self.stats.items()
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AdaptiveGatePolicy:
        return cls(
            stats={
                str(key): GateStats(
                    count=int(value.get("count", 0)),
                    mean_log_gain=float(value.get("mean_log_gain", 0.0)),
                    positive_count=int(value.get("positive_count", 0)),
                )
                for key, value in data.items()
            }
        )


@dataclass(frozen=True)
class AdvisorDecision:
    priority_adjustment: float = 0.0
    exploration_probability: float = 0.1
    prune: bool = False
    reason: str = ""


class SafePathAdvisor:
    """Constrained AI advisory layer.

    The callback may adjust search order or prune formally bad paths. It is forbidden
    from supplying a damage value, winner, or replacement score.
    """

    FORBIDDEN_KEYS = {"damage", "score", "winner", "best", "multiplier", "dps"}

    def __init__(
        self,
        callback: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.callback = callback

    def decide(
        self,
        state: BuildState,
        operation: CandidateOperation,
        mode: str,
    ) -> AdvisorDecision:
        formal = self._formal_decision(state, operation, mode)
        if formal.prune or self.callback is None:
            return formal
        raw = dict(
            self.callback(
                {
                    "mode": mode,
                    "operation_id": operation.operation_id,
                    "kind": operation.kind,
                    "tags": list(operation.tags),
                    "resources": dict(state.resources),
                    "flags": sorted(state.flags),
                }
            )
        )
        if self.FORBIDDEN_KEYS.intersection(key.lower() for key in raw):
            raise ValueError("Path advisor attempted to provide calculator output or a winner")
        return AdvisorDecision(
            priority_adjustment=formal.priority_adjustment
            + float(raw.get("priority_adjustment", 0.0)),
            exploration_probability=max(
                0.0,
                min(
                    1.0,
                    float(
                        raw.get(
                            "exploration_probability", formal.exploration_probability
                        )
                    ),
                ),
            ),
            prune=bool(raw.get("prune", False)),
            reason=str(raw.get("reason", formal.reason)),
        )

    @staticmethod
    def _formal_decision(
        state: BuildState,
        operation: CandidateOperation,
        mode: str,
    ) -> AdvisorDecision:
        tags = set(operation.tags)
        adjustment = 0.0
        reason = ""
        # Do not hard-code that normal pets are always worse. Once Xeno is unlocked,
        # unexplained normal-pet spending is merely explored later unless it preserves a
        # gate or grants an account-wide bonus.
        if "auto:system:xeno_pet" in state.flags and "system:normal_pet" in tags:
            if not tags.intersection(
                {"xeno_unlock_gate", "account_bonus", "affection_atk"}
            ):
                adjustment -= 0.8
                reason = (
                    "Normal-pet branch after Xeno unlock lacks a stated "
                    "gate/account benefit"
                )
        if "loses_unlock" in tags:
            return AdvisorDecision(prune=True, reason="Operation loses a required unlock")
        if "one_way" in tags:
            adjustment -= 0.25
        if "refund" in tags or "reconfiguration" in tags:
            adjustment += 0.15
        return AdvisorDecision(
            priority_adjustment=adjustment,
            exploration_probability=0.12,
            reason=reason,
        )


def choose_with_exploration(
    ordered: Sequence[Any],
    count: int,
    exploration_probability: float,
    random_source: random.Random,
) -> list[Any]:
    if count >= len(ordered):
        return list(ordered)
    chosen = list(ordered[:count])
    remaining = list(ordered[count:])
    for index in range(len(chosen)):
        if remaining and random_source.random() < exploration_probability:
            swap = random_source.randrange(len(remaining))
            chosen[index], remaining[swap] = remaining[swap], chosen[index]
    return chosen


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            result.extend(_flatten(value[key], path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            path = f"{prefix}.{index}" if prefix else str(index)
            result.extend(_flatten(item, path))
    else:
        result.append((prefix, value))
    return result
