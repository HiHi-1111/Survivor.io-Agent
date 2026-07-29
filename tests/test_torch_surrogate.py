from __future__ import annotations

import importlib


def test_torch_surrogate_module_imports_without_loading_torch() -> None:
    module = importlib.import_module("survivor_optimizer.torch_surrogate")
    assert module.TorchBatchSurrogate.__name__ == "TorchBatchSurrogate"


def test_training_scripts_are_import_safe() -> None:
    importlib.import_module("scripts.check_training_hardware")
    importlib.import_module("scripts.train_optimizer")
