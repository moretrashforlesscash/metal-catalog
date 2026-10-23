"""Поиск позиции по каталогу.

Пример: python3 scripts/find.py "труба проф 40х20х2"
Все числа из запроса должны найтись в наименовании/размере позиции,
слова — в разделе/наименовании (по началу слова, с синонимами).
Для труб, листа, круга и арматуры добавляется теоретическая масса и цена за метр.
"""

import csv
import difflib
import functools
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
    "квадратка": ["квадрат"],
    "прямоугольная": ["прямоуг"],
    "профнастил": ["профнаст"],
    "нерж": ["нерж", "aisi"],
    "оцинк": ["оцинк", "zn"],
    "а500": ["а500", "400;500"],
    "а500с": ["а500с", "400;500"],
    "квадратка": ["трубы электросварные квадрат"],
    "горячекатаный": ["г/к"], "горячекатанный": ["г/к"], "гк": ["г/к"],
    "холоднокатаный": ["х/к"], "холоднокатанный": ["х/к"], "хк": ["х/к"],
    "оцинкованный": ["оцинк", "zn"], "оцинкованная": ["оцинк", "zn"], "оцинковка": ["оцинк", "zn"],
    "нержавейка": ["нерж", "aisi"], "нержавеющий": ["нерж", "aisi"], "нержавеющая": ["нерж", "aisi"],
    "бесшовная": ["г/д", "х/д"], "бесшовка": ["г/д", "х/д"],
    "электросварная": ["электросвар"], "эсв": ["электросвар"],
    "вгп": ["водогаз"], "водогазопроводная": ["водогаз"],
    "рифленый": ["рифл"], "рифленка": ["рифл"], "просечка": ["просеч"], "пвл": ["просеч"],
    "арм": ["арматур"], "арматурка": ["арматур"],
    "шестигранник": ["шестигран"],
}
# слова без смысла для поиска («круглая труба» — в прайсе просто «трубы»)
STOP = {"мм", "м", "т", "и", "на", "по", "круглая", "круглый", "стальная", "стальной", "сталь", "металл",
        "цена", "цены", "сколько", "стоит", "нужно", "нужна", "нужен", "марка", "размер", "толщина", "стенка",
        "диаметр", "мерная", "немерная", "длина", "шт", "штук", "тонн", "тн", "кг", "до", "в", "для"}


def norm(s):
    s = s.lower().replace("ё", "е")
    s = re.sub(r"a(?=\d)", "а", s)  # латинская A500 → кириллическая А500
    s = re.sub(r"(?<=\d)\s*[xх×*]\s*(?=\d)", " ", s)  # 40х20х2 → 40 20 2
    return s.replace(",", ".")


def numbers(s):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]


def mass_kg_m(r):
    """Теоретическая масса, кг/м (лист — кг/м²); None, если формулы/таблицы нет."""
    sec, name = r["section"].upper(), r["name"]
    dims = numbers(norm(dims_text(name)))
    try:
        size = float(r["size"])
    except ValueError:
        size = None
    if "НЕРЖ" in sec or "АЛЮМ" in sec or "МЕД" in sec or "ЛАТУН" in sec:
        return None
    if "ДВУТАВР" in sec or "БАЛК" in sec:
        return weights.ibeam(dims[0], r["size"].strip()) if dims else None
    if "ШВЕЛЛЕР" in sec and "ГНУТ" not in sec:
        return weights.channel(dims[0]) if dims else None
    if size is None:
        return None
    if "ШВЕЛЛЕР" in sec and len(dims) >= 2:
        return weights.bent_channel(dims[0], dims[1], size)
    if "УГОЛОК" in sec and dims:
        return weights.angle(dims[0], dims[1] if len(dims) > 1 else dims[0], size)
    if ("ПРЯМОУГ" in sec or "КВАДРАТ" in sec) and "ТРУБ" in sec and len(dims) >= 2:
        return weights.profile_pipe(dims[0], dims[1], size)
    if "КВАДРАТ" in sec and "ТРУБ" in sec and dims:  # в прайсе квадратная труба — одна сторона: «40» = 40×40
        return weights.profile_pipe(dims[0], dims[0], size)
    if "ТРУБ" in sec and "ВОДОГАЗ" not in sec and "ОВАЛ" not in sec and dims:
        return weights.round_pipe(dims[0], size)
    if "ЛИСТ" in sec and "РИФЛ" not in sec and "ПРОСЕЧ" not in sec:
        return weights.sheet(size)
    if "ПОЛОСА" in sec and dims:
        return weights.strip(dims[0], size)
    if "ШЕСТИГРАН" in sec:
        return weights.hexagon(size)
    if "КВАДРАТ" in sec:
        return weights.square_bar(size)
    if any(k in sec for k in ("АРМАТУР", "КРУГ", "КАТАНК")):
        return weights.round_bar(size)
    return None


def load():
    rows = []
    for f in sorted(CATALOG.glob("*.csv")):
        rows += list(csv.DictReader(open(f, encoding="utf-8")))
    return rows


