#include <Wire.h>
#include <Adafruit_BME280.h>

Adafruit_BME280 bme;

void setup() {
  Serial.begin(115200);
  while (!Serial) {}

  if (!bme.begin(0x76) && !bme.begin(0x77)) {
    Serial.println("BME280 не найден, проверь подключение/адрес");
    while (1) delay(1000);
  }
}

void loop() {
  Serial.print("T=");
  Serial.print(bme.readTemperature());
  Serial.print("C  P=");
  Serial.print(bme.readPressure() / 100.0F);
  Serial.print("hPa  H=");
  Serial.print(bme.readHumidity());
  Serial.println("%");

  delay(1000);
}
