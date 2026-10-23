"""Себестоимость позиции из каталога с доставкой до города в Казахстане, в тенге.

Пример: python3 scripts/costing.py "труба проф 40х20х2" 5 т Караганда
Цепочка: цена поставщика в ₽ (с НДС РФ) → без НДС РФ (экспорт в ЕАЭС по ставке 0%) → ₸ по курсу НБ РК (+спред)
→ доставка (фура по средней бирже fa-fa или сборный груз JetLogistic — что дешевле) → НДС РК 16% при ввозе
(база = товар + доставка). Настройки — reference/pricing.json. Используется ботом и будущим сайтом.
"""

import csv
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cities  # noqa: E402
import delivery_jet  # noqa: E402
import find  # noqa: E402
import freight_fafa  # noqa: E402
import rate  # noqa: E402

ROOT = Path(__file__).parent.parent
SETTINGS = json.loads((ROOT / "reference" / "pricing.json").read_text(encoding="utf-8"))
TON_UNITS = ("т", "теор.т")


def item_id(r):
    return f"{r['src']}|{r['size']}"


def get_item(iid):
    for r in find.load():
        if item_id(r) == iid:
            return r
    raise KeyError(f"позиция {iid} не найдена в каталоге (мог обновиться прайс — найдите заново)")


def ftl_quote(city_from, city_to):
    """Средняя ставка фуры 20 т с fa-fa; свежие (за fafa_cache_days) берём из logistics/fafa.csv."""
    days = SETTINGS["freight"]["fafa_cache_days"]
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    if freight_fafa.OUT.exists():
        rows = [r for r in csv.DictReader(open(freight_fafa.OUT, encoding="utf-8"))
                if r["from"] == city_from and r["to"] == city_to and r["date"] >= since]
        if rows:
            q = rows[-1]
        else:
            q = freight_fafa.quote(city_from, city_to)
            freight_fafa.save(q)
    else:
        q = freight_fafa.quote(city_from, city_to)
        freight_fafa.save(q)
    tiers = {t: int(q[f"t{t}"]) for t in (1, 2, 5, 10, 20) if str(q[f"t{t}"]).strip()}
    return {"t20": int(q["t20"]), "days": int(q["days"]), "km": int(q["km"]), "date": q["date"], "tiers": tiers}


def freight_options(city_from, city_to, tons):
    """Варианты доставки, самый дешёвый — первым. Ошибки источников попадают в notes."""
    cfg = SETTINGS["freight"]
    options, notes = [], []
    city_from, _ = cities.normalize(city_from)
    city_to, city_note = cities.normalize(city_to)
    if city_note:
        notes.append(city_note)
    try:
        q = ftl_quote(city_from, city_to)
        trucks = max(1, math.ceil(tons / cfg["truck_tons"]))
        options.append({"type": f"фура {cfg['truck_tons']} т" + (f" × {trucks}" if trucks > 1 else ""),
                        "kzt": trucks * q["t20"], "days": q["days"],
                        "source": f"средняя ставка биржи fa-fa.kz на {q['date']}, {q['km']} км"})
        # догруз: ближайшая ступень по весу ≥ партии; заявок по ним мало — цифра шумная
        tier = next((t for t in sorted(q["tiers"]) if t >= tons and t < cfg["truck_tons"]), None)
        if tier:
            options.append({"type": f"догруз / машина до {tier} т", "kzt": q["tiers"][tier], "days": q["days"],
                            "source": f"fa-fa.kz, ступень «{tier} т» — мало заявок, оценка грубая"})
    except Exception as e:
        notes.append(f"фура: нет данных ({e})")
    if tons <= cfg.get("groupage_max_tons", 5):
        try:
            j = delivery_jet.quote(city_from, city_to, tons * 1000, tons / cfg["groupage_density_t_m3"])
            options.append({"type": "сборный груз (JetLogistic)",
                            "kzt": j["pickup"] + j["line"] + j["door"] + j["extra"], "days": j["days"],
                            "source": "калькулятор jetlogistic.kz, забор + магистраль + до двери"})
        except Exception as e:
            notes.append(f"сборный груз JetLogistic: не возит в {city_to}" if "не нашли город" in str(e)
                         else f"сборный груз JetLogistic: нет данных ({str(e)[:80]})")
    options.sort(key=lambda o: o["kzt"])
    return options, notes


