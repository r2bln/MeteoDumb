# METEO-2: Headless APRS-маяк (погодный отчёт в APRS-IS)

**Статус: Open**

Хочется, чтобы станция на wakkanai была видна как погодная станция на
aprs.fi / aprs-map.info — по образцу
https://aprs-map.info/views/overview.php?id=845&imperialUnits=0

Это **headless**-точка: без радио и передатчика, чистый клиент APRS-IS
(интернет) — периодически шлёт position+weather report пакет в сеть
APRS-IS, дальше его подхватывают агрегаторы вроде aprs.fi/aprs-map.info.

## Источник данных

`http://localhost:9100/metrics` (тот же textfile collector, что и в
METEO-1) — метрики `meteo_temperature_celsius`, `meteo_humidity_percent`,
`meteo_pressure_pascals`. Ветра/осадков нет (нет датчиков), эти поля в
пакете идут как unknown (`.../...g...`) — это нормальная часть спецификации
APRS weather report.

## Скрипт-маяк

Python-скрипт (`aprs-beacon.py` или похоже), раз в `BEACON_INTERVAL`
(по умолчанию 600с/10мин):

1. Забирает `meteo_temperature_celsius`/`humidity`/`pressure` из
   `/metrics` (или сразу из `.prom`-файла — не принципиально)
2. Конвертирует в единицы APRS weather report (температура → °F, давление
   → десятые доли мбар, влажность → 2 цифры, `00` = 100%)
3. Собирает пакет вида
   `CALLSIGN>APRS,TCPIP*:!LAT/LON_.../...g...tTTThHHbBBBBB`
4. Коннектится к APRS-IS серверу (`rotate.aprs2.ru:14580` по умолчанию),
   логинится позывным и APRS-IS passcode (детерминированный хэш от базового
   позывного, публичный алгоритм — не требует регистрации/SMS), шлёт пакет

Реализовано (`aprs-beacon.py`) на чистом stdlib (`socket`) — без `aprslib`
и без pip-зависимостей, протокол логина/пакета там тривиальный и не стоит
тащить внешнюю библиотеку ради него. Passcode по умолчанию считается самим
скриптом от `APRS_CALLSIGN` каждый запуск (не хранится и не передаётся).

## Конфигурация — НЕ коммитить в репозиторий

Репозиторий публичный (`github.com/r2bln/MeteoDumb`). Позывной+SSID,
координаты дачи и APRS-IS passcode — это данные конкретного пользователя
и конкретного места, в код/git они не зашиваются. По аналогии с
`meteo-exporter` — инсталлятор пишет их в `/etc/default/aprs-beacon`
(на машине, не в репо), значения передаются параметрами `make`:

```
sudo make aprs-install APRS_CALLSIGN=R2BLN-13 APRS_LAT=55.1234 APRS_LON=37.5678 [APRS_PASSCODE=...] [APRS_SERVER=rotate.aprs2.ru:14580] [APRS_INTERVAL=600]
```

Если `APRS_PASSCODE` не передан — инсталлятор считает его сам из
базовой части позывного (без `-SSID`) по стандартному алгоритму, чтобы
не пришлось вычислять руками.

## Install vs Activate — разделить

В отличие от `meteo-exporter` (который безобиден и должен работать сразу
после `make install`), у этого маяка `install` и реальный запуск —
**разные шаги**:

- `make aprs-install` — кладёт скрипт, зависимости, unit/timer,
  `/etc/default/aprs-beacon` с конфигом. **Не** делает `systemctl enable
  --now`. Ничего не уходит в эфир.
- `make aprs-activate` — `systemctl enable --now` на timer/service:
  маяк начинает реально слать позицию дачи в публичную сеть APRS-IS.
- `make aprs-deactivate` — `systemctl disable --now`: маяк перестаёт
  слать, но файлы/конфиг остаются на месте (можно снова `activate` без
  повторного `install`).
- `make aprs-uninstall` — как `meteo-exporter`: подразумевает
  `aprs-deactivate` + чистит файлы, unit, `/etc/default/aprs-beacon`.

Причина разделения: `install` — обратимая, безопасная подготовка;
`activate` — момент, когда точные координаты дачи становятся публично
видны на aprs.fi/aprs-map.info, это должно быть отдельным осознанным
действием, а не побочным эффектом установки.

## Проверка

`make aprs-check` — по аналогии с `make check` в METEO-1: смотрит, что
маяк реально недавно отправлял пакет (например, пишет timestamp
последней успешной отправки в стейт-файл и проверяет его свежесть), а
не просто что systemd-таймер существует.

## Реализовано

`aprs-beacon.py`, `systemd/aprs-beacon.{service,timer}`, таргеты в
`Makefile` (`aprs-install`/`aprs-activate`/`aprs-deactivate`/
`aprs-uninstall`/`aprs-check`). Протестировано локально на реальных
данных с `wakkanai.ts.0x1b.cc:9100/metrics` (парсинг + сборка пакета) —
`R2BLN-13>APRS,TCPIP*:!5555.97N/03601.11E_.../...g...t065h65b09846...`.
Ещё не разворачивалось на самой машине (`make aprs-install`/`activate`
на wakkanai) и не подтверждено появление станции на aprs.fi/aprs-map.info.

## Открытые вопросы

- Позывной/SSID (`R2BLN-13`) и координаты дачи подтверждены в переписке
  — координаты в код/репозиторий не заносились (см. выше), передаются
  на хосте как параметр `make aprs-install`.
- Интервал маяка (10 мин, `OnUnitActiveSec=600` в таймере) — дефолт по
  конвенции APRS для стационарных погодных станций, переопределяется
  `APRS_INTERVAL=` при установке.
