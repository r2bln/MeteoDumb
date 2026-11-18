#!/usr/bin/env python3
"""Functional tests for ism-exporter.py (METEO-6).

Runs the real script as a subprocess against a temp decode directory: feeds it
ISM-*.txt logs line by line (repr-dicts, exactly what OpenWebRX+ IsmParser
writes), then asserts on the meteo.prom it produced. The script is an endless
loop, so each case starts it, feeds, waits one interval, terminates, reads.
Run: python3 tests/test_ism_exporter.py
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ism-exporter.py"


class IsmExporterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.decode_dir = os.path.join(self.tmp.name, "decodes")
        self.prom = os.path.join(self.tmp.name, "meteo.prom")
        os.makedirs(self.decode_dir)
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=10)

    def start_exporter(self):
        env = dict(
            os.environ,
            ISM_DECODE_DIR=self.decode_dir,
            ISM_PROM_FILE=self.prom,
            ISM_INTERVAL_S="0.2",
        )
        self.proc = subprocess.Popen(
            [sys.executable, str(SCRIPT)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def feed(self, name, lines):
        """Append repr-dict lines to a decode file, like IsmParser.writeFile."""
        path = os.path.join(self.decode_dir, name)
        with open(path, "a") as f:
            for d in lines:
                f.write(str(d) + "\n")

    def read_prom(self):
        text = Path(self.prom).read_text()
        values = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2 and not line.startswith("#"):
                values[parts[0]] = float(parts[1])
        return values

    def test_selects_most_stable_sensor_and_handles_repr(self):
        # OpenWebRX+ writes str(dict): single quotes, not JSON.
        self.feed(
            "ISM-261118-183000-433920.txt",
            [
                {"time": int(time.time()) - 2, "model": "Nexus-TH", "id": 17, "temperature_C": 4.5, "humidity": 61},
                {"time": int(time.time()) - 1, "model": "Nexus-TH", "id": 17, "temperature_C": 4.6, "humidity": 61},
                {"time": int(time.time()), "model": "Acurite-606TX", "id": 3, "temperature_C": 21.0},
            ],
        )
        self.start_exporter()
        time.sleep(1.0)
        values = self.read_prom()
        # Two decodes beat one: Nexus-17 is the selected sensor.
        self.assertAlmostEqual(4.6, values["meteo_temperature_celsius"])
        self.assertAlmostEqual(61, values["meteo_humidity_percent"])
        self.assertNotIn("meteo_pressure_pascals", values)
        self.assertGreater(values["meteo_last_reading_timestamp_seconds"], 0)
        self.assertIn("rtl433_decodes_total", Path(self.prom).read_text())

    def test_follows_appends_and_rotation(self):
        name1 = "ISM-261118-183000-433920.txt"
        self.feed(name1, [{"time": int(time.time()), "model": "Nexus-TH", "id": 17, "temperature_C": 4.5}])
        self.start_exporter()
        time.sleep(0.8)
        # Appended lines to the same file...
        self.feed(name1, [{"time": int(time.time()), "model": "Nexus-TH", "id": 17, "temperature_C": 5.5}])
        # ...and a brand new file, like DataRecorder rotation to a fresh log.
        self.feed(
            "ISM-261118-183100-433920.txt",
            [{"time": int(time.time()), "model": "Nexus-TH", "id": 17, "temperature_C": 6.5}],
        )
        time.sleep(1.0)
        values = self.read_prom()
        self.assertAlmostEqual(6.5, values["meteo_temperature_celsius"])
        text = Path(self.prom).read_text()
        # Window counts survived the rotation: all three decodes are in.
        self.assertIn("rtl433_decodes_total{model=\"Nexus-TH\",id=\"17\"} 3", text)

    def test_sensor_without_temperature_is_not_selected(self):
        # Keyfob-ish decode without temperature_C must not become the source.
        self.feed(
            "ISM-261118-183000-433920.txt",
            [
                {"time": int(time.time()), "model": "Secplus-v1", "id": 5, "button": 1},
                {"time": int(time.time()), "model": "Nexus-TH", "id": 17, "temperature_C": 4.5, "humidity": 61},
            ],
        )
        self.start_exporter()
        time.sleep(1.0)
        values = self.read_prom()
        self.assertAlmostEqual(4.5, values["meteo_temperature_celsius"])

    def test_fahrenheit_only_sensor_is_converted(self):
        # inFactory-TH (the first real sensor around) reports temperature_F only.
        self.feed(
            "ISM-261118-183000-433920.txt",
            [{"time": int(time.time()), "model": "inFactory-TH", "id": 7, "temperature_F": 31.6, "humidity": 92}],
        )
        self.start_exporter()
        time.sleep(1.0)
        values = self.read_prom()
        self.assertAlmostEqual((31.6 - 32) * 5 / 9, values["meteo_temperature_celsius"])
        self.assertAlmostEqual(92, values["meteo_humidity_percent"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
