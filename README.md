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

**Переменные окружения** (пишутся инсталлятором в `/etc/default/meteo-exporter`,
можно править вручную и потом `systemctl restart meteo-exporter`):

- `METEO_DEVICE` (по умолчанию `/dev/ttyUSB0`)
- `METEO_BAUD` (по умолчанию `115200`)
- `METEO_TEXTFILE_DIR` (по умолчанию `/var/lib/prometheus/node-exporter`)
- `METEO_OUTFILE` (по умолчанию `$METEO_TEXTFILE_DIR/meteo.prom`)

**Установка:**

```
sudo make install
```

Перед установкой проверяет:
- что `prometheus-node-exporter` (или `node_exporter`/`node-exporter`) уже
  установлен и активен (`check-node-exporter`)
- что serial-устройство (`DEVICE`, по умолчанию `/dev/ttyUSB0`) присутствует,
  является character-устройством и доступно на чтение/запись (`check-tty`)

Затем создаёт `$METEO_TEXTFILE_DIR`, копирует скрипт в
`/usr/local/bin/meteo-exporter`, unit-файл в `/etc/systemd/system/`, пишет
`/etc/default/meteo-exporter` с текущими `DEVICE`/`BAUD`/`TEXTFILE_DIR`,
включает и запускает сервис.

Пути и устройство можно переопределить прямо при вызове, например:

```
sudo make install DEVICE=/dev/ttyUSB1 BAUD=115200
```

**Проверка, что данные реально идут:**

```
make check
```

Смотрит на метрику `meteo_last_reading_timestamp_seconds` в `.prom` файле и
проверяет, что последнее показание не старше `STALE_SECS` (по умолчанию 15
секунд — датчик шлёт данные раз в секунду). Никакого рестарта
`prometheus-node-exporter` для этого не требуется: textfile collector сам
перечитывает директорию с `.prom` файлами при каждом scrape'е.

**Удаление:**

```
sudo make uninstall
```

Останавливает и дизейблит сервис, удаляет unit-файл, бинарник,
`/etc/default/meteo-exporter` и `meteo.prom`.

## aprs-beacon

Headless APRS-точка (см. METEO-2): раз в `APRS_INTERVAL` секунд (по
умолчанию 600) читает `meteo.prom` и шлёт position+weather report пакет
в APRS-IS (`rotate.aprs2.ru:14580` по умолчанию) — без радио, чистый
интернет-клиент. Появляется на aprs.fi/aprs-map.info как погодная
станция. Реализация на stdlib (`socket`), без внешних Python-зависимостей.

Позывной, координаты и APRS-IS passcode — данные конкретного места и
пользователя, в репозиторий не коммитятся; передаются параметрами `make`
и оседают в `/etc/default/aprs-beacon` на самой машине.

**Установка (только раскладывает файлы, ничего не отправляет в эфир):**

```
sudo make aprs-install APRS_CALLSIGN=R2BLN-13 APRS_LAT=55.9328 APRS_LON=36.0184
```

Опционально: `APRS_SERVER` (по умолчанию `rotate.aprs2.ru:14580`),
`APRS_INTERVAL` (по умолчанию `600`), `APRS_COMMENT`, `APRS_PASSCODE`
(если не передан — считается скриптом от `APRS_CALLSIGN` на лету).

**Активация/деактивация** — отдельно от install/uninstall, потому что
именно этот шаг реально начинает публично транслировать координаты дачи
в сеть APRS-IS:

```
sudo make aprs-activate     # начать слать маяки
sudo make aprs-deactivate   # прекратить (конфиг и файлы остаются)
```

**Проверка, что маяк реально уходит:**

```
make aprs-check
```

Смотрит на файл `/var/lib/aprs-beacon/last-sent`, который скрипт
обновляет только при успешной отправке пакета в APRS-IS.

**Удаление** (останавливает, если ещё активен, и чистит всё, включая
`/etc/default/aprs-beacon`):

```
sudo make aprs-uninstall
```