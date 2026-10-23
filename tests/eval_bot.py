"""Проверка понимания запросов ботом на настоящем Claude API (запускать на сервере, где есть ключи):
    sudo -u metal bash -c "cd ~/metal-catalog && set -a && . ~/.metal-catalog.env && set +a && .venv/bin/python tests/eval_bot.py"
Каждый запрос прогоняется через бота; проверяется, какие функции он вызвал и с какими параметрами.
Стоимость прогона на Haiku — порядка нескольких центов.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("TELEGRAM_CHAT_ID", "0")
import bot  # noqa: E402
import cities  # noqa: E402
import costing  # noqa: E402

# (сообщение, ожидание). calc: section — подстрока раздела, size — колонка размера, qty/unit, city, piece/sheet.
CASES = [
    ("профтруба 40х20х2, 5 т, Караганда", {"calc": [dict(section="ПРЯМОУГ", size="2", qty=5, unit="т", city="Караганда")]}),
    ("проф 40*20*2 5тн карага", {"calc": [dict(section="ПРЯМОУГ", size="2", qty=5, unit="т", city="Караганда")]}),
    ("труба профильная 40 на 20 на 2 пять тонн до караганды",
     {"calc": [dict(section="ПРЯМОУГ", size="2", qty=5, unit="т", city="Караганда")]}),
    ("квадратка 40х40х2 600м алматы", {"calc": [dict(section="КВАДРАТ", size="2", qty=600, unit="м", city="Алматы")]}),
    ("100 хлыстов профтрубы 40х20х2 по 6м в астану",
     {"calc": [dict(section="ПРЯМОУГ", size="2", qty=100, unit="шт", piece=6, city="Астана")]}),
    ("лист 4мм 1500х6000 10 листов шымкент",
     {"calc": [dict(section="ЛИСТ", size="4", qty=10, unit="шт", sheet=9.0, city="Шымкент")]}),
    ("лист горячекатанный 4мм толщ 1500-3000мм 5 штук в караганду",
     {"calc": [dict(section="Г/К", size="4", qty=5, unit="шт", sheet=4.5, city="Караганда")]}),
    ("лист 10 ст3 2 тонны", {"calc": [dict(section="ЛИСТ", size="10", qty=2, unit="т", city="Алматы")]}),
    ("арматура 12 а500с 20т чимкент", {"calc": [dict(section="АРМАТУРА", size="12", qty=20, unit="т", city="Шымкент")]}),
    ("арм 12 3000 кг нур-султан", {"calc": [dict(section="АРМАТУРА", size="12", tons=3, city="Астана")]}),
    ("уголок 50х5 1,5т костанай", {"calc": [dict(section="УГОЛОК", size="5", qty=1.5, unit="т", city="Костанай")]}),
    ("швеллер 12 3 т актобе", {"calc": [dict(section="ШВЕЛЛЕР", qty=3, unit="т", city="Актобе")]}),
    ("балка 20б1 4т павлодар", {"calc": [dict(section="БАЛК", size="Б1", qty=4, unit="т", city="Павлодар")]}),
    ("труба 57х3,5 500 метров атырау",
     {"calc": [dict(section="ЭЛЕКТРОСВАР", size="3.5", qty=500, unit="м", city="Атырау")]}),
    ("полоса 40х4 1т уральск", {"calc": [dict(section="ПОЛОСА", size="4", qty=1, unit="т", city="Уральск")]}),
    ("оцинковка 0.5 3 т алматы", {"calc": [dict(section="ОЦИНК", size="0.5", qty=3, unit="т", city="Алматы")]}),
    ("нержавейка лист 2мм aisi 304 1т алматы", {"calc": [dict(section="НЕРЖ", size="2", qty=1, unit="т", city="Алматы")]}),
    ("квадрат 20 2т алматы", {"calc": [dict(section="КВАДРАТ", qty=2, unit="т", city="Алматы")]}),
    ("труба 40х20х2 и уголок 50х5 по 2 тонны в алматы",
     {"calc": [dict(section="ПРЯМОУГ", size="2", qty=2, unit="т", city="Алматы"),
               dict(section="УГОЛОК", size="5", qty=2, unit="т", city="Алматы")]}),
    ("арматура 12 цена", {"tools": ["show_prices"], "no_calc": True}),
    ("сколько метров в 3 тоннах трубы 57х3,5", {"tools": ["convert"], "no_calc": True}),
    ("сколько весит 100 хлыстов арматуры 12 по 11.7 м", {"tools": ["convert"], "no_calc": True}),
    ("лист 4мм 5 листов караганда", {"no_calc": True}),  # нет размера листа — должен спросить
    ("доставка москва шымкент 10 тонн", {"tools": ["delivery"], "no_calc": True}),
]

calls = []
_orig_run = bot.run_tool


def spy(name, args, outbox):
    item = None
    if "item_id" in args:
        try:
            item = costing.get_item(args["item_id"])
        except KeyError:
            pass
    calls.append((name, dict(args), item))
    return _orig_run(name, args, outbox)


bot.run_tool = spy
usage = {"in": 0, "out": 0}
_orig_create = bot.client.messages.create


def counted(**kw):
    resp = _orig_create(**kw)
    usage["in"] += resp.usage.input_tokens
    usage["out"] += resp.usage.output_tokens
    return resp


bot.client.messages.create = counted


def check_calc(exp, args, item):
    errs = []
    if item is None:
        return ["позиция не найдена по id"]
    if exp["section"] not in item["section"].upper():
        errs.append(f"раздел {item['section']}")
    if "size" in exp and item["size"] != exp["size"]:
        errs.append(f"размер {item['size']}")
    if "qty" in exp and abs(float(args["quantity"]) - exp["qty"]) > 1e-6:
        errs.append(f"кол-во {args['quantity']}")
    if "unit" in exp and args["unit"] != exp["unit"]:
        errs.append(f"ед. {args['unit']}")
    if "tons" in exp:
        t = float(args["quantity"]) / (1000 if args["unit"] == "кг" else 1) if args["unit"] in ("т", "кг") else None
        if t is None or abs(t - exp["tons"]) > 1e-6:
            errs.append(f"вес {args['quantity']} {args['unit']}")
    if "piece" in exp and abs(float(args.get("piece_length_m") or 0) - exp["piece"]) > 1e-6:
        errs.append(f"длина хлыста {args.get('piece_length_m')}")
    if "sheet" in exp:
        area = costing.piece_size(args.get("sheet_mm")) if args.get("sheet_mm") else 0
        if abs(area - exp["sheet"]) > 1e-6:
            errs.append(f"лист {args.get('sheet_mm')}")
    if cities.normalize(args["city"])[0] != exp["city"]:
        errs.append(f"город {args['city']}")
    return errs


passed = 0
for msg, exp in CASES:
    calls.clear()
    bot.history.clear()
    try:
        outbox, reply = bot.ask_claude("eval", msg)
    except Exception as e:
        print(f"✗ {msg}\n    ошибка: {e}")
        continue
    calc = [(a, it) for n, a, it in calls if n == "calc_cost"]
    names = [n for n, _, _ in calls]
    errs = []
    if exp.get("no_calc") and calc:
        errs.append("посчитал, хотя должен был не считать/спросить")
    for t in exp.get("tools", []):
        if t not in names:
            errs.append(f"не вызвал {t}")
    for i, e in enumerate(exp.get("calc", [])):
        best = None
        for a, it in calc:
            err = check_calc(e, a, it)
            if best is None or len(err) < len(best):
                best = err
        if best is None:
            errs.append(f"не посчитал позицию {i + 1}")
        elif best:
            errs.append(f"позиция {i + 1}: " + ", ".join(best))
    if errs:
        print(f"✗ {msg}\n    " + "; ".join(errs) + f"\n    вызовы: {[(n, a) for n, a, _ in calls]}\n    ответ: {reply[:200]}")
    else:
        passed += 1
        print(f"✓ {msg}")

cost = usage["in"] / 1e6 * 0.10 + usage["out"] / 1e6 * 0.50
print(f"\nИтог: {passed}/{len(CASES)} верно. Токены: {usage['in']} вход, {usage['out']} выход ≈ ${cost:.3f} (Haiku)")
