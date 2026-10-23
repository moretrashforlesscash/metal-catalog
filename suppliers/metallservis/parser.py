"""Парсер прайсов «Металл Сервис» (mc.ru) — общий прайс, архив из 10 xls.

Раскладка каждого xls одинаковая:
- строки 0–2: контакты и «Прайс-лист от ДД.ММ.ГГГГ ЧЧ:ММ»;
- лист разбит на печатные страницы по 72 строки (horizontal_page_breaks);
- на странице две колонки-«газеты»: A–D и F–I (наименование, размер, ед.изм, цена).
  Читать надо так: левая колонка страницы сверху вниз, потом правая, потом следующая страница;
- строка с одним текстом — заголовок раздела (за ним идёт строка-шапка «...| Ед.изм | Цена»);
- строка без наименования и цены, но с размерами — продолжение списка размеров предыдущей позиции;
- «10 ; 12; 14» в размере — несколько размеров по одной цене.

Запуск: python3 suppliers/metallservis/parser.py suppliers/metallservis/raw/2026-10-22
Результат: catalog/metallservis.csv
"""

import csv
import re
import sys
from pathlib import Path

import xlrd

SUPPLIER = "Металл Сервис"
COLUMNS = [(0, 1, 2, 3), (5, 6, 7, 8)]  # наименование, размер, ед.изм, цена
PAGE = 72
FIELDS = ["supplier", "warehouse", "price_date", "file", "title", "section", "name",
          "size_label", "size", "unit", "price_rub", "vat_included", "src"]


def text(cell):
    v = cell.value
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def number(s):
    s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def split_sizes(s):
    sizes = [x.strip().replace(",", ".") for x in s.split(";") if x.strip()]
    return list(dict.fromkeys(sizes))


def price_date(sheet):
    for r in range(min(6, sheet.nrows)):
        for c in sheet.row(r):
            m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text(c))
            if m:
                return f"{m[3]}-{m[2]}-{m[1]}"
    return ""


def cells_stream(sheet):
    """Ячейки в порядке чтения: страница → левая колонка → правая колонка."""
    breaks = [0] + [b[0] for b in sheet.horizontal_page_breaks] + [sheet.nrows]
    for start, end in zip(breaks, breaks[1:]):
        for cols in COLUMNS:
            for r in range(max(start, 3), min(end, sheet.nrows)):
                row = sheet.row(r)
                vals = [text(row[c]) if c < len(row) else "" for c in cols]
                if any(vals):
                    yield r, cols[0], vals


def parse_file(path, warehouse="Москва"):
    sheet = xlrd.open_workbook(path, formatting_info=True).sheet_by_index(0)
    date = price_date(sheet)
    title = section = size_label = ""
    last_single = ""
    prev = None
    rows = []

    def emit(item, sizes):
        seen = item.setdefault("_sizes", set())
        for size in sizes or [""]:
            if size not in seen:
                seen.add(size)
                rows.append({k: v for k, v in item.items() if k != "_sizes"} | {"size": size})

    for r, c, (name, size, unit, price) in cells_stream(sheet):
        if price == "Цена" or unit == "Ед.изм":
            section = last_single.replace("(продолжение)", "").strip()
            size_label = size
            prev = None
            continue
        if name and not (size or unit or price):
            if not title:
                title = name
            last_single = name
            continue
        p = number(price)
        if p is None:
            if prev and not name and size and not unit:
                emit(prev, split_sizes(size))
            continue
        item = {
            "supplier": SUPPLIER, "warehouse": warehouse, "price_date": date, "file": path.name,
            "title": title, "section": section,
            "name": name or (prev["name"] if prev else section),
            "size_label": size_label, "unit": unit, "price_rub": p,
            "vat_included": "true", "src": f"{path.name}:{r + 1}:{'AF'[c > 0]}",
        }
        emit(item, split_sizes(size))
        prev = item
    return rows


def main(raw_dir, out="catalog/metallservis.csv", warehouse="Москва"):
    """Все xls из папки → один каталог склада (Москва — общий прайс из 10 файлов, филиал — свой файл)."""
    rows = []
    for f in sorted(Path(raw_dir).glob("*.xls")):
        part = parse_file(f, warehouse)
        print(f"{f.name}: {len(part)} позиций")
        rows += part
    Path(out).parent.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Итого {len(rows)} позиций → {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
