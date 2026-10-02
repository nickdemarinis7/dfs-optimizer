from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive pre-lock DFS slate inputs")
    parser.add_argument("--label", required=True)
    parser.add_argument("--file", action="append", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/slates"))
    args = parser.parse_args()
    destination = args.root / args.label
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"label": args.label, "archived_at_utc": datetime.now(timezone.utc).isoformat(), "files": []}
    for source in args.file:
        if not source.is_file():
            parser.error(f"file does not exist: {source}")
        target = destination / source.name
        shutil.copy2(source, target)
        manifest["files"].append({"name": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Archived {len(args.file)} files to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

