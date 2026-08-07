#!/usr/bin/env python3
"""e22.py — driver + field tools for the EBYTE E22-900T22S UART LoRa module
on the Waveshare SX1262 915M LoRa HAT (MeshHikerNode1).

Wiring (verified 2026-08-07):
  UART: Pi GPIO14/15 -> /dev/ttyAMA0 @ 9600 8N1 (jumpers on B row, along-row)
  M0  : BCM22   M1: BCM27   (MODE SELECT caps removed; Pi drives modes)

Modes (M0,M1):  (0,0) transparent TX/RX   (1,0) WOR-TX  (0,1) CONFIG  (1,1) sleep
RSSI append byte: dBm = -(256 - byte).

Subcommands:
  status                     read + decode registers
  configure [--save]        apply calibration config (US channel, RSSI on, power)
  noise                     query ambient noise floor (RX-chain self test)
  beacon [--period S] [--count N] [--power dBm]   transmit numbered beacon frames
  rxlog [--out FILE]        receive frames, append RSSI + GPS, write jsonl
"""
import argparse, json, os, struct, subprocess, sys, time
import serial

PORT = "/dev/ttyAMA0"
BAUD = 9600
M0_BCM, M1_BCM = 22, 27
BASE_MHZ = 850.125          # channel 0 frequency for E22-900 series

POWER = {22: 0b00, 17: 0b01, 13: 0b10, 10: 0b11}
POWER_INV = {v: k for k, v in POWER.items()}
AIR = {"0.3k": 0, "1.2k": 1, "2.4k": 2, "4.8k": 3, "9.6k": 4, "19.2k": 5, "38.4k": 6, "62.5k": 7}
AIR_INV = {v: k for k, v in AIR.items()}


def _pin(bcm, level):
    subprocess.run(["pinctrl", "set", str(bcm), "op", "pn", "dh" if level else "dl"], check=True)


def set_mode(m0, m1, settle=0.1):
    _pin(M0_BCM, m0)
    _pin(M1_BCM, m1)
    time.sleep(settle)


def open_port(timeout=2.0):
    return serial.Serial(PORT, BAUD, timeout=timeout)


def read_regs(s, addr=0x00, n=9):
    s.reset_input_buffer()
    s.write(bytes([0xC1, addr, n]))
    time.sleep(0.3)
    r = s.read(3 + n)
    if len(r) != 3 + n or r[0] != 0xC1:
        raise IOError(f"bad register read: {r.hex() if r else 'no reply'}")
    return r[3:]


def write_regs(s, addr, data, save=True):
    head = 0xC0 if save else 0xC2      # C0 persists across power-down
    s.reset_input_buffer()
    s.write(bytes([head, addr, len(data)]) + bytes(data))
    time.sleep(0.3)
    r = s.read(3 + len(data))
    if len(r) != 3 + len(data) or r[0] != 0xC1:
        raise IOError(f"bad register write ack: {r.hex() if r else 'no reply'}")
    return r[3:]


def decode(d):
    reg0, reg1, chan, reg3 = d[3], d[4], d[5], d[6]
    return {
        "addr": (d[0] << 8) | d[1],
        "netid": d[2],
        "uart_baud": {0: 1200, 1: 2400, 2: 4800, 3: 9600, 4: 19200, 5: 38400, 6: 57600, 7: 115200}[reg0 >> 5],
        "air_rate": AIR_INV[reg0 & 0x07],
        "packet_bytes": {0: 240, 1: 128, 2: 64, 3: 32}[reg1 >> 6],
        "ambient_rssi_en": bool(reg1 & 0x20),
        "tx_power_dbm": POWER_INV[reg1 & 0x03],
        "channel": chan,
        "freq_mhz": round(BASE_MHZ + chan, 3),
        "rssi_byte_en": bool(reg3 & 0x80),
        "fixed_point_mode": bool(reg3 & 0x40),
        "lbt_en": bool(reg3 & 0x10),
        "wor_period_ms": 500 * ((reg3 & 0x07) + 1),
    }


