#!/usr/bin/env python3
"""
ism-exporter: tail-читает сервисные логи декодера ISM (rtl_433 внутри OpenWebRX+,
см. METEO-6) и поддерживает prometheus-node-exporter textfile-коллектор .prom файл
с показаниями "опорного" датчика температуры - самого стабильно принимаемого за
последнее окно. Формат .prom совместим с meteo-exporter.sh: aprs-beacon.py читает
те же метрики meteo_* и шлёт их погодным маячком (METEO-2).

Вход: ISM_DECODE_DIR (по умолчанию /var/lib/openwebrx/decodes), куда OpenWebRX+
пишет файлы вида ISM-261118-183005-433920.txt - по одной записи на строку.
Записи - это str() от dict (IsmParser пишет repr, не JSON), поэтому каждая строка
парсится сначала как JSON, затем как python-literal.

Опорный датчик: записи группируются по (model, id) и в пределах окна ISM_WINDOW_S
ранжируются по числу декодов (freshness как tie-break). Сдох датчик - счётчик
за окно обнулился, следующий по стабильности занимает его место сам; свежесть
meteo_last_reading_timestamp_seconds определяет сам aprs-beacon (STALE_AFTER_S).

Давления у ISM-датчиков почти никогда нет, влажность - примерно у половины:
эти метрики пишутся только когда источник их действительно даёт, а aprs-beacon.py
(METEO-6-патч) пропускает отсутствующие поля в APRS-пакете.

Запуск - вечный цикл в одном процессе (см. Dockerfile.ism-exporter): свежесть
выхлопа должна переживать паузы между передачами датчиков.
"""

import ast
import glob
import json
import os
import sys
import time

DECODE_DIR = os.environ.get("ISM_DECODE_DIR", "/var/lib/openwebrx/decodes")
TEXTFILE_DIR = os.environ.get(
    "METEO_TEXTFILE_DIR", "/var/lib/prometheus/node-exporter"
)
PROM_FILE = os.environ.get("ISM_PROM_FILE") or os.path.join(
    TEXTFILE_DIR, "meteo.prom"
)
WINDOW_S = float(os.environ.get("ISM_WINDOW_S", "1800"))
INTERVAL_S = float(os.environ.get("ISM_INTERVAL_S", "5"))


def log(msg):
    print(f"ism-exporter: {msg}", file=sys.stderr, flush=True)


def parse_line(line):
    """Одна строка лога -> dict или None (мусор/неполная запись в момент записи)."""
    line = line.strip()
    if not line:
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            rec = loader(line)
        except (ValueError, SyntaxError):
            continue
        if isinstance(rec, dict) and "model" in rec:
            return rec
    return None


def sensor_key(rec):
    """Идентичность передатчика: пара model+id, с fallback на channel/частоту."""
    ident = rec.get("id", rec.get("channel", rec.get("freq", "?")))
    return (str(rec["model"]), str(ident))


def sensor_reading(rec):
    """(temp_c, humidity, pressure_pa) - каждое None, если этого поля нет."""
    temp = rec.get("temperature_C")
    hum = rec.get("humidity")
    pres = rec.get("pressure_hPa")
    if pres is None:
        pres = rec.get("pressure_kPa")
        if pres is not None:
            pres *= 10.0
    if pres is not None:
        pres *= 100.0  # hPa -> Pa
    return temp, hum, pres


