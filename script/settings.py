"""Runtime settings from the environment."""

from __future__ import annotations

import os
from decimal import Decimal

from script.exceptions import ConfigError

PRICE_AREAS = ("DK1", "DK2")
DEFAULT_PRICE_AREA = "DK2"
DEFAULT_VAT_RATE = Decimal("0.25")
DEFAULT_NETSELSKAB_GLN = "5790000705689"  # Radius Elnet A/S (2700 Brønshøj)
DEFAULT_NETSELSKAB_NAME = "Radius Elnet A/S"
DEFAULT_NETSELSKAB_CHARGE_CODE = "DT_C_01"  # Nettarif C, typical household
DEFAULT_ENERGINET_GLN = "5790000432752"
# Andel Energi FlexEnergi tillæg ~14.58 øre/kWh inkl. moms → 0.11664 kr/kWh excl. moms.
DEFAULT_SUPPLIER_DKK_KWH = Decimal("0")
DEFAULT_SUPPLIER_NAME = "Andel Energi"


class Settings:
    """Holds price area and charge lookup settings."""

    def __init__(
        self,
        price_area: str,
        vat_rate: Decimal = DEFAULT_VAT_RATE,
        netselskab_gln: str = DEFAULT_NETSELSKAB_GLN,
        netselskab_name: str = DEFAULT_NETSELSKAB_NAME,
        netselskab_charge_code: str = DEFAULT_NETSELSKAB_CHARGE_CODE,
        energinet_gln: str = DEFAULT_ENERGINET_GLN,
        supplier_name: str = DEFAULT_SUPPLIER_NAME,
        supplier_dkk_kwh: Decimal = DEFAULT_SUPPLIER_DKK_KWH,
    ):
        area = (price_area or "").strip().upper()
        if area not in PRICE_AREAS:
            raise ConfigError(
                f"PRISKLASSE must be DK1 (west of Storebælt) or DK2 (east). Got {price_area!r}."
            )
        self.price_area = area
        self.vat_rate = vat_rate
        self.netselskab_gln = netselskab_gln.strip()
        self.netselskab_name = netselskab_name.strip() or DEFAULT_NETSELSKAB_NAME
        self.netselskab_charge_code = netselskab_charge_code.strip() or DEFAULT_NETSELSKAB_CHARGE_CODE
        self.energinet_gln = energinet_gln.strip() or DEFAULT_ENERGINET_GLN
        self.supplier_name = supplier_name.strip() or DEFAULT_SUPPLIER_NAME
        self.supplier_dkk_kwh = supplier_dkk_kwh

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from PRISKLASSE and optional charge overrides."""
        return cls(
            price_area=os.environ.get("PRISKLASSE", DEFAULT_PRICE_AREA),
            vat_rate=_decimal_env("VAT_RATE", DEFAULT_VAT_RATE),
            netselskab_gln=os.environ.get("NETSELSKAB_GLN", DEFAULT_NETSELSKAB_GLN),
            netselskab_name=os.environ.get("NETSELSKAB_NAME", DEFAULT_NETSELSKAB_NAME),
            netselskab_charge_code=os.environ.get(
                "NETSELSKAB_CHARGE_CODE", DEFAULT_NETSELSKAB_CHARGE_CODE
            ),
            energinet_gln=os.environ.get("ENERGINET_GLN", DEFAULT_ENERGINET_GLN),
            supplier_name=os.environ.get("SUPPLIER_NAME", DEFAULT_SUPPLIER_NAME),
            supplier_dkk_kwh=_decimal_env("SUPPLIER_DKK_KWH", DEFAULT_SUPPLIER_DKK_KWH),
        )


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return Decimal(raw.strip().replace(",", "."))
    except Exception as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from exc
