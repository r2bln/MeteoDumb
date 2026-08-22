#!/usr/bin/env bash
#
# Reads "T=19.56C  P=985.14hPa  H=63.07%" lines from a BME280-based serial
# sensor (see SensorSerial.ino) and maintains a prometheus-node-exporter
# textfile-collector .prom file with the latest reading.
#
# Runs as a long-lived process: the serial device is opened once (so the
# ESP32/CP210x board is not reset by a fresh DTR toggle on every read) and
# each valid line atomically replaces the .prom file.

set -uo pipefail

DEVICE="${METEO_DEVICE:-/dev/ttyUSB0}"
BAUD="${METEO_BAUD:-115200}"
TEXTFILE_DIR="${METEO_TEXTFILE_DIR:-/var/lib/prometheus/node-exporter}"
OUTFILE="${METEO_OUTFILE:-${TEXTFILE_DIR}/meteo.prom}"
TMPFILE="${OUTFILE}.tmp"

LINE_RE='T=(-?[0-9]+\.[0-9]+)C[[:space:]]+P=(-?[0-9]+\.[0-9]+)hPa[[:space:]]+H=(-?[0-9]+\.[0-9]+)%'

cleanup() {
  rm -f "$TMPFILE"
}
trap cleanup EXIT

if [[ ! -e "$DEVICE" ]]; then
  echo "meteo-exporter: serial device $DEVICE not found" >&2
  exit 1
fi

if [[ ! -d "$TEXTFILE_DIR" ]]; then
  echo "meteo-exporter: textfile collector directory $TEXTFILE_DIR does not exist" >&2
  exit 1
fi

stty -F "$DEVICE" "$BAUD" raw -echo -hupcl

echo "meteo-exporter: reading $DEVICE at ${BAUD} baud, writing $OUTFILE" >&2

while IFS= read -r line; do
  if [[ "$line" =~ $LINE_RE ]]; then
    temp_c="${BASH_REMATCH[1]}"
    pres_hpa="${BASH_REMATCH[2]}"
    hum_pct="${BASH_REMATCH[3]}"
    pres_pa="$(awk -v p="$pres_hpa" 'BEGIN { printf "%.2f", p * 100 }')"
    now="$(date +%s)"

    {
      echo "# HELP meteo_temperature_celsius Temperature reported by the BME280 sensor."
      echo "# TYPE meteo_temperature_celsius gauge"
      echo "meteo_temperature_celsius ${temp_c}"
      echo "# HELP meteo_humidity_percent Relative humidity reported by the BME280 sensor."
      echo "# TYPE meteo_humidity_percent gauge"
      echo "meteo_humidity_percent ${hum_pct}"
      echo "# HELP meteo_pressure_pascals Atmospheric pressure reported by the BME280 sensor."
      echo "# TYPE meteo_pressure_pascals gauge"
      echo "meteo_pressure_pascals ${pres_pa}"
      echo "# HELP meteo_last_reading_timestamp_seconds Unix time of the last successfully parsed reading."
      echo "# TYPE meteo_last_reading_timestamp_seconds gauge"
      echo "meteo_last_reading_timestamp_seconds ${now}"
    } > "$TMPFILE"
    mv -f "$TMPFILE" "$OUTFILE"
  fi
done < "$DEVICE"

echo "meteo-exporter: serial device closed, exiting" >&2
exit 1
