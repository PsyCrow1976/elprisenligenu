# Examples

```bash
export PRISKLASSE=DK2
```

```python
from datetime import date
from script import PriceApi

api = PriceApi.from_env()
day = date(2026, 9, 18)
hours = api.hours_for_day(day)
for hour in hours:
    print(
        f"{hour.local_hour:02d}:00  "
        f"spot {hour.spot_dkk_kwh}  "
        f"staten {hour.staten_dkk_kwh}  "
        f"energinet {hour.energinet_dkk_kwh}  "
        f"net {hour.netselskab_dkk_kwh}  "
        f"total {hour.total_incl_vat} inkl. moms"
    )
```

```python
from datetime import date
from script import PriceApi

api = PriceApi.from_env()
bands = api.lookup_charges(date.today())
print(bands["staten"].prices if bands["staten"] else None)
print(bands["netselskab"].note, bands["netselskab"].prices[:6])
```

```bash
python3 -m script
```
