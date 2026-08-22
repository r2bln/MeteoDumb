# METEO-1: systemctl module установка и экспорт

**Статус: Done (2026-08-22)**

Реализовано: `meteo-exporter.sh`, `systemd/meteo-exporter.service`, `Makefile`
(`install`/`uninstall`/`check`/`check-tty`/`check-node-exporter`). Развёрнуто и
проверено на боевой машине (wakkanai): `make check` показывает свежие
показания, `curl localhost:9100/metrics | grep ^meteo_` отдаёт
`meteo_temperature_celsius`, `meteo_humidity_percent`, `meteo_pressure_pascals`,
`meteo_last_reading_timestamp_seconds`.

В этом репозитории необходимо реализовать скрипт получения данных с рудиментарной метеостанции - датчика из
SensorSerial.ino который бы получал данные следующим образом

```
sudo stty -F /dev/ttyUSB0  115200 raw -echo && sudo cat /dev/ttyUSB0
```

Ответ выглядит следующим образом 

```
T=19.56C  P=985.14hPa  H=63.07%
T=19.56C  P=985.16hPa  H=63.10%
```

Далее эти данные необходимо сложить в файл чтобы `prometheus-node-exporter` с помощью textfile collector смог
их подцепить и заэкспортить.

У этого скрипта должен быть 

- systemd модуль который мониторит и поддерживает его в рабочем состоянии 
- make install инсталлятор который:
  - проверяет наличие и работу `prometheus-node-exporter`
  - проверяет доступ к serial-устройству (tty) перед установкой
  - создаёт файлы и директории, копирует модули
- make uninstall который чистит за собой - стопает и дизейблит модули, чистит файлы и директории
- отдельная команда (`make check`) для проверки того, что экспортёр реально
  получает данные с датчика (свежий `.prom` файл), а не просто запущен

Примечание: `prometheus-node-exporter` рестартовать не нужно - textfile
collector перечитывает директорию с `.prom` файлами при каждом scrape'е сам.
