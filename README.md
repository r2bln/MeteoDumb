Метеостанция на минималках.

Оригинал - https://github.com/AlexGyver/MeteoClock

## Sensor.ino

Оригинальный скетч: BME280 + SSD1306 OLED (128x64, адрес 0x3C), показания температуры/влажности/давления выводятся на экран.

## SensorSerial.ino

Упрощённый вариант без экрана — просто читает BME280 и шлёт показания в Serial (115200 baud) раз в секунду. Пригодится когда под рукой только ESP32 + датчик без дисплея.

**Железо:**
- ESP32-D0WD dev board (USB-UART мост Silicon Labs CP210x, обычно `/dev/ttyUSB0`)
- BME280 по I2C: SDA=GPIO21, SCL=GPIO22
- Адрес модуля: **0x76** (китайские клоны почти всегда на этом адресе, а не на стоковом 0x77)

**Библиотеки (Library Manager):** `Adafruit BME280 Library` (подтянет `Adafruit Unified Sensor`).

**Arduino IDE:** Board = `ESP32 Dev Module`, Port = `/dev/ttyUSB0`.

Скетч пробует адреса 0x76 и 0x77 по очереди, так что менять исходники библиотеки (как раньше делали для Sensor.ino) не нужно.

## meteo-exporter

Демон на bash, который читает строки вида `T=19.56C  P=985.14hPa  H=63.07%` с
serial-порта (`SensorSerial.ino`) и поддерживает файл для textfile collector
`prometheus-node-exporter` в актуальном состоянии.

Порт открывается один раз на весь жизненный цикл процесса (а не на каждое
чтение), чтобы не дёргать DTR/RTS и не ресетить ESP32 лишний раз. При
пропадании устройства процесс завершается, а `systemd` (`Restart=always`)
перезапускает его.

**Метрики** (в `/var/lib/prometheus/node-exporter/meteo.prom` по умолчанию):

- `meteo_temperature_celsius`
- `meteo_humidity_percent`
- `meteo_pressure_pascals`
- `meteo_last_reading_timestamp_seconds` — unix-время последнего успешно
  распарсенного показания (для контроля устаревания данных)

**Переменные окружения** (можно задать в `/etc/default/meteo-exporter`):

- `METEO_DEVICE` (по умолчанию `/dev/ttyUSB0`)
- `METEO_BAUD` (по умолчанию `115200`)
- `METEO_TEXTFILE_DIR` (по умолчанию `/var/lib/prometheus/node-exporter`)
- `METEO_OUTFILE` (по умолчанию `$METEO_TEXTFILE_DIR/meteo.prom`)

**Установка:**

```
sudo make install
```

Проверяет, что `prometheus-node-exporter` (или `node_exporter`/`node-exporter`)
уже установлен и запущен, создаёт `$METEO_TEXTFILE_DIR`, копирует скрипт в
`/usr/local/bin/meteo-exporter` и unit-файл в `/etc/systemd/system/`, включает
и запускает сервис.

**Удаление:**

```
sudo make uninstall
```

Останавливает и дизейблит сервис, удаляет unit-файл, бинарник и `meteo.prom`.