from __future__ import annotations

import argparse
import json
from pathlib import Path

from survivor_optimizer.catalog import ActionCatalog


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile deterministic unlock metadata from normalized Survivor.io CSVs."
    )
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--output", default="data/compiled_unlock_logic.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    catalog = ActionCatalog.discover_repository_data(root)
    payload = {
        "collection_sets": [
            {
                "set_id": item.set_id,
                "set_name": item.set_name,
                "members": list(item.members),
                "exact_members": item.exact_members,
            }
            for item in catalog.collection_sets
        ],
        "normal_pet_type_by_name": catalog.normal_pet_type_by_name,
        "actions": [],
        "derived_rules": [],
    }
    target = root / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(target)


if __name__ == "__main__":
    main()
