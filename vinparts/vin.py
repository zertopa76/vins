"""Минимальный разбор VIN: марка и год. Код двигателя и модель по VIN определить нельзя
(для европейских машин VIN не содержит их в открытом виде), поэтому их указывают отдельно."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

# Коды изготовителя (первые 3 знака) для концерна VAG
WMI = {
    "WVW": "Volkswagen", "WVG": "Volkswagen", "WV1": "Volkswagen (коммерческие)",
    "WV2": "Volkswagen (коммерческие)", "WV3": "Volkswagen (грузовые)",
    "VWV": "Volkswagen (Испания)", "AAV": "Volkswagen (ЮАР)", "3VW": "Volkswagen (Мексика)",
    "1VW": "Volkswagen (США)", "9BW": "Volkswagen (Бразилия)", "WUA": "Audi (quattro GmbH)",
    "WAU": "Audi", "WA1": "Audi", "TRU": "Audi (Венгрия)", "TMB": "Škoda", "TMP": "Škoda",
    "VSS": "SEAT", "VS6": "SEAT",
}

_YEAR_CHARS = "ABCDEFGHJKLMNPRSTVWXY123456789"


@dataclass
class VinInfo:
    vin: str
    valid_format: bool
    make: str | None
    year: int | None
    note: str


def decode(vin: str, today: date | None = None) -> VinInfo:
    vin = re.sub(r"\s+", "", vin).upper()
    if not _VIN_RE.match(vin):
        return VinInfo(vin, False, None, None,
                       "VIN должен состоять из 17 знаков (латинские буквы без I, O, Q и цифры).")
    make = WMI.get(vin[:3])
    year = None
    idx = _YEAR_CHARS.find(vin[9])
    if idx >= 0:
        limit = (today or date.today()).year + 1
        candidates = [y for y in (1980 + idx, 2010 + idx) if y <= limit]
        year = max(candidates) if candidates else None
    note = ("Год взят из 10-го знака VIN, для европейских машин он не всегда совпадает с годом выпуска. "
            "Модель и код двигателя по VIN определить нельзя: укажите их отдельно.")
    return VinInfo(vin, True, make, year, note)
