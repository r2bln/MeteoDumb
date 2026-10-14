#!/usr/bin/env python3
"""
Reads the latest meteo-exporter reading from a prometheus-node-exporter
textfile-collector .prom file (see meteo-exporter.sh / METEO-1) and sends
a single APRS position+weather report to APRS-IS. No radio involved: this
is a pure APRS-IS ("headless") client, meant to be run periodically by a
systemd timer (see systemd/aprs-beacon.{service,timer} / METEO-2).

One invocation = one beacon. Periodicity is systemd's job, not this
script's.
"""

import glob
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

PROM_FILE = os.environ.get(
    "APRS_PROM_FILE",
    os.path.join(
        os.environ.get("METEO_TEXTFILE_DIR", "/var/lib/prometheus/node-exporter"),
        "meteo.prom",
    ),
)
STATE_FILE = os.environ.get("APRS_STATE_FILE", "/var/lib/aprs-beacon/last-sent")
TELEMETRY_SEQ_FILE = os.environ.get(
    "APRS_TELEMETRY_SEQ_FILE",
    os.path.join(os.path.dirname(STATE_FILE), "telemetry-seq"),
)
SERVER = os.environ.get("APRS_SERVER", "rotate.aprs2.ru:14580")
CALLSIGN = os.environ.get("APRS_CALLSIGN")
LAT = os.environ.get("APRS_LAT")
LON = os.environ.get("APRS_LON")
PASSCODE = os.environ.get("APRS_PASSCODE")
COMMENT = os.environ.get("APRS_COMMENT", "")
# APRS_WEATHER=0: no weather/position packet, telemetry only - for a host whose
# callsign already beacons its position from elsewhere (METEO-5).
WEATHER = os.environ.get("APRS_WEATHER", "1") != "0"
# APRS_TRANSPORT=http: one-shot HTTP POST submit (APRS_SERVER port 8080) instead
# of a TCP login - doesn't hold an APRS-IS session, so it doesn't clash with
# another client logged in under the same callsign (METEO-5).
TRANSPORT = os.environ.get("APRS_TRANSPORT", "tcp")
SENSOR_NOTE = "sensor-in-sun(temp+)"
CONNECT_TIMEOUT = 10

# APRS telemetry (METEO-4): 5 analog channels, raw value 0..255 each, real
# value = a*x^2 + b*x + c with (a, b, c) from EQNS. Tuples are
# (PARM name, UNIT, b); a and c are always 0. Load average has b=0.02 so it
# fits 0..5.10 into one byte - clamped above that.
TELEMETRY_CHANNELS = (
    ("CPU", "%", 1),
    ("RAM", "%", 1),
    ("Load", "load", 0.02),
    ("SysT", "C", 1),
    ("MBT", "C", 1),
)
TELEMETRY_TITLE = os.environ.get("APRS_TELEMETRY_TITLE", "MeteoDumb host")
# PARM/UNIT/EQNS/BITS are resent every Nth telemetry packet (and on seq 0,
# i.e. after a fresh start) - at the default 600s interval that's hourly.
TELEMETRY_META_EVERY = 6


def log(msg):
    print(f"aprs-beacon: {msg}", file=sys.stderr)


def aprs_passcode(callsign):
    """Standard APRS-IS passcode algorithm, derived from the base callsign
    (SSID stripped). Public/deterministic - no registration needed."""
    base = callsign.split("-")[0].upper()
    h = 0x73E2
    for i, ch in enumerate(base):
        h ^= ord(ch) << (8 if i % 2 == 0 else 0)
    return h & 0x7FFF


def read_reading(path):
    values = {}
    pattern = re.compile(r"^(meteo_\w+)\s+([0-9.eE+-]+)\s*$")
    with open(path) as f:
        for line in f:
            m = pattern.match(line)
            if m:
                values[m.group(1)] = float(m.group(2))

    missing = [
        k
        for k in (
            "meteo_temperature_celsius",
            "meteo_humidity_percent",
            "meteo_pressure_pascals",
            "meteo_last_reading_timestamp_seconds",
        )
        if k not in values
    ]
    if missing:
        raise ValueError(f"{path} is missing metric(s): {', '.join(missing)}")
    return values


def format_lat(lat):
    deg = int(abs(lat))
    minutes = (abs(lat) - deg) * 60
    hemi = "N" if lat >= 0 else "S"
    return f"{deg:02d}{minutes:05.2f}{hemi}"


def format_lon(lon):
    deg = int(abs(lon))
    minutes = (abs(lon) - deg) * 60
    hemi = "E" if lon >= 0 else "W"
    return f"{deg:03d}{minutes:05.2f}{hemi}"


def format_temp_f(temp_c):
    temp_f = round(temp_c * 9 / 5 + 32)
    if temp_f < 0:
        return f"-{abs(temp_f):02d}"
    return f"{temp_f:03d}"


