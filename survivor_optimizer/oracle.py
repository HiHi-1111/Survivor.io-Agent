from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


class DamageOracle(Protocol):
    def score(self, calculator_payload: Mapping[str, Any]) -> float: ...

    def score_many(self, calculator_payloads: Sequence[Mapping[str, Any]]) -> list[float]: ...


@dataclass
class CachedOracle:
    inner: DamageOracle
    cache: dict[str, float] = field(default_factory=dict)
    calls: int = 0
    cache_hits: int = 0

    def score(self, calculator_payload: Mapping[str, Any]) -> float:
        return self.score_many([calculator_payload])[0]

    def score_many(self, calculator_payloads: Sequence[Mapping[str, Any]]) -> list[float]:
        results: list[float | None] = [None] * len(calculator_payloads)
        missing_payloads: list[Mapping[str, Any]] = []
        missing_indices: list[int] = []
        missing_keys: list[str] = []
        for index, payload in enumerate(calculator_payloads):
            key = payload_hash(payload)
            if key in self.cache:
                self.cache_hits += 1
                results[index] = self.cache[key]
            else:
                missing_indices.append(index)
                missing_keys.append(key)
                missing_payloads.append(payload)
        if missing_payloads:
            values = self.inner.score_many(missing_payloads)
            if len(values) != len(missing_payloads):
                raise RuntimeError("Damage oracle returned the wrong number of results")
            self.calls += len(values)
            for index, key, value in zip(missing_indices, missing_keys, values, strict=True):
                numeric = float(value)
                if numeric < 0:
                    raise ValueError("Damage oracle returned a negative value")
                self.cache[key] = numeric
                results[index] = numeric
        return [float(value) for value in results if value is not None]


class SIOBundleOracle:
    """Calls the calculator module from a user-supplied sIO Tools web bundle.

    The JavaScript source is not copied into this repository. The runner loads module
    67727 from the local snapshot at runtime and calls its exported calculator function.
    """

    def __init__(
        self,
        bundle_dir: str | Path | None = None,
        *,
        node_binary: str = "node",
        runner_path: str | Path | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        configured = bundle_dir or os.getenv("SIO_BUNDLE_DIR")
        if not configured:
            raise ValueError("Set SIO_BUNDLE_DIR or pass bundle_dir")
        self.bundle_dir = Path(configured).expanduser().resolve()
        self.node_binary = node_binary
        self.runner_path = Path(runner_path or Path(__file__).with_name("sio_calculator_runner.js"))
        self.timeout_seconds = timeout_seconds
        if not self.bundle_dir.exists():
            raise FileNotFoundError(f"sIO bundle directory not found: {self.bundle_dir}")
        if not self.runner_path.exists():
            raise FileNotFoundError(f"sIO runner not found: {self.runner_path}")
        if shutil.which(self.node_binary) is None:
            raise RuntimeError(f"Node.js binary not found: {self.node_binary}")

    def score(self, calculator_payload: Mapping[str, Any]) -> float:
        return self.score_many([calculator_payload])[0]

    def score_many(self, calculator_payloads: Sequence[Mapping[str, Any]]) -> list[float]:
        request = {
            "bundle_dir": str(self.bundle_dir),
            "payloads": [dict(payload) for payload in calculator_payloads],
        }
        completed = subprocess.run(
            [self.node_binary, str(self.runner_path)],
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"sIO calculator runner failed: {detail}")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("sIO calculator runner returned invalid JSON") from exc
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error", "Unknown sIO calculator error")))
        values = response.get("scores")
        if not isinstance(values, list):
            raise RuntimeError("sIO calculator response did not contain a score list")
        return [float(value) for value in values]

    def bundle_fingerprint(self) -> str:
        chunk_root = _find_chunk_root(self.bundle_dir)
        digest = hashlib.sha256()
        for path in sorted(chunk_root.rglob("*.js")):
            relative = path.relative_to(chunk_root).as_posix().encode("utf-8")
            digest.update(relative)
            digest.update(path.read_bytes())
        return digest.hexdigest()


def payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _find_chunk_root(bundle_dir: Path) -> Path:
    direct = bundle_dir / "_next" / "static" / "chunks"
    if direct.exists():
        return direct
    nested = bundle_dir / "sio-tools.exp0.dev" / "_next" / "static" / "chunks"
    if nested.exists():
        return nested
    if bundle_dir.name == "chunks":
        return bundle_dir
    candidates = list(bundle_dir.glob("**/_next/static/chunks"))
    if not candidates:
        raise FileNotFoundError(f"Could not find _next/static/chunks under {bundle_dir}")
    return candidates[0]
