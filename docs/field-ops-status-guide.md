# Field Ops Status Guide — meshradiohead2

This guide is for anyone checking on the system during or after a hike when the
primary operator is not available. Read it before touching anything.

---

## The Short Version

**One command tells you if everything is OK:**

```bash
ssh meshradiohead2 'python3 /home/pump/telemetry_head/scripts/head_readiness_report.py'
```

If it prints `READY` with no red lines, the system is fine. Stop there. Do not
restart anything, do not install timers, do not change service files.

---

## What the System Is Doing

There are four services running on the Pi at all times:

| Service | What it does |
|---|---|
| `telemetry_collector_head` | Listens to the LoRa radio and writes a log file |
| `telemetry_sync_spool` | Copies the log file to this Mac every 2 minutes |
| `starlink_raw_poller` | Reads Starlink signal stats |
| `starlink_window_aggregator` | Summarizes those stats |

The `meshtastic_fallback_worker` is a backup command channel — it only activates
when the internet is down. It being "inactive" is normal and expected.

---

## How to Check Status (Do This, Not That)

### Correct way — check all services at once

```bash
ssh meshradiohead2 'for svc in telemetry_collector_head starlink_raw_poller starlink_window_aggregator; do echo -n "$svc: "; systemctl is-active $svc; done'
```

Expected output — every line should say `active`:

```
telemetry_collector_head: active
starlink_raw_poller: active
starlink_window_aggregator: active
```

### If something says `inactive` or `failed`, check why before acting

```bash
ssh meshradiohead2 'systemctl status telemetry_collector_head --no-pager -n 20'
```

Read the output. Look for actual error messages. A service saying `active (running)`
with a recent start time is fine. `failed` or `activating` for more than 30 seconds
means something needs attention.

### Check the live log to confirm data is flowing

```bash
ssh meshradiohead2 'tail -f /home/pump/telemetry_head/jsonl/telemetry_stream.jsonl'
```

You should see new JSON lines appearing roughly every 30–60 seconds. If you go 5+
minutes with nothing new, that may indicate the radio is not receiving packets from
nearby mesh nodes — this is not necessarily a failure, it may just mean no other
Meshtastic devices are in range.

---

## How to Read the Service Journal

```bash
ssh meshradiohead2 'journalctl -u telemetry_collector_head.service -n 30 --no-pager'
```

What you are looking for:

| What you see | What it means | Action |
|---|---|---|
| `Started ... Collector` once, nothing after | Service started and is running normally | None |
| `Started` repeatedly every few minutes | Service is crash-looping — something is wrong | Investigate — see below |
| `python3: ... Error: ...` | Actual crash with a Python traceback | Read the error, report it |
| `Stopping` + `Started` every 15 minutes on the clock | An external restart timer was installed unnecessarily | Remove it — see below |

---

## Understanding Data Gaps

The log file is append-only. A gap in timestamps does not necessarily mean the
service crashed. It can mean:

- **No nearby Meshtastic nodes transmitting** — the radio is on and listening but
  there is nothing to hear. This is common on trails before other hikers with
  Meshtastic devices arrive.

- **Meshtastic library reconnecting** — the Python library that talks to the radio
  occasionally drops its internal connection and reconnects silently. The service
  does not crash. It resumes on its own in minutes. The service already has
  `Restart=always` — it restarts itself within 2 seconds if it actually crashes.

- **Starlink/IP was down** — this does not affect telemetry collection. The log file
  is written locally on the Pi. Data is synced when connectivity resumes.

**A gap in the log file is not proof that the service was broken.** Check the journal
for actual errors before concluding anything.

---

## What NOT to Do

### Do not install restart timers

Do not run `systemctl enable` or create new `.service` / `.timer` files to restart
the collector on a schedule. The service already handles its own restarts. An
external timer that force-restarts the collector every N minutes causes a data gap
every N minutes, permanently, for no benefit.

To verify no rogue timers are installed:

```bash
ssh meshradiohead2 'systemctl list-timers --no-pager'
```

The only MANET-related timers that should appear are:
- `meshtastic_fallback_worker.timer`
- `telemetry_sync_spool.timer`

If you see anything with `restart` in the name, remove it:

```bash
ssh meshradiohead2 'sudo systemctl stop <timer-name>.timer && sudo systemctl disable <timer-name>.timer && sudo rm /etc/systemd/system/<timer-name>.timer /etc/systemd/system/<timer-name>.service && sudo systemctl daemon-reload'
```

### Do not restart a running service without reading the journal first

If the service shows `active (running)`, a restart will cause a data gap and
accomplish nothing. Only restart if the service shows `failed` or `inactive` and
the journal shows an actual error.

### Do not compare the log rate to home behavior

The Pi at home receives its own node's periodic heartbeats. On a trail the radio
may hear dozens of strangers' Meshtastic devices — or none, depending on who is
nearby. Sparse log output is expected in low-traffic areas.

---

## When Something Is Actually Wrong

These are real problems that warrant action:

**Service shows `failed` with a Python traceback in the journal:**
```bash
ssh meshradiohead2 'sudo systemctl restart telemetry_collector_head'
```
Then read the journal to confirm it started cleanly.

**`/dev/lora_radio` not found (radio physically disconnected):**
```bash
ssh meshradiohead2 'ls -la /dev/lora_radio'
```
If missing, the USB cable between the Pi and the Heltec radio is unplugged or the
device was not recognized. Reconnect the cable. The service will reconnect on its
own within a few seconds once the device node appears.

**Disk full:**
```bash
ssh meshradiohead2 'df -h /home/pump'
```
If above 90% used, notify the primary operator before doing anything.

---

## Quick Reference — Safe Commands Only

```bash
# Full status check
ssh meshradiohead2 'python3 /home/pump/telemetry_head/scripts/head_readiness_report.py'

# Are all services active?
ssh meshradiohead2 'for svc in telemetry_collector_head starlink_raw_poller starlink_window_aggregator; do echo -n "$svc: "; systemctl is-active $svc; done'

# Is data flowing? (watch for 60 seconds)
ssh meshradiohead2 'tail -f /home/pump/telemetry_head/jsonl/telemetry_stream.jsonl'

# How many rows collected today?
ssh meshradiohead2 'grep -c "$(date -u +%Y-%m-%d)" /home/pump/telemetry_head/jsonl/telemetry_stream.jsonl'

# Disk space
ssh meshradiohead2 'df -h /home/pump'

# Last 20 journal lines for collector
ssh meshradiohead2 'journalctl -u telemetry_collector_head.service -n 20 --no-pager'
```
