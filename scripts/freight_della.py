"""Рыночные ставки на перевозки по Казахстану с della.kz (реальные свежие сделки).

Пример: python3 scripts/freight_della.py
Забирает таблицы «Цены на грузоперевозки Казахстан — Казахстан» (20 т, 10 т, малотоннажные),
дописывает новые сделки в logistics/della_kz.csv и печатает медиану ₸/км по классам машин.
Запускать регулярно (раз в день) — база копится, медиана становится надёжнее.
"""

import csv
import datetime as dt
import html
import re
import statistics
import urllib.request
from pathlib import Path

URL = "https://www.della.kz/prices/local/"
OUT = Path(__file__).parent.parent / "logistics" / "della_kz.csv"
FIELDS = ["date", "route", "km", "cargo", "tons", "rate_kzt", "kzt_per_km", "class"]


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def num(s):
    return float(re.search(r"\d+(?:[.,]\d+)?", s.replace(" ", ""))[0].replace(",", "."))


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    year = dt.date.today().year
    rows = []
    for tr in re.findall(r'<tr class="row1">(.*?)</tr>', page, re.S):
        td = [clean(x) for x in re.findall(r"<td[^>]*>(.*?)(?=<td|$)", tr, re.S)]
        if len(td) < 6 or "км" not in td[2]:
            continue
        day, month = td[0].split(".")
        tons = re.search(r"(\d+(?:[.,]\d+)?)\s*т\b", td[3])
        t = num(tons[1]) if tons else 0
        cls = "фура 20 т" if t >= 15 else "средний 5–15 т" if t >= 5 else "малый до 5 т"
        rows.append({
            "date": f"{year}-{month}-{day}", "route": td[1].replace(" — ", " → "),
            "km": num(td[2]), "cargo": td[3], "tons": t,
            "rate_kzt": num(td[4]), "kzt_per_km": num(td[5]), "class": cls,
        })
    return rows


def save(rows):
    old = list(csv.DictReader(open(OUT, encoding="utf-8"))) if OUT.exists() else []
    seen = {(r["date"], r["route"], str(float(r["rate_kzt"]))) for r in old}
    new = [r for r in rows if (r["date"], r["route"], str(r["rate_kzt"])) not in seen]
    with open(OUT, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS)
        if not old:
            w.writeheader()
        w.writerows(new)
    return old + new, len(new)


def main():
    allrows, added = save(fetch())
    print(f"Della: +{added} новых сделок, всего в базе {len(allrows)}")
    by = {}
    for r in allrows:
        by.setdefault(r["class"], []).append(float(r["kzt_per_km"]))
    for cls, v in by.items():
        print(f"  {cls}: медиана {statistics.median(v):.0f} ₸/км (сделок {len(v)}, разброс {min(v):.0f}–{max(v):.0f})")


if __name__ == "__main__":
    main()
