"""Карточки для Telegram (HTML): расчёт себестоимости и список цен. Все числа — из costing/find.

Главная сумма — сверху жирным, слагаемые — столбиком моноширинным шрифтом, технические подробности —
в свёрнутом блоке «Подробнее» (expandable blockquote).
"""

import re
from html import escape

import find

NBSP = " "


def money(x):
    return f"{x:,.0f}".replace(",", NBSP)


def dec(x, digits=3):
    return f"{x:.{digits}f}".replace(".", ",")


def ru_date(iso):
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def pretty_name(section, name, size):
    """«ТРУБЫ ЭЛЕКТРОСВАРНЫЕ ПРЯМОУГ | 40x20 | 2» → «Профтруба 40×20×2»."""
    sec, nm = section.upper(), name.strip()
    dims = [x for x in re.findall(r"\d+(?:[.,]\d+)?", nm)]
    extra = re.sub(r"^[\d.,x×хX ]+", "", nm).strip()
    tail = f" {extra}" if extra else ""
    if "ТРУБ" in sec and ("ПРЯМОУГ" in sec or "КВАДРАТ" in sec) and dims:
        a, b = (dims[0], dims[1]) if "ПРЯМОУГ" in sec and len(dims) > 1 else (dims[0], dims[0])
        return f"Профтруба {a}×{b}×{size}{tail}"
    if "ТРУБ" in sec and "ВОДОГАЗ" not in sec and dims and "НЕРЖ" not in sec:
        return f"Труба {dims[0]}×{size}{tail}"
    if "АРМАТУР" in sec:
        return f"Арматура Ø{size} {nm}"
    if "ЛИСТ" in sec and "НЕРЖ" not in sec:
        return f"Лист {size} мм {nm}"
    return f"{section.capitalize()} {nm} {size}".strip()


def cost_card(c, supplier_city):
    it = c["item"]
    per = "м²" if c["unit"] == "м2" or "ЛИСТ" in it["section"].upper() else "м"
    title = pretty_name(it["section"], it["name"], it["size_raw"])
    qty = f"{c['qty']:g} {c['unit']}" + (f" по {c['piece_desc']}" if c.get("piece") else "")
    out = [f"<b>{escape(title)} · {escape(qty)} → {escape(c['city'])}</b>",
           f"{escape(it['supplier'])}, прайс {ru_date(it['price_date'])}", "",
           f"<b>💰 Итого с НДС: {money(c['total_with_vat_kzt'])} ₸</b>",
           f"Без НДС: {money(c['cost_no_vat_kzt'])} ₸"]
    per_line = []
    if c["per_t_no_vat"]:
        per_line.append(f"за тонну: {money(c['per_t_no_vat'])} ₸")
    if c["per_m_no_vat"]:
        per_line.append(f"за {per}: {money(c['per_m_no_vat'])} ₸")
    if per_line:
        out.append(" · ".join(per_line).capitalize())
    out.append("")

    rows = [("Металл", c["goods_kzt"])]
    if c["freight"]:
        rows.append(("Доставка", c["freight"]["kzt"]))
    rows.append(("НДС 16%", c["kz_vat_kzt"]))
    width = max(len(money(v)) for _, v in rows)
    out.append("<pre>" + "\n".join(f"{k:<9}{money(v):>{width + 2}} ₸" for k, v in rows) + "</pre>")

    f = c["freight"]
    if f:
        line = f"🚚 {f['type'].capitalize()}, ~{f['days']} дн."
        for alt in c["freight_alternatives"]:
            line += f" · {alt['type']}: {money(alt['kzt'])} ₸"
        out.append(escape(line))
    else:
        out.append("🚚 Доставку посчитать не удалось")
    if c["tons"] is not None and c["mass_kg_m"]:
        meters = dec(c["meters"], 1) if c["meters"] < 100 else money(c["meters"])
        out.append(f"⚖️ {dec(c['tons'], 3).rstrip('0').rstrip(',')} т ≈ {meters} {per} "
                   f"({dec(c['mass_kg_m'])} кг/{per}, вес теоретический)")

    details = [f"Цена: {money(it['price_rub'])} ₽/{it['price_unit']}, с НДС РФ · {it['src']}",
               f"Без НДС РФ: {money(c['goods_rub_net'])} ₽ × {dec(c['fx']['rate'])} ₸/₽ (курс НБ РК"
               + (f" +{c['fx']['spread_pct']}%" if c["fx"]["spread_pct"] else "") + ")"]
    if f:
        details.append(f"Доставка {supplier_city} → {c['city']}: {f['source']}. Оценка, не котировка перевозчика")
    details += c["freight_notes"] + c["warnings"]
    details.append("НДС РК идёт в зачёт, если вы плательщик НДС")
    out.append("<blockquote expandable><b>Подробнее</b>\n" + "\n".join(escape(d) for d in details) + "</blockquote>")
    return "\n".join(out)


def prices_card(rows, title=None):
    """Список цен по выбранным позициям каталога."""
    r0 = rows[0]
    head = title or pretty_name(r0["section"], r0["name"], r0["size"])
    out = [f"<b>{escape(head)}</b> · {escape(r0['supplier'])}, {ru_date(r0['price_date'])}"]
    for r in rows:
        label = f"{r['name']} {r['size_label']} {r['size']}".strip()
        out.append(f"• <b>{money(float(r['price_rub']))} ₽/{escape(r['unit'])}</b> — {escape(label)}")
    m = find.mass_kg_m(r0)
    if m:
        per = "м²" if "ЛИСТ" in r0["section"].upper() else "м"
        out.append(f"{dec(m)} кг/{per} · 1 т ≈ {money(1000 / m)} {per} (вес теоретический)")
    out.append("<i>Цены в рублях с НДС РФ, за единицу поставщика</i>")
    return "\n".join(out)
