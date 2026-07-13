#!/usr/bin/env python3
"""Write a self-contained provenance manifest for a simulation result.

The simulators intentionally keep bulky traces out of Git.  This manifest
binds a compact result to its inputs and code-tree state.  Missing inputs or
results are hard failures.  Dirty-tree runs include hashes of tracked diffs
and untracked files; decision-grade runners should also use ``--require-clean``.

Example::

    .venv/bin/python scripts/sim_run_manifest.py \
      --out artifacts/sim/run_manifest_etx.json \
      --engine python --mode etx --days 365 --seed 42 \
      --input topology=artifacts/sim/topology_statewide.json \
      --input routes=artifacts/sim/routes_statewide.json \
      --input weather=artifacts/sim/weather_year.json \
      --input config=config/sim/wmnf_sim.yaml \
      --result artifacts/sim/kiosk_summary_etx.json \
      --command '.venv/bin/python scripts/mesh_sim.py ...'
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1.1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def file_entry(raw_path: str) -> dict[str, Any]:
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"required provenance file not found: {path}")
    stat_before = path.stat()
    digest = sha256_file(path)
    stat_after = path.stat()
    stable_fields_before = (
        stat_before.st_size,
        stat_before.st_mtime_ns,
        getattr(stat_before, "st_ino", None),
    )
    stable_fields_after = (
        stat_after.st_size,
        stat_after.st_mtime_ns,
        getattr(stat_after, "st_ino", None),
    )
    if stable_fields_before != stable_fields_after:
        raise RuntimeError(f"provenance file changed while hashing: {path}")
    return {
        "path": display_path(path),
        "bytes": stat_after.st_size,
        "sha256": digest,
    }


def parse_assignment(value: str, option: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"{option} must be KEY=VALUE, got {value!r}")
    key, item = value.split("=", 1)
    if not key.strip() or not item:
        raise ValueError(f"{option} must contain a non-empty key and value")
    return key.strip(), item


def git_record() -> dict[str, Any]:
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout

    try:
        commit = run("rev-parse", "HEAD").strip()
        branch = run("rev-parse", "--abbrev-ref", "HEAD").strip()
        status_lines = [
            line for line in run("status", "--porcelain=v1", "--untracked-files=all").splitlines()
            if line
        ]
        tracked_diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        untracked_output = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        untracked_files = []
        fingerprint = hashlib.sha256()
        fingerprint.update(b"tracked-diff\0")
        fingerprint.update(tracked_diff)
        for raw_name in sorted(name for name in untracked_output.split(b"\0") if name):
            relative_name = raw_name.decode("utf-8", errors="surrogateescape")
            path = ROOT / relative_name
            if path.is_file():
                digest = sha256_file(path)
                size = path.stat().st_size
                untracked_files.append(
                    {"path": relative_name, "bytes": size, "sha256": digest}
                )
                fingerprint.update(b"untracked\0")
                fingerprint.update(raw_name)
                fingerprint.update(b"\0")
                fingerprint.update(digest.encode("ascii"))
                fingerprint.update(b"\0")
        return {
            "available": True,
            "commit": commit,
            "branch": branch,
            "dirty": bool(status_lines),
            "status": status_lines,
            "tracked_diff_sha256": hashlib.sha256(tracked_diff).hexdigest(),
            "untracked_files": untracked_files,
            "worktree_fingerprint_sha256": fingerprint.hexdigest(),
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"available": False, "error": str(exc)}


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Manifest JSON path")
    parser.add_argument("--engine", required=True, choices=["python", "fastsim"])
    parser.add_argument("--mode", required=True)
    parser.add_argument("--days", required=True, type=float)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Required input and logical name; repeat for every input",
    )
    parser.add_argument(
        "--result",
        action="append",
        default=[],
        metavar="PATH",
        help="Result file to bind to this run; repeat as needed",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Additional resolved run parameter",
    )
    parser.add_argument(
        "--command",
        required=True,
        help="Runner-reported command (recorded as supplied; not independently attested)",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="refuse to write a manifest if the Git worktree is dirty",
    )
    return parser


def installed_versions(names: tuple[str, ...]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def locked_package_names(path: Path) -> tuple[str, ...]:
    names = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        names.append(line.split("==", 1)[0])
    return tuple(names)


def command_output(*command: str) -> str:
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"cannot attest {' '.join(command)!r} for the selected engine: {exc}"
        ) from exc
    return proc.stdout.strip()


def engine_runtime(engine: str) -> dict[str, Any]:
    """Bind the selected engine to its runtime and dependency declarations."""

    if engine == "python":
        lock_path = ROOT / "requirements.lock"
        return {
            "kind": "cpython",
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
            "version": sys.version,
            "dependency_files": {
                "requirements": file_entry("requirements.txt"),
                "lock": file_entry("requirements.lock"),
            },
            "locked_packages": installed_versions(locked_package_names(lock_path)),
        }
    if engine == "fastsim":
        return {
            "kind": "rust",
            "rustc": command_output("rustc", "--version", "--verbose"),
            "cargo": command_output("cargo", "--version"),
            "project_files": {
                "toolchain": file_entry("fastsim/rust-toolchain.toml"),
                "manifest": file_entry("fastsim/Cargo.toml"),
                "lock": file_entry("fastsim/Cargo.lock"),
            },
        }
    raise ValueError(f"unsupported engine: {engine}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input:
        raise SystemExit("at least one --input NAME=PATH is required")
    if not args.result:
        raise SystemExit("at least one --result PATH is required")

    inputs: dict[str, dict[str, Any]] = {}
    for assignment in args.input:
        name, raw_path = parse_assignment(assignment, "--input")
        if name in inputs:
            raise SystemExit(f"duplicate --input name: {name}")
        inputs[name] = file_entry(raw_path)

    resolved_args: dict[str, str] = {}
    for assignment in args.arg:
        name, value = parse_assignment(assignment, "--arg")
        if name in resolved_args:
            raise SystemExit(f"duplicate --arg name: {name}")
        resolved_args[name] = value

    git = git_record()
    if args.require_clean and git.get("dirty", True):
        raise SystemExit("--require-clean refused a dirty or unavailable Git worktree")

    now = datetime.now(timezone.utc)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": now.strftime("%Y%m%dT%H%M%S.%fZ"),
        "generated_at_utc": now.isoformat(),
        "engine": args.engine,
        "mode": args.mode,
        "days": args.days,
        "seed": args.seed,
        "reported_command": args.command,
        "command_attestation": "self_reported_by_runner",
        "resolved_args": resolved_args,
        "git": git,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": installed_versions(("numpy", "simpy", "PyYAML")),
            "engine_runtime": engine_runtime(args.engine),
        },
        "inputs": inputs,
        "results": [file_entry(path) for path in args.result],
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    atomic_write_json(out, manifest)
    print(json.dumps({"ok": True, "manifest": display_path(out), "run_id": manifest["run_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
