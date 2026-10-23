"""Теоретическая масса металлопроката.

Плотность стали 7850 кг/м³. Все размеры в мм, результат в кг/м
(для листа — кг/м²). Фактическая масса отличается от теоретической
из-за допусков проката (обычно ±3–8%).
"""

DENSITY = {  # кг/м³
    "steel": 7850,
    "stainless": 7900,  # AISI 304/321; 316 ≈ 7980
    "aluminium": 2700,
}


def _k(material):
    return DENSITY[material] / 1e6  # кг/м на мм²


def sheet(t, material="steel"):
    """Лист толщиной t, кг/м²."""
    return t * DENSITY[material] / 1000


def round_pipe(d, s, material="steel"):
    """Труба круглая: наружный диаметр d, стенка s (ГОСТ 10704/3262/8732)."""
    return 3.141592653589793 * (d - s) * s * _k(material)


def profile_pipe(a, b, s, material="steel"):
    """Труба профильная a×b×s по ГОСТ 30245 (с учётом скругления углов)."""
    return 2 * s * (a + b - 2.86 * s) * _k(material)


def round_bar(d, material="steel"):
    """Круг / арматура номинальным диаметром d (ГОСТ 2590, ГОСТ 34028)."""
    return 3.141592653589793 / 4 * d * d * _k(material)


def square_bar(a, material="steel"):
    """Квадрат a×a (ГОСТ 2591)."""
    return a * a * _k(material)


def strip(b, t, material="steel"):
    """Полоса b×t (ГОСТ 103)."""
    return b * t * _k(material)


if __name__ == "__main__":
    print("Лист 2 мм:", round(sheet(2), 2), "кг/м²")
    print("Труба 57×3.5:", round(round_pipe(57, 3.5), 3), "кг/м")
    print("Профиль 40×20×2:", round(profile_pipe(40, 20, 2), 3), "кг/м")
    print("Арматура d12:", round(round_bar(12), 3), "кг/м")


# ---- профили по таблицам ГОСТ (reference/weights/*.csv, извлечены из текстов стандартов 2026-10-23) ----
import csv as _csv
import functools as _ft
from pathlib import Path as _Path

_REF = _Path(__file__).parent.parent / "reference" / "weights"


@_ft.lru_cache(maxsize=None)
def _table(name):
    with open(_REF / name, encoding="utf-8") as fh:
        return list(_csv.DictReader(fh))


def hexagon(s, material="steel"):
    """Шестигранник «под ключ» s: площадь = √3/2·s²."""
    return 0.8660254 * s * s * _k(material)


def angle(a, b, t):
    """Уголок a×b×t. Равнополочный — по таблице ГОСТ 8509-93; неравнополочный — по формуле
    t·(a+b−t) плюс скругление (≈1%), точность ±2%."""
    if a == b:
        for r in _table("angle_8509.csv"):
            if float(r["b"]) == a and float(r["t"]) == t:
                return float(r["mass_kg_m"])
    return t * (a + b - t) * _k("steel") * 1.01


def channel(no, series="П"):
    """Швеллер по ГОСТ 8240-97. Серии П и У по массе совпадают (отличается уклон полок)."""
    key = f"{no:g}".replace(".", ",") + series
    for r in _table("channel_8240.csv"):
        if r["profile"] == key:
            return float(r["mass_kg_m"])
    return None


def bent_channel(h, b, t):
    """Швеллер гнутый h×b×t (ГОСТ 8278): развёртка t·(h+2b−2t), точность ±2%."""
    return t * (h + 2 * b - 2 * t) * _k("steel")


def ibeam(no, series=""):
    """Двутавр: «20Б1», «30Ш1» — ГОСТ 26020-83; без серии («20») — обычный ГОСТ 8239-89."""
    table, key = ("beam_26020.csv", f"{no:g}{series}") if series else ("beam_8239.csv", f"{no:g}")
    for r in _table(table):
        if r["profile"] == key:
            return float(r["mass_kg_m"])
    return None
