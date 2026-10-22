"""Стоимость доставки сборным грузом через калькулятор JetLogistic (jetlogistic.kz).

Пример: python3 scripts/delivery_jet.py Москва Алматы 1000 0.5
Это тот же запрос, что делает онлайн-калькулятор на их сайте (POST /ajax/calc.php).
Эндпоинт не документирован — может измениться; не долбить его массово.
Ответ: забор до терминала, магистраль, доставка от терминала до двери, доп.услуги (₸), срок (дни).
"""

import json
import sys
import urllib.parse
import urllib.request

URL = "https://jetlogistic.kz/ajax/calc.php"


def quote(city_from, city_to, weight_kg, volume_m3, cargo="МЕТАЛЛОПРОДУКЦИЯ"):
    data = urllib.parse.urlencode({
        "cityfrom": city_from, "cityto": city_to, "ves": weight_kg, "obm3": volume_m3,
        "mest": 1, "noAuth": 1, "NAME_PARAMETR2": cargo,
    }).encode()
    req = urllib.request.Request(URL, data=data, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        res = json.loads(resp.read().decode("utf-8-sig"))
    a = res.get("answer")
    if not res.get("success") or not isinstance(a, list) or not a[1].isdigit():
        raise ValueError(f"JetLogistic не посчитал {city_from} → {city_to}: {a}")
    pickup, line, door, extra = (int(x) for x in a[:4])
    return {"pickup": pickup, "line": line, "door": door, "extra": extra,
            "terminal_to": a[7], "days": a[13]}


if __name__ == "__main__":
    f, t, w, v = sys.argv[1:5]
    q = quote(f, t, float(w), float(v))
    total = q["pickup"] + q["line"] + q["door"] + q["extra"]
    print(f"{f} → {t}, {w} кг, {v} м³ (срок {q['days']} дн.)")
    print(f"  забор {q['pickup']:,} + магистраль {q['line']:,} + до двери {q['door']:,} + доп. {q['extra']:,}"
          f" = {total:,} ₸ ≈ {total / float(w):,.0f} ₸/кг".replace(",", " "))
    print(f"  только терминал–терминал: {q['line']:,} ₸ ≈ {q['line'] / float(w):,.0f} ₸/кг".replace(",", " "))
