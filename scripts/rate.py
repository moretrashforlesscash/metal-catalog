"""Курс валюты к тенге по Нацбанку РК (официальный, на дату).

Пример: python3 scripts/rate.py            → курс RUB на сегодня
        python3 scripts/rate.py RUB 2026-10-22
Курсы кэшируются в reference/rates.csv (история).
Официальный курс ниже реального курса оплаты (банк/платёжный агент берут спред),
поэтому к нему добавляется SPREAD_PCT из reference/pricing.json.
"""

import csv
import datetime as dt
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent.parent
CACHE = ROOT / "reference" / "rates.csv"
PRICING = ROOT / "reference" / "pricing.json"
URL = "https://nationalbank.kz/rss/get_rates.cfm?fdate={:%d.%m.%Y}"


def official(code="RUB", date=None):
    """Официальный курс: сколько ₸ за 1 единицу валюты."""
    date = date or dt.date.today()
    rows = list(csv.DictReader(open(CACHE, encoding="utf-8"))) if CACHE.exists() else []
    for r in rows:
        if r["date"] == date.isoformat() and r["code"] == code:
            return float(r["kzt"])
    with urllib.request.urlopen(URL.format(date), timeout=20) as resp:
        root = ET.fromstring(resp.read())
    for item in root.iter("item"):
        if item.findtext("title") == code:
            kzt = float(item.findtext("description")) / float(item.findtext("quant") or 1)
            break
    else:
        raise ValueError(f"Нацбанк не дал курс {code} на {date}")
    new = not CACHE.exists()
    with open(CACHE, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "code", "kzt"])
        w.writerow([date.isoformat(), code, kzt])
    return kzt


def effective(code="RUB", date=None):
    """Курс для расчёта: официальный + спред на конвертацию."""
    spread = json.loads(PRICING.read_text(encoding="utf-8"))["fx_spread_pct"] if PRICING.exists() else 0
    return official(code, date) * (1 + spread / 100), spread


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "RUB"
    date = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    off = official(code, date)
    eff, spread = effective(code, date)
    print(f"{code}: официальный {off} ₸, для расчёта {eff:.4f} ₸ (спред {spread}%)")