GRADE = re.compile(
    r"\b(?:ст|сталь)\s*\d+\w*"            # Ст3, Ст20, Ст3сп
    r"|\baisi\s*\d+\w*"                   # AISI 304
    r"|\(\s*\d+х\d+[^)]*\)"                 # (12Х17), (08Х18Н10) — марка в скобках
    r"|\b\d+х\d+н\d+\w*"                   # 12Х18Н10Т, 08Х18Н10
    r"|\b\d+х[а-я]{2,}\w*"                  # 30ХГСА, 40ХН
    r"|\b\d+[а-фц-я][а-я\d]*"                # 09Г2С, 10ХСНД (буква не «х» сразу после цифр)
    r"|\b\d+(?:[.,]\d+)?\s*м(?![мa-zа-я])"  # «12м», «6 м» — длина, не размер
    r"|к\.п\.\s*\d+|а\d{3}(?:;\d{3})?")    # класс прочности, А400;500


def dims_text(name):
    """Название без марок стали и длин — чтобы «20» из «Ст20» не считалось размером."""
    return GRADE.sub(" ", name.lower().replace("ё", "е"))


@functools.lru_cache(maxsize=1)
def vocab():
    """Слова из названий разделов и позиций — для исправления опечаток («армотура» → «арматура»)."""
    words = set()
    for r in load():
        words.update(re.findall(r"[а-яa-z]{4,}", norm(f"{r['section']} {r['name']}")))
    return sorted(words)


def fix_word(w):
    if w in SYNONYMS or re.search(r"\d", w) or len(w) < 5 or any(v.startswith(w[:4]) for v in vocab()):
        return w
    close = difflib.get_close_matches(w, vocab(), n=1, cutoff=0.75)
    return close[0] if close else w


def match(r, words, nums):
    hay = norm(f"{r['section']} {r['name']} {r['size']}")
    hay += " " + hay.replace(" ", "")
    for w in words:
        if w.startswith("проф") and w not in SYNONYMS:  # профтруба, профтрубы, профильной...
            w = "проф"
        alts = SYNONYMS.get(w, [w if re.search(r"\d", w) or len(w) < 5 else w[:4]])
        if not any(a in hay for a in alts):
            return False
    have = numbers(norm(dims_text(r["name"]))) + numbers(r["size"])
    if "КВАДРАТ" in r["section"].upper() and "ТРУБ" in r["section"].upper() and have:
        have.insert(0, have[0])  # «40» в квадратной трубе = 40×40, чтобы находилось «40х40х2»
    for n in nums:
        if n in have:
            have.remove(n)
        else:
            return False
    return True


def parse_query(query):
    """Запрос → (числа, слова). Понимает 40*20*2, 40 на 20 на 2, 2мм, ф57, Ø57, d12, №12, 12П."""
    q = norm(query)
    q = re.sub(r"(?<=\d)\s+на\s+(?=\d)", " ", q)  # 40 на 20 на 2
    q = re.sub(r"[фøд№d](?=\d)", " ", q)  # ф57, d12, №12
    nums, words = [], []
    for t in re.findall(r"[a-zа-я0-9./]+", q):
        t = t.strip("./")
        if not t:
            continue
        if m := re.fullmatch(r"(\d+(?:\.\d+)?)(?:мм|mm)?", t):
            nums.append(float(m[1]))
        elif m := re.fullmatch(r"(\d+)([пуб])", t):  # 12П/12У: серии в xls нет, ищем по номеру
            nums.append(float(m[1]))
        elif t not in STOP and len(t) > 1:
            words.append(fix_word(t))
    return nums, words


# особые виды — показываем ниже обычного проката, если о них не просили
SPECIAL = ["ДЕТАЛИ", "ФЛАНЦ", "ОТВОД", "РИФЛ", "ПРОСЕЧ", "НЕРЖ", "ОЦИНК", "АЛЮМ", "МЕД", "ЛАТУН", "НИЗКОЛЕГ", "Х/К", "ПРОФНАСТ", "КРЕПЕЖ", "ГАЙК", "БОЛТ"]


def _rank(r, nums, words):
    sec = norm(r["section"])
    asked = " ".join(words)
    special = any(k.lower() in sec and not any(k.lower()[:4] in w or w[:4] in k.lower() for w in words)
                  for k in SPECIAL)
    try:
        size_hit = float(r["size"]) in nums
    except ValueError:
        size_hit = bool(re.sub(r"\d", "", r["size"]).lower() and r["size"].lower() in asked)
    defect = bool(re.search(r"неконд|уценк", r["name"].lower()))
    return (defect, special, not size_hit if nums else False, float(r["price_rub"]))


def _search(nums, words):
    hits = [r for r in load() if float(r["price_rub"]) > 0 and match(r, words, nums)]
    hits.sort(key=lambda r: _rank(r, nums, words))
    return hits


def find_ex(query, limit=30):
    """Поиск с ослаблением: если точно не нашлось — без больших чисел (размер листа, длина), потом без
    лишних слов (марка, уточнения). Возвращает (позиции, всего, пояснение что отброшено или None)."""
    nums, words = parse_query(query)
    hits = _search(nums, words)
    if hits:
        return hits[:limit], len(hits), None
    small = [n for n in nums if n < 1000]
    if small != nums and (hits := _search(small, words)):
        return hits[:limit], len(hits), "без размеров листа/длины: " + ", ".join(f"{n:g}" for n in nums if n >= 1000)
    for drop in sorted(words, key=lambda w: (not re.search(r"\d", w), len(w))):  # сначала марки вида ст3сп
        rest = [w for w in words if w != drop]
        if rest and (hits := _search(small, rest)):
            return hits[:limit], len(hits), f"без слова «{drop}» (точного совпадения нет)"
    return [], 0, None


def find(query, limit=30):
    hits, total, _ = find_ex(query, limit)
    return hits, total


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