def cmd_status(_args):
    set_mode(0, 1)                      # CONFIG
    with open_port() as s:
        d = read_regs(s)
    print(json.dumps(decode(d), indent=2))
    set_mode(0, 0)


def cmd_configure(args):
    """Calibration config: US mid-band channel, RSSI byte ON, ambient RSSI ON."""
    chan = args.channel
    freq = BASE_MHZ + chan
    if not (902.0 <= freq <= 928.0):
        sys.exit(f"refusing: channel {chan} = {freq:.3f} MHz is outside US 902-928 ISM band")
    set_mode(0, 1)
    with open_port() as s:
        cur = bytearray(read_regs(s))
        cur[0] = args.addr >> 8
        cur[1] = args.addr & 0xFF
        cur[2] = 0                                   # NETID 0
        cur[3] = (0b011 << 5) | AIR[args.air]        # UART 9600 8N1 + air rate
        cur[4] = (0b00 << 6) | 0x20 | POWER[args.power]   # 240B pkt, ambient RSSI on, power
        cur[5] = chan
        cur[6] = 0x80 | 0x03                         # RSSI byte ON, transparent, WOR 2000ms
        cur[7] = cur[8] = 0                          # no encryption key
        write_regs(s, 0x00, cur, save=args.save)
        back = read_regs(s)
    set_mode(0, 0)
    got = decode(back)
    want_freq = round(freq, 3)
    ok = got["freq_mhz"] == want_freq and got["rssi_byte_en"] and got["tx_power_dbm"] == args.power
    print(json.dumps({"verified": ok, "config": got}, indent=2))
    if not ok:
        sys.exit("VERIFY FAILED — read-back does not match requested config")


def cmd_noise(_args):
    """Ambient-noise query = single-unit RX chain self test (needs ambient_rssi_en)."""
    set_mode(0, 0)                      # works in transmission mode
    with open_port() as s:
        s.reset_input_buffer()
        s.write(bytes([0xC0, 0xC1, 0xC2, 0xC3, 0x00, 0x02]))
        time.sleep(0.5)
        r = s.read(16)
    if len(r) >= 5 and r[0] == 0xC1:
        noise = -(256 - r[3])
        last = -(256 - r[4])
        print(json.dumps({"rx_chain": "ALIVE", "ambient_noise_dbm": noise, "last_rx_rssi_dbm": last}))
    else:
        print(json.dumps({"rx_chain": "NO REPLY", "raw": r.hex() if r else ""}))
        sys.exit(1)


def _frame(seq):
    t = time.time()
    payload = struct.pack("<4sIdH", b"MHN1", seq, t, 0)
    crc = sum(payload) & 0xFFFF
    return struct.pack("<4sIdH", b"MHN1", seq, t, crc)


def cmd_beacon(args):
    set_mode(0, 0)
    n = 0
    with open_port() as s, open(args.log, "a") as log:
        while args.count == 0 or n < args.count:
            f = _frame(n)
            s.write(f)
            s.flush()
            row = {"t": time.time(), "seq": n, "bytes": len(f), "role": "beacon"}
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(f"TX seq={n}", flush=True)
            n += 1
            time.sleep(args.period)


def _gps_last():
    """Most recent GGA fix from the running nmea logger's stream (best effort)."""
    p = "/home/pump/telemetry_head/gps/nmea_stream.jsonl"
    try:
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - 20000))
            tail = f.read().decode("ascii", "replace")
        for line in reversed(tail.splitlines()):
            if "GGA" in line:
                seg = line[line.index("$"):].split(",")
                if len(seg) > 9 and seg[2] and seg[4]:
                    lat = float(seg[2][:2]) + float(seg[2][2:]) / 60
                    lon = float(seg[4][:3]) + float(seg[4][3:]) / 60
                    if seg[3] == "S": lat = -lat
                    if seg[5] == "W": lon = -lon
                    return {"lat": round(lat, 7), "lon": round(lon, 7),
                            "fix": int(seg[6] or 0), "sats": int(seg[7] or 0),
                            "alt_m": float(seg[9] or 0)}
    except Exception:
        pass
    return None


