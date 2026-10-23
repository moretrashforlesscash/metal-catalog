"""Telegram-бот владельца: поиск по каталогу металла и себестоимость с доставкой.

Claude (по умолчанию Haiku) только понимает запрос и вызывает функции из scripts/ — все цифры считает код.
Сообщение, начинающееся со слова «подумай», уходит в более умную модель (Sonnet).
Отвечает только владельцу (TELEGRAM_CHAT_ID). Запуск на сервере — systemd-служба metal-bot (deploy/install_bot.sh).

Переменные окружения: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY,
необязательные BOT_MODEL (claude-haiku-5-5), BOT_SMART_MODEL (claude-sonnet-5-5).
"""

import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cards  # noqa: E402
import costing  # noqa: E402
import find  # noqa: E402

TOKEN = os.environ["TELEGRAM_TOKEN"]
OWNER = os.environ["TELEGRAM_CHAT_ID"]
MODEL = os.environ.get("BOT_MODEL", "claude-haiku-5-5")
SMART_MODEL = os.environ.get("BOT_SMART_MODEL", "claude-sonnet-5-5")
API = f"https://api.telegram.org/bot{TOKEN}/"
MAX_TURNS = 8  # после стольких вопросов история начинается заново (короче контекст — дешевле запрос)
MAX_STEPS = 8  # предел вызовов функций на один вопрос

SYSTEM = """Ты — помощник Алема, B2B-поставщика металлопроката из Казахстана (Алматы). Отвечаешь в Telegram по-русски,
коротко и простым текстом (без markdown, без таблиц, без звёздочек).

Что умеешь — через функции:
- search_catalog: найти позиции в каталоге поставщиков (цены в рублях с НДС РФ, за единицу поставщика).
- calc_cost: себестоимость партии в тенге с доставкой до города Казахстана и НДС РК 16%.
- show_prices: показать карточку с ценами выбранных позиций (когда нужен список цен без расчёта).
- delivery: стоимость доставки партии между городами.

Карточки calc_cost и show_prices бот отправляет сам, красиво оформленными. Поэтому после них НЕ повторяй цифры
и не пересказывай карточку: допиши максимум 1–2 коротких строки — альтернативы, предупреждение или вопрос
(«Посчитать другой город или объём?»). Если добавить нечего — ответь одним словом «Готово».

Правила:
1. Цифры бери ТОЛЬКО из результатов функций. Ничего не считай и не округляй сам.
2. Позиции нет в каталоге — так и скажи и предложи уточнить. Не подставляй похожую молча; аналоги — только явно
   помеченные как аналоги.
3. Найдено несколько вариантов — бери самый дешёвый нормальный (не некондицию/уценку, если не просили), коротко
   назови 1–2 альтернативы с ценами.
4. Есть позиция, количество и город — сразу считай calc_cost. Нет города — считай до Алматы и скажи об этом.
   Нет количества — покажи цены через show_prices (3–5 лучших вариантов одной позиции) и спроси объём.
5. Количество: «5т», «5 тонн» → 5 т; «600 м», «600 метров» → 600 м; «200 шт» → 200 шт.
   Листы штуками («5 листов 1500х3000») → unit=шт + sheet_mm="1500x3000"; трубы/арматура/уголок штуками
   («100 хлыстов по 6 м») → unit=шт + piece_length_m=6. Размер листа/хлыста в каталоге не указан — если не задан
   в запросе, спроси (стандарт листа 1500х6000 или 1250х2500, хлыст 6 или 12 м).
6. Всегда указывай поставщика и дату прайса. Вес — теоретический. Доставка — оценка по средним ставкам.
7. Профтруба/квадратка/прямоугольная = труба профильная (в каталоге «ПРЯМОУГ»/«КВАДРАТ»); «сороковка» = 40;
   «двойка» — стенка 2 мм. Швеллер в прайсе без серии П/У — предупреждай об этом.
"""

