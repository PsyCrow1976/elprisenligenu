# Python client

`script/` talks to two public APIs. No token is required.

## Layout

| Path | Role |
| --- | --- |
| `script/client.py` | `PriceApi` |
| `script/settings.py` | `PRISKLASSE` and charge GLNs |
| `script/models.py` | `SpotHour`, `ChargeBand`, `HourCost` |
| `script/exceptions.py` | `PriceError`, `ApiError`, `ConfigError` |

## Settings

`Settings.from_env()` reads:

| Env | Default | Meaning |
| --- | --- | --- |
| `PRISKLASSE` | `DK2` | `DK1` west of Storebælt, `DK2` east (Copenhagen) |
| `VAT_RATE` | `0.25` | Added on top of excl.-VAT totals |
| `NETSELSKAB_GLN` | `5790000705689` | Radius Elnet A/S |
| `NETSELSKAB_CHARGE_CODE` | `DT_C_01` | Household Nettarif C |
| `ENERGINET_GLN` | `5790000432752` | Energinet Systemansvar |
| `SUPPLIER_DKK_KWH` | `0` | Optional tillæg, kr/kWh excl. VAT |

## PriceApi

```python
from script import PriceApi

api = PriceApi.from_env()
hours = api.hours_for_day(date(2026, 9, 18))
charges = api.lookup_charges(date(2026, 9, 18))
```

- `spot_hours(day)` — JSON from `https://www.elprisenligenu.dk/api/v1/prices/YYYY/MM-DD_{DK1|DK2}.json`
- `hours_for_day(day)` — spot plus the three Datahub extras and the optional supplier tillæg
- `elafgift` / `energinet_system` / `energinet_transmission` / `netselskab_tariff` — the Datahub band that is valid on that date

Spot JSON is excl. moms and excl. afgifter. Datahub kWh prices are excl. moms. `HourCost.total_incl_vat` applies `VAT_RATE`.

If the spot API returns 15-minute records, they are averaged to clock hours.

Tomorrow’s file is typically published after 13:00 Copenhagen time. History on elprisenligenu.dk only goes back to 1 November 2022.