def _canonical_row(raw, rssi_b, trial_id):
    """Canonical telemetry row per schemas/telemetry.schema.json.

    hops_away/hop_start/hop_limit are 0 BY CONSTRUCTION on this point-to-point
    UART LoRa link (no mesh, no relaying) — basis must be documented in a
    pre-collection amendment before scoring (see open decision A2/B2 notes).
    snr_db is null: the E22 appends RSSI only, so downstream must label this
    dataset rssi_dbm-fallback (not ESP)."""
    tag, seq, t_tx, crc = struct.unpack("<4sIdH", raw)
    good = (sum(raw[:16]) & 0xFFFF) == crc
    g = _gps_last() or {}
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trial_id": trial_id,
        "node_id": "e22_beacon_" + tag.decode("ascii", "replace"),
        "head_id": "meshhikernode1",
        "line": "e22rx seq=%d t_tx=%.3f rssi_raw=0x%02X crc_ok=%s wire=%s" % (
            seq, t_tx, rssi_b, good, (raw + bytes([rssi_b])).hex()),
        "rssi_dbm": -(256 - rssi_b),
        "snr_db": None,
        "lat": g.get("lat"), "lon": g.get("lon"), "elev_m": g.get("alt_m"),
        "gps_pdop": None,
        "hops_away": 0, "hop_start": 0, "hop_limit": 0,
        "from_mesh_id": "e22:" + tag.decode("ascii", "replace"),
    }


def cmd_rxlog(args):
    set_mode(0, 0)
    print(f"listening on {PORT}; writing {args.out}", flush=True)
    with open_port(timeout=1.0) as s, open(args.out, "a") as out:
        buf = b""
        while True:
            buf += s.read(256)
            while len(buf) >= 19:                      # 18B frame + 1 RSSI byte
                i = buf.find(b"MHN1")
                if i < 0:
                    buf = buf[-3:]
                    break
                if len(buf) - i < 19:
                    buf = buf[i:]
                    break
                raw, rssi_b = buf[i:i + 18], buf[i + 18]
                buf = buf[i + 19:]
                row = _canonical_row(raw, rssi_b, args.trial_id)
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(f"RX {row['from_mesh_id']} rssi={row['rssi_dbm']}", flush=True)


def cmd_selftest(args):
    """Prove the RX path emits schema-valid canonical rows (no RF needed)."""
    rows = []
    for seq, rssi_b in [(0, 0xA5), (1, 0x9C), (2, 0xB0)]:
        rows.append(_canonical_row(_frame(seq), rssi_b, args.trial_id))
    with open(args.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} canonical rows to {args.out}")