TOOLS = [
    {
        "name": "search_catalog",
        "description": "Поиск позиций в каталоге. Запрос — как пишет человек: «труба проф 40х20х2», «арматура A500 12», "
                       "«лист 10 ст3», «уголок 50х50х5», «балка 20Б1». Числа ищутся в размерах, слова — в названии. "
                       "Возвращает список с id (нужен для calc_cost), ценой в ₽ за единицу поставщика, массой кг/м.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "поисковый запрос"},
                "limit": {"type": "integer", "description": "сколько вариантов вернуть, по умолчанию 8"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "calc_cost",
        "description": "Себестоимость партии позиции из каталога в тенге: товар без НДС РФ по курсу НБ РК, доставка "
                       "(фура/догруз/сборный груз — самое дешёвое), НДС РК 16%. Возвращает готовый текст расчёта.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "id позиции из search_catalog"},
                "quantity": {"type": "number", "description": "количество"},
                "unit": {"type": "string", "enum": ["т", "кг", "м", "м2", "шт"], "description": "единица количества"},
                "city": {"type": "string", "description": "город доставки в Казахстане, например «Караганда»"},
                "sheet_mm": {"type": "string", "description": "если unit=шт и это лист: размер листа в мм «ширинаxдлина», "
                                                            "например «1500x3000»"},
                "piece_length_m": {"type": "number", "description": "если unit=шт и это труба/арматура/уголок и т.п.: "
                                                                    "длина одной штуки (хлыста) в метрах, например 6 или 12"},
            },
            "required": ["item_id", "quantity", "unit", "city"],
        },
    },
    {
        "name": "show_prices",
        "description": "Отправить пользователю карточку с ценами выбранных позиций (id из search_catalog), "
                       "3–5 вариантов одной позиции, самые подходящие первыми.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_ids": {"type": "array", "items": {"type": "string"}},
                "title": {"type": "string", "description": "короткий заголовок, например «Арматура А500 Ø12»"},
            },
            "required": ["item_ids"],
        },
    },
    {
        "name": "delivery",
        "description": "Варианты доставки партии металла между городами (фура 20 т, догруз, сборный груз) в тенге.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city_from": {"type": "string"},
                "city_to": {"type": "string"},
                "tons": {"type": "number"},
            },
            "required": ["city_from", "city_to", "tons"],
        },
    },
]


def run_tool(name, args, outbox):
    if name == "search_catalog":
        hits, total = find.find(args["query"], limit=min(int(args.get("limit") or 8), 20))
        items = []
        for r in hits:
            m = find.mass_kg_m(r)
            items.append({
                "id": costing.item_id(r), "section": r["section"], "name": r["name"],
                "size": f"{r['size_label']} {r['size']}".strip(), "price_rub": float(r["price_rub"]),
                "unit": r["unit"], "mass_kg_m": round(m, 3) if m else None,
                "supplier": r["supplier"], "price_date": r["price_date"],
            })
        return json.dumps({"found": total, "shown": len(items), "items": items}, ensure_ascii=False)
    if name == "calc_cost":
        c = costing.landed_cost(args["item_id"], float(args["quantity"]), args["unit"], args["city"],
                                args.get("sheet_mm"), args.get("piece_length_m"))
        outbox.append(cards.cost_card(c, costing.SETTINGS["suppliers"][c["item"]["supplier"]]["city"]))
        return "Карточка отправлена пользователю. Для справки:\n" + costing.summary(c)
    if name == "show_prices":
        rows = [costing.get_item(i) for i in args["item_ids"][:8]]
        outbox.append(cards.prices_card(rows, args.get("title")))
        return "Карточка с ценами отправлена пользователю."
    if name == "delivery":
        opts, notes = costing.freight_options(args["city_from"], args["city_to"], float(args["tons"]))
        lines = [f"{o['type']}: {costing.fmt(o['kzt'])} ₸, ~{o['days']} дн. ({o['source']})" for o in opts]
        return "\n".join(lines + [f"⚠ {n}" for n in notes]) or "нет данных по этому маршруту"
    raise ValueError(f"неизвестная функция {name}")


