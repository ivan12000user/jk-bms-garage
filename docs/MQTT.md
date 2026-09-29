# MQTT

Рабочий корневой префикс:

`ivan12000/garage/akb/`

Основные топики:

- `soc/total_voltage` — напряжение АКБ, V
- `soc/current` — ток, A
- `soc/power` — мощность, W
- `soc/soc_percent` — SOC, %
- `soc/balance_current` — ток балансировки, A
- `soc/capacity` — номинальная ёмкость, Ah
- `mosfet_status/capacity_ah` — остаток, Ah
- `temperatures/1` — температура T1
- `temperatures/2` — температура T2
- `mosfet_status/temperature` — температура BMS
- `cell_voltages/1..4` — напряжения ячеек
- `cell_voltages/min`
- `cell_voltages/max`
- `cell_voltages/delta`
- `bms/uptime`

## Знак тока

В рабочей конфигурации `invert_current=true`.

- `+` = заряд
- `-` = разряд

Этот знак одинаков для MQTT, Home Assistant, Rapid SCADA
и локальной веб-страницы.
