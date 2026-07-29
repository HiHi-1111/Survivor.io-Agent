from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .learning import Prediction


class TorchUnavailableError(RuntimeError):
    pass


def _torch():
    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise TorchUnavailableError(
            "PyTorch is required for GPU training. Install a CUDA-enabled PyTorch build."
        ) from exc
    return torch, nn


@dataclass
class TorchBatchSurrogate:
    dimensions: int = 512
    hidden_dimensions: tuple[int, int] = (512, 256)
    learning_rate: float = 1e-3
    weight_decay: float = 1e-5
    min_confident_samples: int = 200
    batch_size: int = 1024
    device: str = "auto"
    compile_model: bool = False
    samples: int = 0
    residual_ema: float = 1.0
    _pending_features: list[list[float]] = field(default_factory=list, repr=False)
    _pending_targets: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        torch, nn = _torch()
        if self.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise TorchUnavailableError("CUDA was requested but torch.cuda.is_available() is false")
        self._torch_module = torch
        self._model = nn.Sequential(
            nn.Linear(self.dimensions, self.hidden_dimensions[0]),
            nn.SiLU(),
            nn.Linear(self.hidden_dimensions[0], self.hidden_dimensions[1]),
            nn.SiLU(),
            nn.Linear(self.hidden_dimensions[1], 1),
        ).to(self.device)
        if self.compile_model and hasattr(torch, "compile"):
            self._model = torch.compile(self._model)
        self._optimizer = torch.optim.AdamW(
            self._model.parameters(),
            lr=self.learning_rate,
            weight_decay=self.weight_decay,
        )

    @property
    def device_name(self) -> str:
        torch = self._torch_module
        if self.device.startswith("cuda"):
            return torch.cuda.get_device_name(torch.cuda.current_device())
        return "CPU"

    def predict(self, features: Sequence[float]) -> Prediction:
        torch = self._torch_module
        self._model.eval()
        with torch.inference_mode():
            tensor = torch.tensor(features, dtype=torch.float32, device=self.device).unsqueeze(0)
            log_value = float(self._model(tensor).squeeze().clamp(-30.0, 80.0).item())
        uncertainty = max(0.03, self.residual_ema)
        confidence = min(0.99, self.samples / max(1, self.min_confident_samples))
        return Prediction(
            value=math.exp(log_value),
            lower=math.exp(max(-30.0, log_value - 2.0 * uncertainty)),
            upper=math.exp(min(80.0, log_value + 2.0 * uncertainty)),
            confidence=confidence,
        )

    def update(self, features: Sequence[float], exact_value: float) -> None:
        if exact_value <= 0:
            return
        self._pending_features.append([float(value) for value in features])
        self._pending_targets.append(math.log(float(exact_value)))

    def train_pending(self, epochs: int = 3, *, shuffle: bool = True) -> dict[str, float]:
        if not self._pending_targets:
            return {"examples": 0.0, "loss": 0.0}
        torch = self._torch_module
        features = torch.tensor(self._pending_features, dtype=torch.float32)
        targets = torch.tensor(self._pending_targets, dtype=torch.float32).unsqueeze(1)
        dataset = torch.utils.data.TensorDataset(features, targets)
        loader = torch.utils.data.DataLoader(
            dataset,
            batch_size=min(self.batch_size, len(dataset)),
            shuffle=shuffle,
            pin_memory=self.device.startswith("cuda"),
        )
        self._model.train()
        total_loss = 0.0
        steps = 0
        amp_enabled = self.device.startswith("cuda")
        for _ in range(max(1, epochs)):
            for batch_features, batch_targets in loader:
                batch_features = batch_features.to(self.device, non_blocking=True)
                batch_targets = batch_targets.to(self.device, non_blocking=True)
                self._optimizer.zero_grad(set_to_none=True)
                with torch.autocast(
                    device_type="cuda" if amp_enabled else "cpu",
                    dtype=torch.float16 if amp_enabled else torch.bfloat16,
                    enabled=amp_enabled,
                ):
                    predicted = self._model(batch_features)
                    loss = torch.nn.functional.smooth_l1_loss(predicted, batch_targets)
                loss.backward()
                self._optimizer.step()
                total_loss += float(loss.detach().item())
                steps += 1
        with torch.inference_mode():
            predicted = self._model(features.to(self.device)).cpu().squeeze(1)
            residual = float((predicted - targets.squeeze(1)).abs().mean().item())
        self.residual_ema = 0.9 * self.residual_ema + 0.1 * residual
        examples = len(self._pending_targets)
        self.samples += examples
        self._pending_features.clear()
        self._pending_targets.clear()
        return {"examples": float(examples), "loss": total_loss / max(1, steps)}

    def save(self, path: str | Path) -> None:
        torch = self._torch_module
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        model = self._model._orig_mod if hasattr(self._model, "_orig_mod") else self._model
        torch.save(
            {
                "config": {
                    "dimensions": self.dimensions,
                    "hidden_dimensions": list(self.hidden_dimensions),
                    "learning_rate": self.learning_rate,
                    "weight_decay": self.weight_decay,
                    "min_confident_samples": self.min_confident_samples,
                    "batch_size": self.batch_size,
                },
                "model_state": model.state_dict(),
                "optimizer_state": self._optimizer.state_dict(),
                "samples": self.samples,
                "residual_ema": self.residual_ema,
            },
            target,
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        device: str = "auto",
        compile_model: bool = False,
    ) -> TorchBatchSurrogate:
        torch, _ = _torch()
        checkpoint = torch.load(Path(path), map_location="cpu", weights_only=False)
        config: Mapping[str, Any] = checkpoint["config"]
        model = cls(
            dimensions=int(config["dimensions"]),
            hidden_dimensions=tuple(int(v) for v in config["hidden_dimensions"]),
            learning_rate=float(config["learning_rate"]),
            weight_decay=float(config["weight_decay"]),
            min_confident_samples=int(config["min_confident_samples"]),
            batch_size=int(config["batch_size"]),
            device=device,
            compile_model=compile_model,
            samples=int(checkpoint.get("samples", 0)),
            residual_ema=float(checkpoint.get("residual_ema", 1.0)),
        )
        raw_model = model._model._orig_mod if hasattr(model._model, "_orig_mod") else model._model
        raw_model.load_state_dict(checkpoint["model_state"])
        model._optimizer.load_state_dict(checkpoint["optimizer_state"])
        return model
