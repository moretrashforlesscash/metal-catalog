"""Поиск позиции по каталогу.

Пример: python3 scripts/find.py "труба проф 40х20х2"
Все числа из запроса должны найтись в наименовании/размере позиции,
слова — в разделе/наименовании (по началу слова, с синонимами).
Для труб, листа, круга и арматуры добавляется теоретическая масса и цена за метр.
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import weights  # noqa: E402

CATALOG = Path(__file__).parent.parent / "catalog"
SYNONYMS = {
    "проф": ["прямоуг", "квадрат"],
    "профиль": ["прямоуг", "квадрат"],
    "профильная": ["прямоуг", "квадрат"],
    "двутавр": ["балк"],
    "нерж": ["нерж", "aisi"],
    "оцинк": ["оцинк", "zn"],
    "а500": ["а500", "400;500"],
    "а500с": ["а500с", "400;500"],
}
STOP = {"мм", "м", "т", "и", "на", "по"}


def norm(s):
    s = s.lower().replace("ё", "е")
    s = re.sub(r"a(?=\d)", "а", s)  # латинская A500 → кириллическая А500
    s = re.sub(r"(?<=\d)\s*[xх×*]\s*(?=\d)", " ", s)  # 40х20х2 → 40 20 2
    return s.replace(",", ".")


def numbers(s):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]


def mass_kg_m(r):
    """Теоретическая масса, кг/м (лист — кг/м²); None, если формулы нет."""
    sec, name = r["section"].upper(), r["name"]
    try:
        size = float(r["size"])
    except ValueError:
        return None
    dims = numbers(norm(name))
    if "НЕРЖ" in sec or "АЛЮМ" in sec or "МЕД" in sec or "ЛАТУН" in sec:
        return None
    if ("ПРЯМОУГ" in sec or "КВАДРАТ" in sec) and "ТРУБ" in sec and len(dims) >= 2:
        return weights.profile_pipe(dims[0], dims[1], size)
    if "ТРУБ" in sec and "ВОДОГАЗ" not in sec and "ОВАЛ" not in sec and dims:
        return weights.round_pipe(dims[0], size)
    if "ЛИСТ" in sec and "РИФЛ" not in sec and "ПРОСЕЧ" not in sec:
        return weights.sheet(size)
    if any(k in sec for k in ("АРМАТУР", "КРУГ", "КАТАНК")):
        return weights.round_bar(size)
    return None


def load():
    rows = []
    for f in sorted(CATALOG.glob("*.csv")):
        rows += list(csv.DictReader(open(f, encoding="utf-8")))
    return rows


def match(r, words, nums):
    hay = norm(f"{r['section']} {r['name']} {r['size']}")
    hay += " " + hay.replace(" ", "")
    for w in words:
        alts = SYNONYMS.get(w, [w if re.search(r"\d", w) or len(w) < 5 else w[:4]])
        if not any(a in hay for a in alts):
            return False
    have = numbers(norm(r["name"])) + numbers(r["size"])
    for n in nums:
        if n in have:
            have.remove(n)
        else:
            return False
    return True


def find(query, limit=30):
    nums, words = [], []
    for t in re.findall(r"[a-zа-я0-9.]+", norm(query)):
        if re.fullmatch(r"\d+(\.\d+)?", t):
            nums.append(float(t))
        elif m := re.fullmatch(r"(\d+)([пуб])", t):  # 12П/12У: серии в xls нет, ищем по номеру
            nums.append(float(m[1]))
        elif t not in STOP and len(t) > 1:
            words.append(t)
    hits = [r for r in load() if float(r["price_rub"]) > 0 and match(r, words, nums)]
    hits.sort(key=lambda r: (bool(re.search(r"неконд|уценк", r["name"].lower())), float(r["price_rub"])))
    return hits[:limit], len(hits)


def main():
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    query = " ".join(sys.argv[1:])
    hits, total = find(query)
    print(f"«{query}»: найдено {total}" + (f", показаны {len(hits)} самых дешёвых" if total > len(hits) else ""))
    for r in hits:
        price = float(r["price_rub"])
        line = (f"{r['price_rub']:>10} ₽/{r['unit']:<7} | {r['section']} | {r['name']} | "
                f"{r['size_label']} {r['size']}")
        m = mass_kg_m(r)
        if m and r["unit"] in ("т", "теор.т"):
            per = "м²" if "ЛИСТ" in r["section"].upper() else "м"
            line += f" | {m:.3f} кг/{per} ≈ {price * m / 1000:,.0f} ₽/{per}".replace(",", " ")
        print(line + f" | {r['supplier']} {r['price_date']} [{r['src']}]")


if __name__ == "__main__":
    main()
