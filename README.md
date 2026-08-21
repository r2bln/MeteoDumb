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