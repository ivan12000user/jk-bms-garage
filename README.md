# JK BMS Garage

Конфигурация мониторинга гаражной LiFePO4 4S батареи через JK BMS
на Orange Pi Zero3.

## Архитектура

JK BMS
→ Bluetooth
→ BatMON
→ MQTT `ivan12000/garage/akb/...`
→ Home Assistant / Rapid SCADA

Дополнительно:

BatMON
→ локальный WebFileSink
→ `web/state.json`
→ `web/jk_log.csv`
→ `jk-web.service`
→ HTTP :8088

BLE должен опрашиваться только одним процессом.

## Основа

Upstream: fl4p/batmon-ha

Точный upstream commit находится в:

`upstream/base-commit.txt`

## Текущая конфигурация

- sample period: 20 s
- publish period: 20 s
- current sign: заряд `+`, разряд `-`
- BatMON HA Discovery отключён
- HA Discovery публикуется отдельным `publish_ha_short_battery.py`
- MQTT root: `ivan12000/garage/akb`

## Секреты

Настоящий `options.json` в GitHub не хранится.

Использовать:

`config/options.example.json`

## Восстановление

Сначала клонировать upstream BatMON на commit из
`upstream/base-commit.txt`, затем применить локальные файлы и patch.

## Web dashboard

Локальная страница:

`http://<orangepizero3>:8088/`

Архитектура:

`BmsSampler -> WebFileSink -> state.json / jk_log.csv -> jk-web.service`

Веб-сервис сам Bluetooth не опрашивает.

История по умолчанию хранится 72 часа.

Runtime-файлы `state.json` и `jk_log.csv` в Git не сохраняются.
