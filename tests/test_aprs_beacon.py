#!/usr/bin/env python3
"""Functional tests for aprs-beacon.py against a fake APRS-IS server.

Each case runs the real script as a subprocess with a temp PROM_FILE/state
dir and a local TCP listener posing as APRS-IS, then asserts on the exact
packet set it emitted. Run: python3 tests/test_aprs_beacon.py
"""

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "aprs-beacon.py"
CALL = "R2BLN-13"


class FakeAprsIs(threading.Thread):
    """One-shot APRS-IS: accepts one client, answers its login, records lines."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.lines = []

    def run(self):
        self.sock.settimeout(10)
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(10)
            f = conn.makefile("rb")
            for raw in f:
                line = raw.decode("ascii", "replace").strip()
                if not line:
                    continue
                if line.startswith("user "):
                    # aprs-beacon blocks on readline() after login - must answer.
                    conn.sendall(b"# fake aprsc\r\n")
                else:
                    self.lines.append(line)
        self.sock.close()


def write_prom(path, temp_c, hum_pct, pres_hpa, ts):
    Path(path).write_text(
        "meteo_temperature_celsius %r\n"
        "meteo_humidity_percent %r\n"
        "meteo_pressure_pascals %r\n"
        "meteo_last_reading_timestamp_seconds %r\n"
        % (temp_c, hum_pct, pres_hpa * 100.0, ts)
    )


class BeaconTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "state")
        self.prom = os.path.join(self.tmp.name, "meteo.prom")

    def run_beacon(self):
        server = FakeAprsIs()
        server.start()
        env = dict(
            os.environ,
            APRS_CALLSIGN=CALL,
            APRS_LAT="55.93283",
            APRS_LON="36.01851",
            APRS_SERVER=f"127.0.0.1:{server.port}",
            APRS_PROM_FILE=self.prom,
            APRS_STATE_FILE=os.path.join(self.state, "last-sent"),
            APRS_TELEMETRY_SEQ_FILE=os.path.join(self.state, "telemetry-seq"),
        )
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        server.join(timeout=15)
        return proc, server.lines

    @staticmethod
    def is_weather(lines):
        return [l for l in lines if f"{CALL}>APRS,TCPIP*:!" in l]

    @staticmethod
    def is_telemetry(lines):
        return [l for l in lines if ":T#" in l]

    def test_sane_reading_sends_weather_and_telemetry(self):
        write_prom(self.prom, 5.5, 70.0, 990.2, time.time())
        proc, lines = self.run_beacon()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(1, len(self.is_weather(lines)), lines)
        weather = self.is_weather(lines)[0]
        self.assertIn("t042", weather)  # 5.5C = 41.9F
        self.assertIn("h70", weather)
        self.assertIn("b09902", weather)
        self.assertTrue(self.is_telemetry(lines), lines)

    def test_garbage_values_send_telemetry_only(self):
        # The 2026-11-13 failure: sensor reads all-ones, values are fresh
        # garbage (+180C / 100% / -179hPa) - must not look like weather.
        write_prom(self.prom, 180.12, 100.0, -179.05, time.time())
        proc, lines = self.run_beacon()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([], self.is_weather(lines), lines)
        self.assertTrue(self.is_telemetry(lines), lines)
        self.assertIn("implausible", proc.stderr)

    def test_stale_reading_sends_telemetry_only(self):
        write_prom(self.prom, 5.5, 70.0, 990.2, time.time() - 3600)
        proc, lines = self.run_beacon()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([], self.is_weather(lines), lines)
        self.assertTrue(self.is_telemetry(lines), lines)
        self.assertIn("old", proc.stderr)

    def test_missing_prom_file_sends_telemetry_only(self):
        proc, lines = self.run_beacon()  # self.prom never written
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([], self.is_weather(lines), lines)
        self.assertTrue(self.is_telemetry(lines), lines)


if __name__ == "__main__":
    unittest.main(verbosity=2)