client = anthropic.Anthropic()
history = {}  # chat_id -> список сообщений диалога (только добавляем в конец, не правим)


def ask_claude(chat_id, text):
    smart = text.lower().startswith("подумай")
    if smart:  # умная модель — отдельный короткий диалог, без истории
        messages, model, effort = [], SMART_MODEL, "medium"
    else:
        messages, model, effort = list(history.get(chat_id, [])), MODEL, "low"
        if sum(1 for m in messages if m["role"] == "user" and isinstance(m["content"], str)) >= MAX_TURNS:
            messages = []
    messages.append({"role": "user", "content": text})
    outbox = []

    for _ in range(MAX_STEPS):
        params = dict(model=model, max_tokens=8000, system=SYSTEM, tools=TOOLS, messages=messages,
                      output_config={"effort": effort})
        if smart:  # при отказе модели запрос сам уйдёт в запасную модель
            resp = client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            resp = client.messages.create(**params)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "refusal":
            return outbox, "Модель отказалась отвечать на этот запрос. Попробуйте переформулировать."
        if resp.stop_reason != "tool_use":
            if not smart:
                history[chat_id] = messages
            text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            if outbox and re.fullmatch(r"готово\.?", text.lower()):
                text = ""
            return outbox, text or ("" if outbox else "(пустой ответ)")
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": run_tool(b.name, b.input, outbox)})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"ошибка: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
    return outbox, "Слишком много шагов на один вопрос — уточните запрос."


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API + method, data=data, timeout=70) as resp:
        return json.loads(resp.read())["result"]


def send(chat_id, text):
    for i in range(0, len(text), 4000):
        tg("sendMessage", chat_id=chat_id, text=text[i:i + 4000])


def send_html(chat_id, html):
    try:
        tg("sendMessage", chat_id=chat_id, text=html[:4096], parse_mode="HTML")
    except urllib.error.HTTPError:  # не разобрал разметку — отправим без оформления
        send(chat_id, re.sub(r"<[^>]+>", "", html))


HELP = ("Пишите запрос как обычно, например:\n"
        "• профтруба 40х20х2, 5 т, Караганда\n"
        "• арматура A500 12 — цены\n"
        "• сколько метров в 3 т трубы 57х3,5\n"
        "• доставка Москва → Шымкент, 10 т\n"
        "«подумай: …» — сложный вопрос, ответит более умная модель (дороже).\n"
        "/new — начать разговор заново.")


def handle(msg):
    chat_id, text = str(msg["chat"]["id"]), (msg.get("text") or "").strip()
    if chat_id != OWNER:
        send(chat_id, "Это закрытый бот.")
        return
    if text in ("/start", "/help"):
        send(chat_id, HELP)
        return
    if text == "/new":
        history.pop(chat_id, None)
        send(chat_id, "Начали заново.")
        return
    if not text:
        return
    tg("sendChatAction", chat_id=chat_id, action="typing")
    try:
        outbox, reply = ask_claude(chat_id, text)
        for card in outbox:
            send_html(chat_id, card)
        if reply:
            send_html(chat_id, f"<i>{escape(reply)}</i>" if outbox else escape(reply))
    except anthropic.APIStatusError as e:
        history.pop(chat_id, None)
        send(chat_id, f"Ошибка Claude API ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        send(chat_id, "Нет связи с Claude API, попробуйте через минуту.")


def main():
    offset = None
    print(f"бот запущен, модель {MODEL}", flush=True)
    while True:
        try:
            params = {"timeout": 50, "allowed_updates": json.dumps(["message"])}
            if offset:
                params["offset"] = offset
            for upd in tg("getUpdates", **params):
                offset = upd["update_id"] + 1
                if "message" in upd:
                    try:
                        handle(upd["message"])
                    except Exception:
                        traceback.print_exc()
                        send(OWNER, "Внутренняя ошибка бота, подробности в логе сервера.")
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