class Tailer:
    """Помнит позицию (inode, offset) по каждому файлу каталога, отдаёт новые
    строки. Ротацию OpenWebRX+ (новый ISM-*.txt каждые maxBytes) переживает:
    просто подхватывает следующий файл."""

    def __init__(self, directory):
        self.directory = directory
        self.positions = {}

    def poll(self):
        lines = []
        for path in sorted(glob.glob(os.path.join(self.directory, "ISM-*.txt"))):
            try:
                st = os.stat(path)
            except OSError:
                continue
            inode, offset = self.positions.get(path, (None, 0))
            if inode != st.st_ino:  # новый файл (или переезд) - с начала
                inode, offset = st.st_ino, 0
            if offset > st.st_size:  # усечение - тоже с начала
                offset = 0
            if offset == st.st_size:
                self.positions[path] = (inode, offset)
                continue
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read()
            except OSError:
                continue
            self.positions[path] = (inode, st.st_size)
            for raw in chunk.split(b"\n")[:-1]:  # хвост без \n - незавершённая строка
                try:
                    lines.append(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    continue
            # незавершённую строку дочитаем следующим poll-ом: offset уже на
            # конце файла, но последняя строка без \n будет перечитана целиком
            # после завершения - только если скорректировать позицию
            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                self.positions[path] = (inode, offset)
            else:
                self.positions[path] = (inode, offset + last_nl + 1)
        return lines


class Sensors:
    """Скользящее окно декодов по датчикам + выбор опорного."""

    def __init__(self, window_s):
        self.window_s = window_s
        self.readings = {}  # key -> list[(t, temp, hum, pres)]

    def add(self, rec):
        t = float(rec.get("time") or rec.get("timestamp", 0) / 1000.0 or time.time())
        key = sensor_key(rec)
        if key not in self.readings:
            self.readings[key] = []
        self.readings[key].append((t,) + sensor_reading(rec))
        self.decay()

    def decay(self):
        horizon = time.time() - self.window_s
        for key in list(self.readings):
            kept = [r for r in self.readings[key] if r[0] >= horizon]
            if kept:
                self.readings[key] = kept
            else:
                del self.readings[key]

    def select(self):
        """Опорный датчик: (key, последнее показание) или None.
        Рейтинг - число декодов в окне (стабильность приёма), при равенстве -
        свежее последнее сообщение. Кандидаты - только датчики с температурой
        в последнем показании (погодный маяк без неё бессмыслен)."""
        best_key, best_score, best_row = None, (-1, 0), None
        for key, rows in self.readings.items():
            # Latest row: max t, ties broken by arrival order (rtl_433 logs
            # whole seconds, so two decodes within one second are common).
            last_row = max(enumerate(rows), key=lambda ir: (ir[1][0], ir[0]))[1]
            if last_row[1] is None:
                continue
            score = (len(rows), last_row[0])
            if score > best_score:
                best_key, best_score, best_row = key, score, last_row
        if best_key is None:
            return None
        return best_key, best_row


def write_prom(selected, stats):
    lines = []
    if selected:
        (model, ident), (t, temp, hum, pres) = selected
        lines.append("# HELP meteo_temperature_celsius Temperature reported by an ISM sensor (rtl_433).")
        lines.append("# TYPE meteo_temperature_celsius gauge")
        lines.append(f"meteo_temperature_celsius {temp}")
        if hum is not None:
            lines.append("# HELP meteo_humidity_percent Relative humidity reported by an ISM sensor (rtl_433).")
            lines.append("# TYPE meteo_humidity_percent gauge")
            lines.append(f"meteo_humidity_percent {hum}")
        if pres is not None:
            lines.append("# HELP meteo_pressure_pascals Atmospheric pressure reported by an ISM sensor (rtl_433).")
            lines.append("# TYPE meteo_pressure_pascals gauge")
            lines.append(f"meteo_pressure_pascals {pres}")
        lines.append("# HELP meteo_last_reading_timestamp_seconds Unix time of the last decoded transmission.")
        lines.append("# TYPE meteo_last_reading_timestamp_seconds gauge")
        lines.append(f"meteo_last_reading_timestamp_seconds {int(t)}")
        log(f"selected {model} id={ident}: t={temp} h={hum} p={pres}")
    for (model, ident), rows in sorted(stats.items()):
        labels = f'model="{model}",id="{ident}"'
        last = max(r[0] for r in rows)
        lines.append(f'# HELP rtl433_decodes_total Decodes from this sensor in the last {int(WINDOW_S)}s.')
        lines.append("# TYPE rtl433_decodes_total gauge")
        lines.append(f"rtl433_decodes_total{{{labels}}} {len(rows)}")
        lines.append("# TYPE rtl433_sensor_last_decode_seconds gauge")
        lines.append(f"rtl433_sensor_last_decode_seconds{{{labels}}} {int(last)}")

    os.makedirs(os.path.dirname(PROM_FILE), exist_ok=True)
    tmp = PROM_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, PROM_FILE)


def main():
    if not os.path.isdir(DECODE_DIR):
        log(f"decode directory {DECODE_DIR} does not exist")
        return 1
    tailer = Tailer(DECODE_DIR)
    sensors = Sensors(WINDOW_S)
    log(f"tailing {DECODE_DIR}, window {WINDOW_S}s, prom -> {PROM_FILE}")
    while True:
        for line in tailer.poll():
            rec = parse_line(line)
            if rec is not None:
                sensors.add(rec)
        sensors.decay()
        write_prom(sensors.select(), sensors.readings)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
