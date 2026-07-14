"""Tests for the Trial 2 preregistration freezer.

These run the real freezer over the real declared inputs and assert that the
manifest binds every one with a nonempty, correct SHA-256 and a positive byte
count. They also pin the immutability guard and the UTC-stamp validation, which
are the properties that give the freeze its evidential meaning.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "freeze_trial2_prereg", ROOT / "scripts" / "freeze_trial2_prereg.py"
)
freeze = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(freeze)

STAMP = "2026-07-13T18:30:00+00:00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_binds_every_declared_input_with_nonempty_hash() -> None:
    manifest = freeze.build_manifest(STAMP, ROOT)

    # Every declared input is present in the manifest.
    assert set(manifest["inputs"]) == set(freeze.DECLARED_INPUTS)
    assert manifest["input_count"] == len(freeze.DECLARED_INPUTS)

    for role, (rel_path, _desc) in freeze.DECLARED_INPUTS.items():
        entry = manifest["inputs"][role]
        assert entry["path"] == rel_path
        # Nonempty hash that actually matches the on-disk bytes.
        assert entry["sha256"], role
        assert entry["sha256"] == _sha256(ROOT / rel_path), role
        # Positive byte count matching the real file.
        assert entry["bytes"] == (ROOT / rel_path).stat().st_size > 0, role


def test_manifest_records_stamp_git_and_schema() -> None:
    manifest = freeze.build_manifest(STAMP, ROOT)
    assert manifest["schema_version"] == freeze.SCHEMA_VERSION
    assert manifest["build_timestamp_utc"] == STAMP
    assert manifest["git_head"]  # 'unknown' outside a repo, but never empty
    assert isinstance(manifest["git_worktree_dirty"], bool)


def test_stamp_must_be_explicit_utc() -> None:
    assert freeze.parse_stamp("2026-07-13T18:30:00Z") == STAMP
    with pytest.raises(ValueError):
        freeze.parse_stamp("2026-07-13T18:30:00")  # no offset
    with pytest.raises(ValueError):
        freeze.parse_stamp("2026-07-13T18:30:00-05:00")  # not UTC
    with pytest.raises(ValueError):
        freeze.parse_stamp("not-a-timestamp")


def test_missing_input_refuses_to_freeze(tmp_path: Path) -> None:
    # A root with none of the declared inputs must fail closed, not emit a
    # partial manifest.
    with pytest.raises(FileNotFoundError):
        freeze.build_manifest(STAMP, tmp_path)


def test_cli_writes_manifest_and_is_immutable(tmp_path: Path) -> None:
    out = tmp_path / "prereg_manifest.json"
    import sys

    argv = sys.argv
    try:
        sys.argv = [
            "freeze_trial2_prereg.py",
            "--stamp",
            STAMP,
            "--out",
            str(out),
        ]
        assert freeze.main() == 0
        first = json.loads(out.read_text())
        assert first["inputs"]  # wrote a real manifest

        # Second run without --force must refuse to overwrite the frozen file.
        with pytest.raises(SystemExit):
            freeze.main()

        # --force allows a deliberate re-freeze.
        sys.argv = sys.argv + ["--force"]
        assert freeze.main() == 0
    finally:
        sys.argv = argv
