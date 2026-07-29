# Local CPU and GPU training

The local trainer keeps the game calculator authoritative:

- the CPU expands legal build states and runs the bundled sIO Node calculator
- the GPU trains a neural surrogate from exact sIO results
- the surrogate may order or prune candidates, but the reported winner must still receive an exact sIO score
- checkpoints, gate statistics, and episode logs are written to disk so training can resume

## 1. Install PyTorch with CUDA

Install the current NVIDIA driver, then use the official PyTorch installer for Windows and select the CUDA build that matches the offered installation command.

After installing PyTorch, verify the hardware:

```powershell
uv run python scripts/check_training_hardware.py
```

The output should include:

```json
{
  "cuda_available": true,
  "gpu": "NVIDIA GeForce RTX 4070"
}
```

The trainer checks CUDA with `torch.cuda.is_available()` and otherwise falls back to CPU.

## 2. Extract the sIO bundle

Extract the supplied sIO Tools ZIP somewhere outside Git. Pass the directory containing the extracted site to `--sio-bundle`.

The calculator bundle is fingerprinted at startup. The training checkpoint is not trusted across an unreviewed calculator-bundle change.

## 3. Prepare inputs

Create a profile JSON and an optimization-request JSON. The profile contains inventory, resources, upgrade history, protected unlocks, and mode calculator inputs. The request controls search depth and exact-calculator budget.

A practical RTX 4070 request is:

```json
{
  "mode": "ee",
  "max_depth": 7,
  "beam_width": 32,
  "oracle_budget": 500,
  "candidates_per_depth": 96,
  "final_verify_count": 12,
  "minimum_exact_per_depth": 6,
  "exploration_probability": 0.15,
  "surrogate_prune_confidence": 0.95,
  "surrogate_margin_ratio": 0.005,
  "allow_irreversible": true,
  "allow_unknown_refund_forward": true,
  "random_seed": 1
}
```

Start smaller until the profile and action catalog validate correctly.

## 4. Train

Windows PowerShell example:

```powershell
uv run python scripts/train_optimizer.py `
  --profile profiles/my_profile.json `
  --request requests/enders_echo.json `
  --sio-bundle "C:\SurvivorIO\sio-tools" `
  --episodes 500 `
  --epochs-per-episode 4 `
  --device cuda `
  --torch-threads 12 `
  --checkpoint-every 5 `
  --model training/surrogate.pt `
  --gate training/gates.json `
  --log training/runs.jsonl
```

For a Ryzen 7, start with `--torch-threads` between 8 and 14. More threads are not always faster because the sIO calculator also uses CPU time.

`--compile` enables `torch.compile`. It can improve repeated neural-network training after the initial compilation cost, but leave it off while debugging.

## 5. Resume

Run the same command again. If `training/surrogate.pt` and `training/gates.json` exist, training resumes from them.

The JSONL log records each episode's:

- exact sIO calls
- cache hits
- states explored and pruned
- model examples and loss
- residual error estimate
- best exact score and action path

## Safe operating rules

- Never report a surrogate-only candidate as the winner.
- Keep minimum exact samples and periodic exploration enabled.
- Do not train from AI-written damage labels.
- Do not infer sIO input mutations from prose.
- Revalidate the action catalog after game updates.
- Back up the profile, ledger, model, gate file, and run log together.

## CPU-only fallback

```powershell
uv run python scripts/train_optimizer.py ... --device cpu --torch-threads 12
```

This is slower for surrogate training, but exact sIO scoring and legal-state search still work.
