# Elprisen lige nu

Private Python app for Danish **hourly electricity prices**. It stores day-ahead spot plus the three extra kWh costs that sit on top of spot, so each hour has a full consumer-style total.

Spot comes from the open [elprisenligenu.dk API](https://www.elprisenligenu.dk/elpris-api) (`PRISKLASSE` = `DK1` or `DK2`). Extra charges come from Energinet [DatahubPricelist](https://www.energidataservice.dk/tso-electricity/DatahubPricelist). Neither API needs a key.

## What it does

- Pulls hourly (or 15-minute averaged to hourly) day-ahead prices for one price area
- Looks up **staten** (elafgift), **Energinet** (system + transmission), and **netselskab** (grid tariff C) for that date
- Adds an optional supplier kWh tillæg (Andel Energi is not in Datahub)
- Stores every hour in PostgreSQL for later use
- FastHTML UI: years / months / days / hours, plus a settings page for the extras

Defaults match **2700 Brønshøj**: `DK2`, Radius Elnet (`5790000705689`, Nettarif C `DT_C_01`), Andel Energi as supplier name.

## Hourly cost

All stored kWh amounts are **excl. VAT**. The UI also shows inkl. moms at 25%.

| Part | Source | 2700 Brønshøj notes (2026) |
| --- | --- | --- |
| Spot | elprisenligenu.dk | Varies by hour. No moms/afgifter in the JSON. |
| Staten | Datahub `Elafgift` | 0.008 kr/kWh excl. VAT (1 øre inkl. moms) in 2026–2027 |
| Energinet | Datahub `Systemtarif` + `Transmissions nettarif` | 0.072 + 0.043 = 0.115 kr/kWh excl. VAT in 2026 |
| Netselskab | Datahub Radius `DT_C_01` | Time-of-use; summer 2026 about 0.106 / 0.159 / 0.414 kr/kWh excl. VAT |
| Supplier tillæg | env / settings page | Optional. Andel FlexEnergi is roughly 0.11664 kr/kWh excl. VAT |

Fixed monthly fees (Andel abonnement, Radius netabonnement) are **not** in the hourly kWh price.

## Requirements

- Python 3
- `PRISKLASSE` set to `DK1` or `DK2`
- PostgreSQL for the web app (existing server, same idea as [eloverblick](https://github.com/PsyCrow1976/eloverblick))

```bash
export PRISKLASSE=DK2
python3 -m script
python3 -m web
```

Python code lives in `script/`. Class docs: [script.md](script.md). Copy-paste: [example.md](example.md). Web UI: [web.md](web.md). Unraid: [deploy.md](deploy.md).

## Status

Version `0.0.1`. See [CHANGELOG.md](CHANGELOG.md).