def piece_size(sheet_mm=None, piece_length_m=None):
    """Размер одной штуки: лист «1500x3000» (мм) → м², хлыст 6 (м) → м."""
    if sheet_mm:
        w, l = (float(x) for x in re.split(r"\s*[xх×*]\s*", str(sheet_mm).lower().replace(",", ".").strip()))
        if w < 20 and l < 20:  # «1,5х6» — размер в метрах
            w, l = w * 1000, l * 1000
        return w * l / 1e6
    return float(piece_length_m) if piece_length_m else None


def quantities(r, qty, unit, piece=None):
    """Перевод количества в тонны и метры по теоретической массе (если формула есть).
    piece — м (длина хлыста) или м² (площадь листа) одной штуки, если количество в штуках."""
    mass = find.mass_kg_m(r)  # кг/м, у листа — кг/м²
    tons = meters = None
    if unit == "шт" and piece:
        qty, unit = qty * piece, "м"
    if unit == "т":
        tons = qty
        meters = tons * 1000 / mass if mass else None
    elif unit == "кг":
        tons = qty / 1000
        meters = qty / mass if mass else None
    elif unit in ("м", "м2"):
        meters = qty
        tons = qty * mass / 1000 if mass else None
    return tons, meters, mass


def goods_rub(r, qty, unit, tons, meters):
    price, pu = float(r["price_rub"]), r["unit"]
    if pu in TON_UNITS and tons is not None:
        return price * tons
    if pu == "кг" and tons is not None:
        return price * tons * 1000
    if pu in ("м", "м2") and meters is not None:
        return price * meters
    if pu == "шт" and unit == "шт":
        return price * qty
    if pu == "тыс.шт" and unit == "шт":
        return price * qty / 1000
    raise ValueError(f"цена указана за «{pu}», а количество — в «{unit}»; "
                     "для этой позиции нет формулы массы, укажите количество в единицах цены")


def landed_cost(iid, qty, unit, city, sheet_mm=None, piece_length_m=None):
    """Себестоимость партии в ₸. unit: т, кг, м, м2, шт (для шт — размер листа или длина хлыста)."""
    r = get_item(iid)
    sup = SETTINGS["suppliers"][r["supplier"]]
    city = cities.normalize(city)[0] if cities.normalize(city)[1] is None else city
    piece = piece_size(sheet_mm, piece_length_m) if unit == "шт" else None
    tons, meters, mass = quantities(r, qty, unit, piece)
    gross_rub = goods_rub(r, qty, unit, tons, meters)
    net_rub = gross_rub / (1 + sup["vat_pct"] / 100) if sup["export_vat_zero"] else gross_rub
    fx, spread = rate.effective(sup["currency"])
    goods_kzt = net_rub * fx

    origin = r.get("warehouse") or sup["city"]
    options, notes = freight_options(origin, city, tons) if tons else ([], ["вес неизвестен — доставку не посчитать"])
    freight = options[0] if options else None
    freight_kzt = freight["kzt"] if freight else 0
    base = goods_kzt + freight_kzt
    vat = base * SETTINGS["kz_vat_pct"] / 100

    warn = []
    if r["unit"] == "теор.т":
        warn.append("цена за тонну теоретического веса")
    if "(цена от 5 т" in r["title"] and tons is not None and tons < 5:
        warn.append("у поставщика цена сортового проката — от 5 т, на меньшую партию может быть дороже")
    if find.is_offgrade(r):
        warn.append("некондиция / уценка / немерная длина («н/д», «НН») — не обычный прокат, уточнить у поставщика")
    if piece and sheet_mm and "ЛИСТ" in r["section"].upper():
        fmt_price = find.sheet_format(r)
        want = f"{piece_size(sheet_mm) * 1e6:g}"
        if not fmt_price:
            warn.append(f"формат листа в прайсе не указан — посчитано по весу листа {sheet_mm}; "
                        "наличие формата уточнить у поставщика")
        elif f"{piece_size(fmt_price) * 1e6:g}" != want:
            warn.append(f"в прайсе этот лист в формате {fmt_price}, а посчитано для {sheet_mm}")
    if sup["export_vat_zero"]:
        warn.append(f"НДС РФ {sup['vat_pct']}% снят — при экспорте в ЕАЭС поставщик должен дать ставку 0%; "
                    f"если откажет, товар дороже на {sup['vat_pct']}%")
    return {
        "item": {"id": iid, "supplier": r["supplier"], "warehouse": r.get("warehouse") or sup["city"], "price_date": r["price_date"], "section": r["section"],
                 "name": r["name"], "size": f"{r['size_label']} {r['size']}".strip(), "size_raw": r["size"],
                 "price_rub": float(r["price_rub"]), "price_unit": r["unit"], "src": r["src"]},
        "qty": qty, "unit": unit, "piece": piece, "piece_desc": sheet_mm or (f"{piece_length_m} м" if piece_length_m else None),
        "tons": tons, "meters": meters, "mass_kg_m": mass,
        "fx": {"rate": fx, "spread_pct": spread, "currency": sup["currency"]},
        "goods_rub_gross": gross_rub, "goods_rub_net": net_rub, "goods_kzt": goods_kzt,
        "freight": freight, "freight_alternatives": options[1:], "freight_notes": notes,
        "cost_no_vat_kzt": base, "kz_vat_kzt": vat, "total_with_vat_kzt": base + vat,
        "per_t_no_vat": base / tons if tons else None,
        "per_m_no_vat": base / meters if meters else None,
        "city": city, "warnings": warn,
    }


