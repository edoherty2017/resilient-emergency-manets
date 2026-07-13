from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import sim_run_manifest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/sim_run_manifest.py"


def test_manifest_binds_inputs_results_and_git_state(tmp_path: Path):
    input_path = tmp_path / "input.json"
    result_path = tmp_path / "result.json"
    out_path = tmp_path / "manifest.json"
    input_path.write_text('{"input": true}\n', encoding="utf-8")
    result_path.write_text('{"result": true}\n', encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--out",
            str(out_path),
            "--engine",
            "python",
            "--mode",
            "etx",
            "--days",
            "1",
            "--seed",
            "42",
            "--input",
            f"topology={input_path}",
            "--result",
            str(result_path),
            "--arg",
            "renters_per_route=2",
            "--command",
            "python scripts/mesh_sim.py --mode etx",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert json.loads(proc.stdout)["ok"] is True
    assert report["schema_version"] == "1.1"
    assert report["mode"] == "etx"
    assert report["seed"] == 42
    assert report["reported_command"] == "python scripts/mesh_sim.py --mode etx"
    assert report["command_attestation"] == "self_reported_by_runner"
    assert report["resolved_args"] == {"renters_per_route": "2"}
    assert report["inputs"]["topology"]["sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert report["results"][0]["sha256"] == hashlib.sha256(result_path.read_bytes()).hexdigest()
    assert isinstance(report["git"]["dirty"], bool)
    assert report["git"]["available"] is True
    assert len(report["git"]["worktree_fingerprint_sha256"]) == 64
    assert isinstance(report["git"]["untracked_files"], list)
    runtime = report["environment"]["engine_runtime"]
    assert runtime["kind"] == "cpython"
    assert runtime["dependency_files"]["requirements"]["path"] == "requirements.txt"
    assert runtime["dependency_files"]["lock"]["path"] == "requirements.lock"
    assert runtime["locked_packages"]["simpy"] == "4.1.2"


def test_fastsim_runtime_binds_toolchain_and_cargo_inputs(monkeypatch):
    monkeypatch.setattr(
        sim_run_manifest,
        "command_output",
        lambda *command: " ".join(command) + " fixture",
    )

    runtime = sim_run_manifest.engine_runtime("fastsim")

    assert runtime["kind"] == "rust"
    assert runtime["rustc"].startswith("rustc --version --verbose")
    assert runtime["cargo"].startswith("cargo --version")
    assert runtime["project_files"]["toolchain"]["path"] == (
        "fastsim/rust-toolchain.toml"
    )
    assert runtime["project_files"]["lock"]["path"] == "fastsim/Cargo.lock"


def test_manifest_rejects_missing_result(tmp_path: Path):
    input_path = tmp_path / "input.json"
    input_path.write_text("{}", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--out",
            str(tmp_path / "manifest.json"),
            "--engine",
            "python",
            "--mode",
            "etx",
            "--days",
            "1",
            "--seed",
            "1",
            "--input",
            f"topology={input_path}",
            "--result",
            str(tmp_path / "missing.json"),
            "--command",
            "test",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "required provenance file not found" in proc.stderr


def test_require_clean_rejects_dirty_worktree(tmp_path: Path, monkeypatch):
    input_path = tmp_path / "input.json"
    result_path = tmp_path / "result.json"
    input_path.write_text("{}", encoding="utf-8")
    result_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sim_run_manifest,
        "git_record",
        lambda: {"dirty": True, "status": [" M scripts/mesh_sim.py"]},
    )
    with pytest.raises(SystemExit, match="refused a dirty"):
        sim_run_manifest.main(
            [
                "--out",
                str(tmp_path / "manifest.json"),
                "--engine",
                "python",
                "--mode",
                "etx",
                "--days",
                "1",
                "--seed",
                "1",
                "--input",
                f"topology={input_path}",
                "--result",
                str(result_path),
                "--command",
                "test",
                "--require-clean",
            ]
        )
