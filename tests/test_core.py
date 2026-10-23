"""Проверки расчётов и понимания запросов без Claude: python3 tests/test_core.py
Вес — против табличных значений ГОСТ; себестоимость — независимым пересчётом; поиск — набором формулировок.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cities  # noqa: E402
import costing  # noqa: E402
import find  # noqa: E402
import weights  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    if not cond:
        failed += 1
        print("✗", msg)


def near(a, b, tol):
    return a is not None and abs(a - b) <= tol


# --- вес: справочные значения ГОСТ (кг/м) ---
check(near(weights.round_pipe(57, 3.5), 4.62, 0.01), "труба 57×3,5 ≈ 4,62 (ГОСТ 10704)")
check(near(weights.round_pipe(108, 4), 10.26, 0.02), "труба 108×4 ≈ 10,26 (ГОСТ 10704)")
check(near(weights.round_bar(12), 0.888, 0.001), "арматура/круг 12 ≈ 0,888")
check(near(weights.sheet(10), 78.5, 0.01), "лист 10 мм = 78,5 кг/м²")
check(near(weights.angle(50, 50, 5), 3.77, 0.001), "уголок 50×5 = 3,77 (ГОСТ 8509)")
check(near(weights.angle(100, 100, 8), 12.25, 0.001), "уголок 100×8 = 12,25 (ГОСТ 8509)")
check(near(weights.channel(12), 10.4, 0.001), "швеллер 12П = 10,4 (ГОСТ 8240)")
check(near(weights.ibeam(20, "Б1"), 22.4, 0.001), "балка 20Б1 = 22,4 (ГОСТ 26020)")
check(near(weights.ibeam(20), 21.0, 0.001), "двутавр 20 = 21,0 (ГОСТ 8239)")
check(near(weights.strip(40, 4), 1.256, 0.001), "полоса 40×4 = 1,256")
check(near(weights.hexagon(17), 1.96, 0.01), "шестигранник 17 ≈ 1,96")
check(near(weights.profile_pipe(40, 40, 2), 2.33, 0.03), "профтруба 40×40×2 ≈ 2,3 (ГОСТ 30245)")

# --- поиск: (запрос, ожидаемый раздел, ожидаемый размер в колонке size или None) ---
SEARCH = [
    ("профтруба 40*20*2", "ПРЯМОУГ", "2"), ("труба профильная 40 на 20 на 2", "ПРЯМОУГ", "2"),
    ("проф 40х20х2мм", "ПРЯМОУГ", "2"), ("квадратка 40х40х2", "КВАДРАТ", "2"), ("профтруба 40х2", "КВАДРАТ", "2"),
    ("труба 57х3,5", "ЭЛЕКТРОСВАР", "3.5"), ("труба круглая ф57 3.5", "ЭЛЕКТРОСВАР", "3.5"),
    ("бесшовная 57х4", "Г/Д", "4"), ("вгп ду 20", "ВОДОГАЗ", None),
    ("арматура 12", "АРМАТУРА", "12"), ("армотура 12", "АРМАТУРА", "12"), ("арм 12 а500с", "АРМАТУРА", "12"),
    ("арматура d12", "АРМАТУРА", "12"),
    ("лист 4мм", "ЛИСТОВАЯ Г/К", "4"), ("лист горячекатаный 4", "Г/К", "4"), ("лист 4 1500х6000", "ЛИСТОВАЯ Г/К", "4"),
    ("лист 10 ст3сп", "ЛИСТОВАЯ", "10"), ("лист 10 09г2с", "НИЗКОЛЕГ", "10"), ("лист оцинкованный 0.5", "ОЦИНК", "0.5"),
    ("уголок 50х50х5", "УГОЛОК", "5"), ("уголок 50х5", "УГОЛОК", "5"), ("угол 63х6", "УГОЛОК", "6"),
    ("швеллер 12п", "ШВЕЛЛЕР", None), ("балка 20б1", "БАЛК", "Б1"), ("двутавр 20Б1", "БАЛК", "Б1"),
    ("полоса 40х4", "ПОЛОСА", "4"), ("квадрат 20", "КВАДРАТ Г/К", "20"), ("круг 20", "КРУГ", "20"),
    ("шестигранник 17", "ШЕСТИГРАН", "17"), ("нержавейка лист 2мм", "НЕРЖ", "2"), ("профнастил с8 0.5", "ПРОФНАСТ", "0.5"),
    ("труба 40х20", "ПРЯМОУГ", None),
]
for q, sec, size in SEARCH:
    hits, total, note = find.find_ex(q, limit=1)
    if not hits:
        check(False, f"поиск «{q}»: ничего не найдено")
        continue
    r = hits[0]
    check(sec in r["section"].upper(), f"поиск «{q}»: раздел {r['section']} (ждали {sec})")
    if size:
        check(r["size"] == size, f"поиск «{q}»: размер {r['size']} (ждали {size})")
    check(not ("неконд" in r["name"].lower() or "уценк" in r["name"].lower()), f"поиск «{q}»: первой некондиция")

# --- города ---
for raw, want in [("в Карагу", "Караганда"), ("Караганду", "Караганда"), ("Нур-Султан", "Астана"), ("Чимкент", "Шымкент"),
                  ("Алма-Ата", "Алматы"), ("г. Алматы", "Алматы"), ("Өскемен", "Усть-Каменогорск"),
                  ("Семипалатинск", "Семей"), ("Актюбинск", "Актобе"), ("Уральска", "Уральск"), ("Капчагай", "Алматы")]:
    check(cities.normalize(raw)[0] == want, f"город «{raw}» → {cities.normalize(raw)[0]} (ждали {want})")

# --- себестоимость: независимый пересчёт (доставка подменена фиксированной, без интернета) ---
costing.freight_options = lambda f, t, tons: ([{"type": "тест", "kzt": 500000, "days": 5, "source": "тест"}], [])
costing.rate.effective = lambda code, date=None: (5.5, 0)
hits, _ = find.find("профтруба 40х20х2", limit=1)
r = hits[0]
c = costing.landed_cost(costing.item_id(r), 5, "т", "Караганда")
price = float(r["price_rub"])
goods = price * 5 / 1.22 * 5.5
check(near(c["goods_kzt"], goods, 0.5), f"товар {c['goods_kzt']:.0f} ≠ {goods:.0f}")
check(near(c["kz_vat_kzt"], (goods + 500000) * 0.16, 0.5), "НДС РК 16% от (товар + доставка)")
check(near(c["total_with_vat_kzt"], (goods + 500000) * 1.16, 0.5), "итого с НДС")
check(near(c["per_t_no_vat"], (goods + 500000) / 5, 0.5), "за тонну")
check(near(c["meters"], 5000 / weights.profile_pipe(40, 20, 2), 0.1), "метры из тонн")
c = costing.landed_cost(costing.item_id(r), 100, "шт", "Алматы", piece_length_m=6)
check(near(c["meters"], 600, 1e-6) and near(c["tons"], 0.6 * weights.profile_pipe(40, 20, 2), 1e-6), "100 хлыстов по 6 м")
hits, _ = find.find("лист 4мм", limit=1)
c = costing.landed_cost(costing.item_id(hits[0]), 5, "шт", "Алматы", sheet_mm="1500x3000")
check(near(c["meters"], 22.5, 1e-6) and near(c["tons"], 22.5 * 31.4 / 1000, 1e-6), "5 листов 1500×3000 × 4 мм")
c = costing.landed_cost(costing.item_id(hits[0]), 5, "шт", "Алматы", sheet_mm="1,5х6")
check(near(c["meters"], 45, 1e-6), "лист «1,5х6» понят как 1500×6000")

print(f"\n{'ВСЁ ВЕРНО' if not failed else f'ОШИБОК: {failed}'}")
sys.exit(1 if failed else 0)
