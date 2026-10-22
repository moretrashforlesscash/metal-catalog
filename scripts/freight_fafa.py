"""Средняя рыночная ставка на фуру по маршруту с fa-fa.kz (биржа грузов KZ/СНГ, живые данные).

Пример: python3 scripts/freight_fafa.py Москва Алматы
fa-fa считает среднюю по размещённым заявкам. Отдаёт: расстояние, срок, ставку за 20 т (₸ и ₸/км)
и ступени по весу (1/2/5/10/20 т). Результат дописывается в logistics/fafa.csv (история).
"""

import csv
import datetime as dt
import html
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).parent.parent / "logistics" / "fafa.csv"
FIELDS = ["date", "from", "to", "km", "days", "t1", "t2", "t5", "t10", "t20", "kzt_per_km_20t"]
TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r",
               "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(city):
    return "".join(TR.get(c, c) for c in city.lower()).replace(" ", "-")


def quote(city_from, city_to):
    url = f"https://fa-fa.kz/stoimost_perevozki/{slug(city_from)}-{slug(city_to)}/"
    # сайт отдаёт 403 питоновскому urllib, а curl пропускает
    raw = subprocess.run(["curl", "-sS", "-f", "-m", "30", "-A", "Mozilla/5.0", url],
                         capture_output=True, check=True).stdout.decode("cp1251", "ignore")
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
    m = re.search(r"Расстояние ([\d.]+) км.*?срок доставки (\d+) дн.*?Средняя стоимость ([\d.]+) тенге, (\d+) тг/км", text)
    if not m:
        raise ValueError(f"fa-fa: нет данных по маршруту {city_from} → {city_to} ({url})")
    tiers = {int(t): int(p) for t, p in re.findall(r'"(\d+) т\.?",(\d+)', raw)}
    return {
        "date": dt.date.today().isoformat(), "from": city_from, "to": city_to,
        "km": int(m[1].replace(".", "")), "days": int(m[2]),
        **{f"t{t}": tiers.get(t, "") for t in (1, 2, 5, 10, 20)},
        "t20": tiers.get(20) or int(m[3].replace(".", "")), "kzt_per_km_20t": int(m[4]),
    }


def save(q):
    new = not OUT.exists()
    with open(OUT, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS)
        if new:
            w.writeheader()
        w.writerow(q)


def fmt(n):
    return f"{n:,}".replace(",", " ")


if __name__ == "__main__":
    q = quote(sys.argv[1], sys.argv[2])
    save(q)
    tiers = ", ".join(f"{t} т: {fmt(q[f't{t}'])} ₸" for t in (1, 2, 5, 10, 20) if q[f"t{t}"])
    print(f"{q['from']} → {q['to']}: {fmt(q['km'])} км, ~{q['days']} дн., фура 20 т ≈ {fmt(q['t20'])} ₸ "
          f"({q['kzt_per_km_20t']} ₸/км, {q['t20'] / 20000:.0f} ₸/кг)")
    print(f"  по весу (мало заявок — шумно, надёжна только 20 т): {tiers}")
