// адрес BME280 жёстко задан в файле библиотеки Adafruit_BME280.h
// стоковый адрес был 0x77, у китайского модуля адрес 0x76.
// Так что если юзаете НЕ библиотеку из архива - не забудьте поменять

// если дисплей не заводится - поменяйте адрес (строка 54)

// lcd
#include <LiquidCrystal.h>

// Задаём имя пинов дисплея
constexpr uint8_t PIN_RS = 6;
constexpr uint8_t PIN_EN = 7;
constexpr uint8_t PIN_DB4 = 8;
constexpr uint8_t PIN_DB5 = 9;
constexpr uint8_t PIN_DB6 = 10;
constexpr uint8_t PIN_DB7 = 11;

LiquidCrystal lcd(PIN_RS, PIN_EN, PIN_DB4, PIN_DB5, PIN_DB6, PIN_DB7);

// sensor
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#define SEALEVELPRESSURE_HPA (1013.25)
Adafruit_BME280 bme;

float dispTemp, dispHum, dispPres = 0;

void readSensors() {
  bme.takeForcedMeasurement();
  dispTemp = bme.readTemperature();
  dispHum = bme.readHumidity();
  dispPres = (float)bme.readPressure() * 0.00750062;
 
  // Устанавливаем размер экрана
  // Количество столбцов и строк
  lcd.begin(16, 2);
  // Устанавливаем курсор в колонку 0 и строку 0
  lcd.setCursor(0, 0);
  // Печатаем первую строку
  lcd.print("t" + String(dispTemp) + "C h" + String(dispHum) + "%");
  // Устанавливаем курсор в колонку 0 и строку 1
  lcd.setCursor(0, 1);
  // Печатаем вторую строку
  lcd.print("pr " + String(dispPres) + "mm/hg");
}

void setup() {
  // put your setup code here, to run once:
  bme.begin(&Wire);
  bme.setSampling(Adafruit_BME280::MODE_FORCED,
                  Adafruit_BME280::SAMPLING_X1, // temperature
                  Adafruit_BME280::SAMPLING_X1, // pressure
                  Adafruit_BME280::SAMPLING_X1, // humidity
                  Adafruit_BME280::FILTER_OFF   );

  readSensors();
}

void loop() {
  // put your main code here, to run repeatedly:
  readSensors();
  delay(1000);
}
