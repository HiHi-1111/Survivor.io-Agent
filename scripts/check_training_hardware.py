from __future__ import annotations

import json
import os
import platform


def main() -> None:
    report: dict[str, object] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpu_threads": os.cpu_count(),
    }
    try:
        import torch
    except ImportError:
        report.update(
            {
                "torch_installed": False,
                "cuda_available": False,
                "next_step": "Install a CUDA-enabled PyTorch build, then run this probe again.",
            }
        )
        print(json.dumps(report, indent=2))
        return

    report["torch_installed"] = True
    report["torch_version"] = torch.__version__
    report["cuda_available"] = torch.cuda.is_available()
    report["torch_cuda_version"] = torch.version.cuda
    if torch.cuda.is_available():
        device = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(device)
        report.update(
            {
                "gpu": torch.cuda.get_device_name(device),
                "compute_capability": list(torch.cuda.get_device_capability(device)),
                "vram_gib": round(properties.total_memory / 1024**3, 2),
                "mixed_precision": True,
            }
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
