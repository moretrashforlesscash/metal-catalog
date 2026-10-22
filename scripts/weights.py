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
