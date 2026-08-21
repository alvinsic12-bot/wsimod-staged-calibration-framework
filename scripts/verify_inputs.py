"""Verify that all packaged inputs match data_manifest.csv."""
from __future__ import annotations
import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "wsimod-staged-calibration-framework_inputs"

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

with (INPUTS / "data_manifest.csv").open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
failures = []
for row in rows:
    path = INPUTS / row["portable_path"]
    if not path.is_file() or path.stat().st_size != int(row["bytes"]) or sha256(path) != row["sha256"]:
        failures.append(row["portable_path"])
if failures:
    raise SystemExit("Input verification failed:\n" + "\n".join(failures))
print(f"Verified {len(rows)} input files.")
