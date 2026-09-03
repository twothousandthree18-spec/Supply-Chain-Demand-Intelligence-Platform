"""
Supply Chain & Demand Intelligence Platform
Phase 1 - Data Acquisition

Downloads the official M5 Walmart retail forecasting dataset from Kaggle into
data/raw/ and records a provenance manifest (checksums, sizes, source).

The M5 competition is authentication-gated. Credentials are required BEFORE
running this script. Two supported, safe methods (never commit credentials):

  1) kaggle.json placed in the Kaggle config directory, e.g.
     %USERPROFILE%/.kaggle/kaggle.json
       { "username": "<your-username>", "key": "<your-api-token>" }
  2) Environment variables:
       setx KAGGLE_USERNAME "<your-username>"
       setx KAGGLE_KEY "<your-api-token>"

Raw files are preserved unchanged. Data is NOT cleaned or modified here.

Usage:
  .venv\\Scripts\\python scripts\\acquire_m5.py
"""

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

COMPETITION = "m5-forecasting-accuracy"

# Files expected to be inside the competition download
# (verified via `kaggle competitions files m5-forecasting-accuracy`;
#  the official distribution contains no data_readme.txt)
EXPECTED_FILES = [
    "calendar.csv",
    "sell_prices.csv",
    "sales_train_evaluation.csv",
    "sales_train_validation.csv",
    "sample_submission.csv",
]

# Only these are essential/relevant to the project.
# sample_submission is downloaded for completeness but is not loaded into the
# warehouse (it only defines the forecast horizon structure). It is retained
# under data/external to document the official horizon.
RELEVANT_CORE = ["calendar.csv", "sell_prices.csv",
                 "sales_train_validation.csv", "sales_train_evaluation.csv"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_credentials():
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    env_user = os.environ.get("KAGGLE_USERNAME")
    env_key = os.environ.get("KAGGLE_KEY")
    if not (kaggle_json.exists() or (env_user and env_key)):
        print(
            "ERROR: Kaggle credentials not found.\n"
            "  Place kaggle.json at %USERPROFILE%\\.kaggle\\kaggle.json\n"
            "  OR set environment variables KAGGLE_USERNAME and KAGGLE_KEY.\n"
            "  See https://github.com/Kaggle/kaggle-api for setup.\n"
            "  Credentials are read at runtime only and never committed."
        )
        sys.exit(2)


def find_existing_zip(raw_dir, tmp_dir):
    """Return a usable zip path already on disk, else None.

    Checks the data/raw location first (a manually downloaded zip may have
    been placed there), then the script's download temp dir.
    """
    candidates = [
        raw_dir / f"{COMPETITION}.zip",
        tmp_dir / f"{COMPETITION}.zip",
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            try:
                with zipfile.ZipFile(c) as z:
                    if z.testzip() is None:
                        return c
            except zipfile.BadZipFile:
                print(f"WARNING: ignoring invalid zip {c}")
    return None


def main():
    repo_root = Path(__file__).resolve().parents[1]
    raw_dir = repo_root / "data" / "raw"
    ext_dir = repo_root / "data" / "external"
    tmp_dir = repo_root / "data" / "external" / "_download"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ext_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Reuse an already-downloaded zip if present (avoid a second download).
    zip_path = find_existing_zip(raw_dir, tmp_dir)
    if zip_path is not None:
        print(f"== Reusing existing zip: {zip_path} "
              f"({zip_path.stat().st_size:,} bytes) ==")
    else:
        ensure_credentials()
        zip_path = tmp_dir / f"{COMPETITION}.zip"
        print(f"== Downloading Kaggle competition: {COMPETITION} ==")
        kaggle_bin = str(repo_root / ".venv" / "Scripts" / "kaggle.exe")
        res = subprocess.run(
            [kaggle_bin, "competitions", "download", "-c", COMPETITION,
             "-p", str(tmp_dir)],
            capture_output=True, text=True,
        )
        print(res.stdout)
        if res.returncode != 0:
            print("Kaggle download failed:", res.stderr)
            sys.exit(1)

    print("== Extracting to data/raw ==")
    # Only extract files that are not already present (idempotent).
    with zipfile.ZipFile(zip_path) as z:
        to_extract = [
            i for i in z.infolist()
            if not (raw_dir / i.filename).exists()
        ]
        missing_core = [i.filename for i in to_extract
                        if i.filename in RELEVANT_CORE]
        if missing_core:
            for info in to_extract:
                z.extract(info, raw_dir)
        else:
            print("  Core files already present; nothing to extract.")

    manifest_entries = []
    for name in EXPECTED_FILES:
        p = raw_dir / name
        if p.exists():
            manifest_entries.append({
                "filename": name,
                "size_bytes": p.stat().st_size,
                "sha256": sha256(p),
                "location": "data/raw",
            })

    manifest = {
        "source": "Kaggle competition: m5-forecasting-accuracy",
        "url": "https://www.kaggle.com/competitions/m5-forecasting-accuracy",
        "download_date": str(__import__("datetime").datetime.date(
            __import__("datetime").datetime.now())),
        "files": manifest_entries,
        "notes": (
            "Raw files preserved unchanged. Provenance only; no cleaning here. "
            "sample_submission is retained for horizon documentation."
        ),
    }

    manifest_path = raw_dir / "MANIFEST.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written: {manifest_path}")

    # Clean up the zip (it is a duplicate copy of the extracted files).
    # If it was a manually-placed raw/ zip, move it under external/_download as
    # the retained archive reference rather than deleting user content.
    if zip_path.parent == raw_dir and (raw_dir / zip_path.name).exists():
        archive_dest = tmp_dir / zip_path.name
        zip_path.rename(archive_dest)
        print(f"Archive moved to {archive_dest} (retained; ignored by git).")
    else:
        zip_path.unlink(missing_ok=True)

    print("\n== Acquired files ==")
    for e in manifest_entries:
        print(f"  {e['filename']:<32} {e['size_bytes']:>12,} bytes")
    print("\nDone. Next: run scripts/python/profile_m5.py and "
          "scripts/python/validate_m5.py")


if __name__ == "__main__":
    main()
