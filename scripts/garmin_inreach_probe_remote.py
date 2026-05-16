#!/usr/bin/env python3
import argparse
import json
import subprocess
from datetime import datetime, timezone


def run_ssh(host: str, remote_cmd: str, timeout: int = 60):
    p = subprocess.run(["ssh", host, remote_cmd], capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def probe_host(host: str):
    remote = r'''python3 - <<'PY'
import glob, json, re, subprocess
usb=subprocess.getoutput('lsusb').splitlines()
ports=sorted(glob.glob('/dev/ttyUSB*')+glob.glob('/dev/ttyACM*'))
garmin=[l for l in usb if re.search(r'garmin|inreach', l, re.I)]
out={'ports':ports,'garmin_usb_matches':garmin,'usb_lines':usb[:30]}
if ports:
    p=ports[0]
    sniff=subprocess.getoutput(f"bash -lc 'timeout 6s stdbuf -o0 cat {p} | head -n 5'")
    out['serial_sniff_sample']=sniff.splitlines()[:5]
    out['nmea_like_lines']=[ln for ln in out['serial_sniff_sample'] if ln.startswith('$')]
print(json.dumps(out))
PY'''
    code, so, se = run_ssh(host, remote)
    data = None
    if so:
        try:
            data = json.loads(so)
        except Exception:
            data = {"raw": so}
    return {"host": host, "exit": code, "stderr": se, "data": data}


def main():
    ap = argparse.ArgumentParser(description="Probe remote Pis for Garmin inReach USB visibility and serial output")
    ap.add_argument("--hosts", nargs="+", default=["meshhikernode1", "meshradiohead"])
    args = ap.parse_args()

    results = [probe_host(h) for h in args.hosts]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