def format_humidity(pct):
    h = round(pct)
    if h >= 100:
        return "00"
    return f"{h:02d}"


def format_pressure(pascals):
    # 1 hPa (mbar) = 100 Pa; field is tenths of a millibar.
    tenths_mbar = round(pascals / 10)
    return f"{tenths_mbar:05d}"


def read_cpu_pct(sample_time=0.3):
    def snapshot():
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = list(map(int, parts[1:]))
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)

    idle1, total1 = snapshot()
    time.sleep(sample_time)
    idle2, total2 = snapshot()
    dtotal = total2 - total1
    if dtotal <= 0:
        return 0.0
    return 100.0 * (1 - (idle2 - idle1) / dtotal)


def read_mem_pct():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k.strip()] = int(v.strip().split()[0])
    total = info["MemTotal"]
    avail = info.get("MemAvailable", info["MemFree"])
    return 100.0 * (total - avail) / total


def read_loadavg():
    with open("/proc/loadavg") as f:
        one, five, fifteen = f.read().split()[:3]
    return one, five, fifteen


def read_uptime_str():
    with open("/proc/uptime") as f:
        seconds = float(f.read().split()[0])
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d{hours}h"
    return f"{hours}h{minutes}m"


def _read_hwmon_temp_c(*names):
    """First temp1_input under /sys/class/hwmon whose driver name matches
    (same source `sensors` reads from) - no subprocess needed. Matched by
    prefix: the kernel appends "_0", "_1", etc. to the name when more than
    one hwmon device would otherwise collide (e.g. "acpitz_0")."""
    for name_path in glob.glob("/sys/class/hwmon/hwmon*/name"):
        try:
            with open(name_path) as f:
                name = f.read().strip()
        except OSError:
            continue
        if any(name == n or name.startswith(n + "_") for n in names):
            try:
                with open(name_path.replace("name", "temp1_input")) as tf:
                    return int(tf.read().strip()) / 1000.0
            except OSError:
                continue
    return None


def read_cpu_temp_c():
    """CPU package temperature (k10temp on AMD, coretemp on Intel)."""
    return _read_hwmon_temp_c("k10temp", "coretemp")


def read_mainboard_temp_c():
    """"acpitz" in `sensors` - a generic ACPI thermal zone, not a dedicated
    chip. Whatever the board's ACPI tables report; used here as an
    approximate mainboard/case temperature."""
    return _read_hwmon_temp_c("acpitz")


def read_host_stats():
    """CPU/mem/uptime/load/temp of the beacon's own host, sampled once and
    used for both the comment field and the telemetry packet. None if
    /proc is unreadable; temps are None when no matching hwmon exists."""
    try:
        load1, load5, load15 = read_loadavg()
        return {
            "cpu": read_cpu_pct(),
            "mem": read_mem_pct(),
            "uptime": read_uptime_str(),
            "load": (load1, load5, load15),
            "cpu_temp": read_cpu_temp_c(),
            "mb_temp": read_mainboard_temp_c(),
        }
    except OSError:
        return None


def build_sys_status(stats):
    """Host telemetry appended to the comment field so it's visible
    alongside the weather report."""
    if stats is None:
        return ""
    load1, load5, load15 = stats["load"]
    cpu_temp, mb_temp = stats["cpu_temp"], stats["mb_temp"]
    cpu_temp_part = f" CPU:{cpu_temp:.0f}C" if cpu_temp is not None else ""
    mb_temp_part = f" MB:{mb_temp:.0f}C" if mb_temp is not None else ""
    return (
        f"HOST:{socket.gethostname()} cpu-used:{stats['cpu']:.0f}% "
        f"mem-used:{stats['mem']:.0f}% UP:{stats['uptime']} "
        f"LD:{load1}/{load5}/{load15}{cpu_temp_part}{mb_temp_part}"
    )


def next_telemetry_seq(path):
    """Sequence number 000..999, persisted next to the last-sent state file.
    Starts over from 0 if the file is missing/unreadable."""
    try:
        with open(path) as f:
            seq = (int(f.read().strip()) + 1) % 1000
    except (OSError, ValueError):
        seq = 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{seq}\n")
    return seq


def telemetry_raw(value, scale):
    """Real value -> raw 0..255 byte for a channel with EQNS b=scale.
    Missing values (no hwmon) go out as 0."""
    if value is None:
        return 0
    return max(0, min(255, round(value / scale)))