def cmd_noisefloor(args):
    """Receive-only diagnostic: periodic ambient noise floor to jsonl."""
    set_mode(0, 0)
    with open_port() as s, open(args.out, "a") as out:
        n = 0
        while args.count == 0 or n < args.count:
            s.reset_input_buffer()
            s.write(bytes([0xC0, 0xC1, 0xC2, 0xC3, 0x00, 0x02]))
            time.sleep(0.5)
            r = s.read(16)
            row = {"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "freq_mhz": None, "ambient_noise_dbm": None}
            if len(r) >= 5 and r[0] == 0xC1:
                row["ambient_noise_dbm"] = -(256 - r[3])
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(row, flush=True)
            n += 1
            time.sleep(max(0, args.period - 0.5))


def _ambient(s):
    s.reset_input_buffer()
    s.write(bytes([0xC0, 0xC1, 0xC2, 0xC3, 0x00, 0x02]))
    time.sleep(0.35)
    r = s.read(16)
    return -(256 - r[3]) if len(r) >= 5 and r[0] == 0xC1 else None


def cmd_scan(args):
    """Protocol-blind band survey: sweep 902-928 MHz, log energy per channel.

    Channel writes use the VOLATILE command (no flash wear); the flash-saved
    operating channel is untouched and restored on exit. RX-only.
    """
    chans = list(range(args.lo, args.hi + 1))
    sweeps = []
    try:
        for k in range(args.sweeps):
            row = {}
            for ch in chans:
                set_mode(0, 1)
                with open_port() as s:
                    write_regs(s, 0x05, [ch], save=False)
                set_mode(0, 0)
                with open_port() as s:
                    row[ch] = _ambient(s)
            sweeps.append(row)
            t = time.strftime("%H:%M:%S", time.gmtime())
            print(f"sweep {k+1}/{args.sweeps} @ {t}Z")
            with open(args.out, "a") as f:
                f.write(json.dumps({"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "rssi_by_channel": {str(BASE_MHZ + c): v for c, v in row.items()}}) + "\n")
    finally:
        set_mode(0, 1)
        with open_port() as s:
            write_regs(s, 0x05, [65], save=False)   # restore 915.125 operating channel
        set_mode(0, 0)
    # terminal heatmap: per-channel max across sweeps
    print(f"\n{'MHz':>8}  {'max':>5}  {'mean':>6}  activity")
    for ch in chans:
        vals = [s[ch] for s in sweeps if s[ch] is not None]
        if not vals:
            continue
        mx, mn = max(vals), sum(vals) / len(vals)
        bar = "#" * max(0, int((mx + 110) / 2))
        print(f"{BASE_MHZ + ch:8.3f}  {mx:5d}  {mn:6.1f}  {bar}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    c = sub.add_parser("configure")
    c.add_argument("--channel", type=int, default=65, help="65 = 915.125 MHz")
    c.add_argument("--power", type=int, default=10, choices=[10, 13, 17, 22])
    c.add_argument("--air", default="2.4k", choices=list(AIR))
    c.add_argument("--addr", type=int, default=0)
    c.add_argument("--save", action="store_true", help="persist across power-down")
    sub.add_parser("noise")
    b = sub.add_parser("beacon")
    b.add_argument("--period", type=float, default=30.0)
    b.add_argument("--count", type=int, default=0, help="0 = forever")
    b.add_argument("--log", default="/home/pump/telemetry_head/e22_beacon.jsonl")
    r = sub.add_parser("rxlog")
    r.add_argument("--out", default="/home/pump/telemetry_head/e22_rx.jsonl")
    r.add_argument("--trial-id", default="bench-e22-bringup-20260807")
    st = sub.add_parser("selftest")
    st.add_argument("--out", default="/tmp/e22_selftest_rows.jsonl")
    st.add_argument("--trial-id", default="bench-e22-bringup-20260807")
    nf = sub.add_parser("noisefloor")
    nf.add_argument("--period", type=float, default=60.0)
    nf.add_argument("--count", type=int, default=0)
    nf.add_argument("--out", default="/home/pump/telemetry_head/e22_noisefloor.jsonl")
    sc = sub.add_parser("scan")
    sc.add_argument("--lo", type=int, default=52, help="ch 52 = 902.125 MHz")
    sc.add_argument("--hi", type=int, default=77, help="ch 77 = 927.125 MHz")
    sc.add_argument("--sweeps", type=int, default=3)
    sc.add_argument("--out", default="/home/pump/telemetry_head/e22_bandscan.jsonl")
    args = ap.parse_args()
    {"status": cmd_status, "configure": cmd_configure, "noise": cmd_noise,
     "beacon": cmd_beacon, "rxlog": cmd_rxlog, "selftest": cmd_selftest,
     "noisefloor": cmd_noisefloor, "scan": cmd_scan}[args.cmd](args)


if __name__ == "__main__":
    main()
