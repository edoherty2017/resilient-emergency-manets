#!/usr/bin/env python3
"""Compile the corrected Trial 1 TeX and bind the PDF to its source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tex",
        default="artifacts/coverage_prediction/trial1_report.tex",
    )
    parser.add_argument(
        "--manifest",
        default="artifacts/coverage_prediction/trial1_report_manifest.json",
    )
    args = parser.parse_args(argv)
    tex_path = ROOT / args.tex
    pdf_path = tex_path.with_suffix(".pdf")
    version = subprocess.run(
        ["tectonic", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["tectonic", tex_path.name], cwd=tex_path.parent, check=True)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"tectonic did not create {pdf_path}")

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_status": "CORRECTED_SOURCE_BUILD_NOT_FIELD_VALIDATION",
        "compiler": version,
        "generator": file_record(Path(__file__)),
        "source": file_record(tex_path),
        "output": file_record(pdf_path),
    }
    manifest_path = ROOT / args.manifest
    temporary = manifest_path.with_name(f".{manifest_path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(temporary, manifest_path)
    print(json.dumps({"pdf": manifest["output"], "manifest": args.manifest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