def equivalent_key(r):
    """Одна и та же позиция на разных складах: раздел, наименование, размер, единица (т = теор.т)."""
    unit = "т" if r["unit"] in TON_UNITS else r["unit"]
    return (r["section"].upper(), re.sub(r"\s+", " ", r["name"].strip().lower()), r["size"].strip(), unit)


def equivalents(iid):
    """Эта позиция на всех складах — по одной самой дешёвой строке на склад (без некондиции/н/д)."""
    base = get_item(iid)
    key = equivalent_key(base)
    best = {}
    for r in find.load():
        if equivalent_key(r) != key or float(r["price_rub"]) <= 0:
            continue
        if find.is_offgrade(r) and not find.is_offgrade(base):
            continue
        w = r.get("warehouse") or "Москва"
        if w not in best or float(r["price_rub"]) < float(best[w]["price_rub"]):
            best[w] = r
    best.setdefault(base.get("warehouse") or "Москва", base)
    return list(best.values())


def best_landed_cost(iid, qty, unit, city, sheet_mm=None, piece_length_m=None):
    """Себестоимость с каждого склада, где есть эта позиция; самый выгодный — основной результат,
    остальные — в c["warehouses"] (склад, итого с НДС, разница с лучшим в %)."""
    results = []
    for r in equivalents(iid):
        try:
            c = landed_cost(item_id(r), qty, unit, city, sheet_mm, piece_length_m)
        except Exception:
            continue
        if c["freight"] or not c["tons"]:  # склад без данных о доставке не сравниваем
            results.append(c)
    if not results:
        return landed_cost(iid, qty, unit, city, sheet_mm, piece_length_m)
    results.sort(key=lambda c: c["total_with_vat_kzt"])
    best = results[0]
    best["warehouses"] = [(c["item"]["warehouse"], c["total_with_vat_kzt"],
                           (c["total_with_vat_kzt"] / best["total_with_vat_kzt"] - 1) * 100) for c in results]
    return best


def convert(iid, qty, unit, sheet_mm=None, piece_length_m=None):
    """Пересчёт количества: тонны ↔ метры (м²) ↔ штуки (хлысты/листы). Для вопросов «сколько метров в 3 т»."""
    r = get_item(iid)
    piece = piece_size(sheet_mm, piece_length_m) if (sheet_mm or piece_length_m) else None
    tons, meters, mass = quantities(r, qty, unit, piece if unit == "шт" else None)
    if not mass:
        return f"Для «{r['section']} {r['name']} {r['size']}» нет формулы массы — пересчитать нельзя."
    sheet = "ЛИСТ" in r["section"].upper()
    per = "м²" if sheet else "м"
    lines = [f"{r['section']} | {r['name']} | {r['size_label']} {r['size']}: {mass:.3f} кг/{per} (теоретическая, факт ±3–8%)",
             f"{qty:g} {unit}" + (f" по {sheet_mm or str(piece_length_m) + ' м'}" if unit == "шт" and piece else "")
             + f" = {tons:.3f} т = {meters:,.1f} {per}".replace(",", " ")]
    if sheet:
        for w, l in ((1.5, 6), (1.25, 2.5), (1.5, 3)) if not piece else ():
            lines.append(f"  листов {w * 1000:g}x{l * 1000:g}: {meters / (w * l):.1f} шт ({w * l * mass:.1f} кг/лист)")
        if piece:
            lines.append(f"  листов {sheet_mm}: {meters / piece:.1f} шт ({piece * mass:.1f} кг/лист)")
    else:
        for L in ((piece,) if piece else (6, 12)):
            lines.append(f"  хлыстов по {L:g} м: {meters / L:.1f} шт ({L * mass:.1f} кг/хлыст)")
    return "\n".join(lines)


