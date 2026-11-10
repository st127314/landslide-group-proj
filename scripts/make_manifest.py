"""Write FILE_MANIFEST.csv: size, CSV row count and SHA-256 for every file in
data/, models/ and results/, so a reviewer can verify they hold the exact files
the documentation describes.

Run: python3 scripts/make_manifest.py
"""

import csv
import hashlib
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
ROOTS = ["data", "models", "results"]
SKIP = ("data/cache/", "data/raw/")   # resumable extraction parts and source downloads: not what the documents describe


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_rows(path):
    with path.open("rb") as handle:
        return max(sum(1 for _ in handle) - 1, 0)  # minus header


def main():
    rows = []
    for root in ROOTS:
        for path in sorted((PROJECT_DIR / root).rglob("*")):
            if path.is_file() and path.name != ".DS_Store" and not path.relative_to(PROJECT_DIR).as_posix().startswith(SKIP):
                rows.append({
                    "path": path.relative_to(PROJECT_DIR).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "csv_rows": csv_rows(path) if path.suffix == ".csv" else "",
                    "sha256": sha256(path),
                })
    out = PROJECT_DIR / "FILE_MANIFEST.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "size_bytes", "csv_rows", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} entries to {out}")


if __name__ == "__main__":
    main()
