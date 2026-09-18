"""Smoke-check: load PRISKLASSE, print today and tomorrow if published."""

from datetime import date

from script.client import PriceApi
from script.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    api = PriceApi(settings)
    print(f"prisklasse: {settings.price_area}")
    print(f"netselskab: {settings.netselskab_name} ({settings.netselskab_gln})")
    print(f"supplier: {settings.supplier_name} {settings.supplier_dkk_kwh} kr/kWh excl. VAT")
    today = date.today()
    _print_day(api, today)
    try:
        _print_day(api, today.fromordinal(today.toordinal() + 1))
    except Exception as exc:
        print(f"tomorrow: not available yet ({exc})")


def _print_day(api: PriceApi, day) -> None:
    hours = api.hours_for_day(day)
    cheapest = min(hours, key=lambda item: item.total_incl_vat)
    print(f"{day.isoformat()}: {len(hours)} hours")
    print(
        f"  cheapest {cheapest.local_hour:02d}:00  "
        f"{cheapest.total_incl_vat} kr/kWh inkl. moms  "
        f"(spot {cheapest.spot_dkk_kwh})"
    )


if __name__ == "__main__":
    main()