def fmt(x):
    return f"{x:,.0f}".replace(",", " ")


def summary(c):
    """Готовый текст для бота/консоли — все числа посчитаны здесь, модель их только пересказывает."""
    it = c["item"]
    per = "м²" if c["unit"] == "м2" or "ЛИСТ" in it["section"].upper() else "м"
    lines = [f"{it['section']} | {it['name']} | {it['size']}",
             f"{it['supplier']}, склад {it.get('warehouse', '')}, прайс {it['price_date']}: "
             f"{fmt(it['price_rub'])} ₽/{it['price_unit']} (с НДС РФ) [{it['src']}]"]
    q = [f"{c['qty']:g} {c['unit']}" + (f" по {c['piece_desc']}" if c.get("piece") else "")]
    if c["tons"] is not None and c["unit"] != "т":
        q.append(f"{c['tons']:.3f} т")
    if c["meters"] is not None and c["unit"] not in ("м", "м2"):
        q.append(f"{c['meters']:.1f} {per}" if c["meters"] < 100 else f"{fmt(c['meters'])} {per}")
    if c["mass_kg_m"]:
        q.append(f"теор. масса {c['mass_kg_m']:.3f} кг/{per} (факт ±3–8%)")
    lines.append("Партия: " + ", ".join(q))
    lines.append(f"Товар: {fmt(c['goods_rub_net'])} ₽ без НДС РФ × {c['fx']['rate']:.3f} ₸/₽"
                 + (f" (курс НБ РК +{c['fx']['spread_pct']}%)" if c['fx']['spread_pct'] else " (курс НБ РК)")
                 + f" = {fmt(c['goods_kzt'])} ₸")
    f = c["freight"]
    if f:
        lines.append(f"Доставка {SETTINGS['suppliers'][it['supplier']]['city']} → {c['city']}: {fmt(f['kzt'])} ₸ — {f['type']}, ~{f['days']} дн. ({f['source']})")
        for alt in c["freight_alternatives"]:
            lines.append(f"  вариант: {alt['type']} — {fmt(alt['kzt'])} ₸, ~{alt['days']} дн.")
    for n in c["freight_notes"]:
        lines.append(f"  ⚠ {n}")
    lines.append(f"Себестоимость без НДС: {fmt(c['cost_no_vat_kzt'])} ₸"
                 + (f" ({fmt(c['per_t_no_vat'])} ₸/т" if c["per_t_no_vat"] else "")
                 + (f", {fmt(c['per_m_no_vat'])} ₸/{per})" if c["per_m_no_vat"] else (")" if c["per_t_no_vat"] else "")))
    lines.append(f"НДС РК 16% при ввозе: {fmt(c['kz_vat_kzt'])} ₸ (идёт в зачёт, если вы плательщик НДС)")
    lines.append(f"Итого с НДС: {fmt(c['total_with_vat_kzt'])} ₸")
    if c.get("warehouses"):
        lines.append("Склады (итого с НДС): " + ", ".join(f"{w} {fmt(t)} ₸ ({d:+.0f}%)" for w, t, d in c["warehouses"]))
    if c["freight"]:
        lines.append("Доставка — оценка по средним ставкам, не котировка перевозчика.")
    for w in c["warnings"]:
        lines.append(f"• {w}")
    return "\n".join(lines)


def parse_qty(s):
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(т|кг|м2|м|шт)", s.strip().lower())
    if not m:
        raise ValueError(f"не понял количество «{s}» — пример: 5т, 600м, 200шт")
    return float(m[1].replace(",", ".")), m[2]


if __name__ == "__main__":
    query, qty_s, city = sys.argv[1], " ".join(sys.argv[2:-1]), sys.argv[-1]
    qty, unit = parse_qty(qty_s)
    hits, total = find.find(query, limit=1)
    if not hits:
        sys.exit(f"«{query}» не найдено в каталоге")
    print(summary(best_landed_cost(item_id(hits[0]), qty, unit, city)))