def build_telemetry_packets(callsign, stats, seq, with_meta):
    values = (
        stats["cpu"],
        stats["mem"],
        float(stats["load"][0]),
        stats["cpu_temp"],
        stats["mb_temp"],
    )
    analog = ",".join(
        f"{telemetry_raw(v, ch[2]):03d}" for v, ch in zip(values, TELEMETRY_CHANNELS)
    )
    packets = [f"{callsign}>APRS,TCPIP*:T#{seq:03d},{analog},00000000"]
    if with_meta:
        # Telemetry metadata goes out as APRS messages addressed to the
        # station itself; addressee is padded to exactly 9 characters.
        to = f"{callsign:<9}"
        names = ",".join(ch[0] for ch in TELEMETRY_CHANNELS)
        units = ",".join(ch[1] for ch in TELEMETRY_CHANNELS)
        eqns = ",".join(f"0,{ch[2]},0" for ch in TELEMETRY_CHANNELS)
        for body in (
            f"PARM.{names}",
            f"UNIT.{units}",
            f"EQNS.{eqns}",
            f"BITS.00000000,{TELEMETRY_TITLE}",
        ):
            packets.append(f"{callsign}>APRS,TCPIP*::{to}:{body}")
    return packets


def build_packet(callsign, lat, lon, reading, comment):
    position = f"{format_lat(lat)}/{format_lon(lon)}_"
    wind = ".../...g..."
    temp = f"t{format_temp_f(reading['meteo_temperature_celsius'])}"
    humidity = f"h{format_humidity(reading['meteo_humidity_percent'])}"
    pressure = f"b{format_pressure(reading['meteo_pressure_pascals'])}"
    return f"{callsign}>APRS,TCPIP*:!{position}{wind}{temp}{humidity}{pressure}{comment}"


def send(server, callsign, passcode, packets):
    if TRANSPORT == "http":
        send_http(server, callsign, passcode, packets)
        return
    host, port = server.split(":")
    with socket.create_connection((host, int(port)), timeout=CONNECT_TIMEOUT) as sock:
        f = sock.makefile("rw", encoding="ascii", newline="\r\n")
        f.write(f"user {callsign} pass {passcode} vers MeteoDumb-aprs-beacon 1.0\r\n")
        f.flush()
        f.readline()  # server login banner/ack
        for packet in packets:
            f.write(packet + "\r\n")
        f.flush()


def send_http(server, callsign, passcode, packets):
    """APRS-IS HTTP submit: login line + one packet per POST - aprsc takes only
    the first line after the login and silently drops the rest, so packets go
    out as separate requests. The server answers 200 only for a verified login;
    anything else raises."""
    login = f"user {callsign} pass {passcode} vers MeteoDumb-aprs-beacon 1.0\r\n"
    for packet in packets:
        req = urllib.request.Request(
            f"http://{server}/",
            data=(login + packet + "\r\n").encode("ascii"),
            headers={"Content-Type": "application/octet-stream", "Accept-Type": "text/plain"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as resp:
                resp.read()
        except urllib.error.URLError as e:
            # HTTPError (non-2xx) is a URLError too; re-raise as plain OSError
            # so main() logs the server's reason.
            raise OSError(f"HTTP submit failed: {e}") from e


def main():
    if not CALLSIGN:
        log("APRS_CALLSIGN is required")
        return 1
    if WEATHER and (not LAT or not LON):
        log("APRS_LAT and APRS_LON are required unless APRS_WEATHER=0")
        return 1
    if TRANSPORT not in ("tcp", "http"):
        log(f"APRS_TRANSPORT must be tcp or http, got {TRANSPORT!r}")
        return 1

    passcode = PASSCODE if PASSCODE is not None else aprs_passcode(CALLSIGN)
    stats = read_host_stats()
    packets = []

    if WEATHER:
        try:
            reading = read_reading(PROM_FILE)
        except (OSError, ValueError) as e:
            log(f"could not read sensor data from {PROM_FILE}: {e}")
            return 1

        age = time.time() - reading["meteo_last_reading_timestamp_seconds"]
        if age > 300:
            log(f"latest sensor reading is {age:.0f}s old, refusing to beacon stale data")
            return 1

        comment_parts = [COMMENT, SENSOR_NOTE, build_sys_status(stats)]
        comment = " ".join(p for p in comment_parts if p)
        packets.append(build_packet(CALLSIGN, float(LAT), float(LON), reading, comment))
    elif stats is None:
        log("telemetry-only mode, but host stats are unreadable - nothing to send")
        return 1

    if stats is not None:
        try:
            seq = next_telemetry_seq(TELEMETRY_SEQ_FILE)
        except OSError as e:
            log(f"could not persist telemetry seq to {TELEMETRY_SEQ_FILE}: {e}")
            seq = 0
        with_meta = seq % TELEMETRY_META_EVERY == 0
        packets += build_telemetry_packets(CALLSIGN, stats, seq, with_meta)

    try:
        send(SERVER, CALLSIGN, passcode, packets)
    except OSError as e:
        log(f"failed to send beacon to {SERVER}: {e}")
        return 1

    for packet in packets:
        log(f"sent: {packet}")

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        f.write(f"{int(time.time())}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
