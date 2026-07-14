use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn project_path(relative: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("fastsim must live under the project root")
        .join(relative)
}

fn fastsim_command(output: &Path, days: &str) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_fastsim"));
    command.args([
        "--topology",
        project_path("artifacts/sim/topology.json")
            .to_str()
            .expect("UTF-8 topology path"),
        "--routes",
        project_path("artifacts/sim/routes.json")
            .to_str()
            .expect("UTF-8 routes path"),
        "--weather",
        project_path("artifacts/sim/weather_year.json")
            .to_str()
            .expect("UTF-8 weather path"),
        "--config",
        project_path("config/sim/wmnf_sim.yaml")
            .to_str()
            .expect("UTF-8 config path"),
        "--mode",
        "min_hop",
        "--days",
        days,
        "--seed",
        "1729",
        "--renters-per-route",
        "2",
        "--out",
        output.to_str().expect("UTF-8 output path"),
    ]);
    command
}

#[test]
fn same_seed_is_identical_across_processes() {
    let temp_root = std::env::temp_dir();
    let mut reference: Option<Vec<u8>> = None;

    for run in 0..6 {
        let output = temp_root.join(format!("fastsim-repro-{}-{run}.json", std::process::id()));
        let status = fastsim_command(&output, "0.1")
            .status()
            .expect("run FastSim child process");
        assert!(status.success(), "FastSim child process failed");

        let bytes = fs::read(&output).expect("read FastSim summary");
        let summary: Value = serde_json::from_slice(&bytes).expect("parse FastSim summary");
        assert_eq!(summary["start_date"], "2025-07-01");
        fs::remove_file(&output).expect("remove temporary FastSim summary");

        if let Some(expected) = &reference {
            assert_eq!(
                &bytes, expected,
                "same inputs and seed changed byte-for-byte across FastSim processes"
            );
        } else {
            reference = Some(bytes);
        }
    }
}

#[test]
fn invalid_cli_and_timing_inputs_fail_closed() {
    let cases: &[(&str, &[&str])] = &[
        ("unknown option", &["--not-a-real-option", "value"]),
        ("zero event interval", &["--energy-step-s", "0"]),
        ("malformed outage", &["--outage", "ammo_relay:not-a-day:1"]),
        ("overflow kiosk spares", &["--kiosk-spares", "4294967295"]),
        ("excessive renters", &["--renters-per-route", "4294967295"]),
    ];
    for (label, extra) in cases {
        let output = std::env::temp_dir().join(format!(
            "fastsim-invalid-{}-{}.json",
            std::process::id(),
            label.replace(' ', "-")
        ));
        let result = fastsim_command(&output, "0.1")
            .args(*extra)
            .output()
            .expect("run invalid FastSim command");
        assert!(!result.status.success(), "{label} was accepted");
        assert!(!output.exists(), "{label} wrote a summary despite failure");
        assert!(
            String::from_utf8_lossy(&result.stderr).contains("fastsim: error:"),
            "{label} did not produce a clear error"
        );
    }

    let output =
        std::env::temp_dir().join(format!("fastsim-invalid-days-{}.json", std::process::id()));
    let result = fastsim_command(&output, "0")
        .output()
        .expect("run zero-day FastSim command");
    assert!(!result.status.success());
    assert!(!output.exists());
}

#[test]
fn overlapping_outages_are_merged_as_a_union() {
    let output =
        std::env::temp_dir().join(format!("fastsim-outage-union-{}.json", std::process::id()));
    let status = fastsim_command(&output, "1")
        .args(["--outage", "ammo_relay:0:0.75,ammo_relay:0.25:1"])
        .status()
        .expect("run overlapping-outage FastSim command");
    assert!(status.success());
    let summary: Value = serde_json::from_slice(&fs::read(&output).expect("read outage summary"))
        .expect("parse outage summary");
    fs::remove_file(&output).expect("remove outage summary");
    assert_eq!(summary["per_node"]["ammo_relay"]["dead_time_s"], 86_400.0);
    assert_eq!(summary["per_node"]["ammo_relay"]["availability"], 0.0);
}
