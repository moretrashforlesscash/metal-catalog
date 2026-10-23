"""Ежедневное обновление: прайс «Металл Сервис», ставки на перевозки, коммит в GitHub, отчёт в Telegram.

Запускается на сервере по расписанию (cron), см. deploy/README.md:
    python3 scripts/update.py
Переменные окружения (необязательные): TELEGRAM_TOKEN, TELEGRAM_CHAT_ID — куда слать отчёт.

Шаги:
1. git pull — забрать изменения, сделанные Claude в чатах.
2. Скачать общий прайс mc.ru (zip). Если архив не изменился — пропустить.
3. Распаковать в suppliers/metallservis/raw/ГГГГ-ММ-ДД/, разобрать парсером.
4. Проверить: строк не меньше 80% от прошлого раза, у ≤10% позиций цена скакнула >30%.
   Не прошло — каталог НЕ перезаписывается, в Telegram уходит тревога.
5. Записать catalog/metallservis.csv, посчитать, что подорожало/подешевело.
6. Ставки: сделки Della по Казахстану, биржевые средние fa-fa по ключевым маршрутам.
7. Удалить старые сырые прайсы (оставить 30 дней + по одному на месяц).
8. git commit + push, отчёт в Telegram.
"""

import csv
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUP = ROOT / "suppliers" / "metallservis"
CATALOG = ROOT / "catalog" / "metallservis.csv"
STATE = SUP / "last_zip.sha256"
PRICE_PAGE = "https://mc.ru/price/msk"
ZIP_FALLBACK = ["https://mc.ru/prices/metserv.zip"]  # имя архива с сайта: metserv.zip
# на странице несколько zip (резка и т.п.) — общий прайс узнаём по составу файлов
EXPECTED_XLS = {"truby.xls", "sortovojprokat.xls", "listovojprokat.xls", "krepezh.xls", "nerzhaveika.xls"}
BRANCHES = json.loads((SUP / "branches.json").read_text(encoding="utf-8"))
WAREHOUSES = ["Москва"] + [b["city"] for b in BRANCHES]
KZ_HUBS = ["Алматы", "Астана", "Караганда", "Шымкент", "Павлодар"]
FAFA_ROUTES = [(w, c) for w in WAREHOUSES for c in KZ_HUBS]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

sys.path.insert(0, str(ROOT / "scripts"))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def curl(url):
    return subprocess.run(["curl", "-sS", "-f", "-L", "-m", "120", "-A", UA, url],
                          capture_output=True, check=True).stdout


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


# ---------- прайс Металл Сервис ----------

def find_zip_urls():
    try:
        page = curl(PRICE_PAGE).decode("utf-8", "ignore")
        found = re.findall(r'href="([^"]+\.zip)"', page, re.I)
        return [urllib.parse.urljoin(PRICE_PAGE, u) for u in found] + ZIP_FALLBACK
    except subprocess.CalledProcessError:
        return ZIP_FALLBACK


def fetch_mc(today):
    """Скачать архив, распаковать в raw/<дата>. None — если архив не изменился."""
    tried = []
    for url in dict.fromkeys(find_zip_urls()):
        try:
            zf = zipfile.ZipFile(io.BytesIO(curl(url)))
        except (subprocess.CalledProcessError, zipfile.BadZipFile) as e:
            tried.append(f"{url}: {e}")
            continue
        names = {Path(n).name.lower() for n in zf.namelist()}
        if len(names & EXPECTED_XLS) >= 3:
            break
        tried.append(f"{url}: не общий прайс ({', '.join(sorted(names))[:120]})")
    else:
        raise RuntimeError("не нашёл общий прайс mc.ru. Проверено: " + "; ".join(tried))
    xls = [n for n in zf.namelist() if n.lower().endswith(".xls")]
    digest = hashlib.sha256(b"".join(zf.read(n) for n in sorted(xls))).hexdigest()
    if STATE.exists() and STATE.read_text().strip() == digest:
        return None
    out = SUP / "raw" / today
    out.mkdir(parents=True, exist_ok=True)
    for n in xls:
        (out / Path(n).name).write_bytes(zf.read(n))
    return out, digest


def read_catalog(path):
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def key(r):
    return (r["file"], r["section"], r["name"], r["size"], r["unit"])


def min_prices(rows):
    out = {}
    for r in rows:
        p = float(r["price_rub"])
        if p > 0:
            out[key(r)] = min(p, out.get(key(r), p))
    return out


def validate(old, new):
    problems = []
    if old and len(new) < 0.8 * len(old):
        problems.append(f"позиций стало {len(new)} против {len(old)} (−{100 - 100 * len(new) / len(old):.0f}%)")
    o, n = min_prices(old), min_prices(new)
    common = [k for k in n if k in o]
    jumps = [k for k in common if abs(n[k] / o[k] - 1) > 0.30]
    if common and len(jumps) > 0.10 * len(common):
        problems.append(f"у {len(jumps)} из {len(common)} позиций цена изменилась >30% — похоже на сдвиг колонок")
    return problems


def diff_report(old, new):
    o, n = min_prices(old), min_prices(new)
    common = [k for k in n if k in o]
    up = sorted((n[k] / o[k] - 1, k) for k in common if n[k] > o[k])
    down = sorted((n[k] / o[k] - 1, k) for k in common if n[k] < o[k])
    lines = [f"подорожало {len(up)}, подешевело {len(down)}, новых {len(set(n) - set(o))}, "
             f"пропало {len(set(o) - set(n))}"]
    for ch, k in up[-3:][::-1] + down[:3]:
        lines.append(f"  {ch:+.0%} {k[1]} | {k[2]} {k[3]} → {n[k]:,.0f} ₽/{k[4]}".replace(",", " "))
    return "\n".join(lines)


def update_mc(today, report):
    got = fetch_mc(today)
    if got is None:
        report.append("Металл Сервис: прайс не изменился")
        return
    raw, digest = got
    parser = load_module(SUP / "parser.py", "mc_parser")
    tmp = Path(tempfile.mkdtemp()) / "metallservis.csv"
    parser.main(str(raw), str(tmp))
    old, new = read_catalog(CATALOG), read_catalog(tmp)
    problems = validate(old, new)
    if problems:
        report.append("⚠️ Металл Сервис: прайс НЕ обновлён — " + "; ".join(problems) +
                      f". Сырые файлы сохранены в {raw.relative_to(ROOT)}, нужна проверка парсера.")
        return
    report.append(f"Металл Сервис: {len(new)} позиций, " + diff_report(old, new))
    shutil.move(tmp, CATALOG)
    STATE.write_text(digest + "\n")  # только после успешной проверки — битый архив скачаем снова


def update_branch(b, today):
    """Прайс одного филиала: скачать xls → разобрать → проверить → catalog/metallservis_<slug>.csv. Строка отчёта."""
    data = curl(b["url"])
    digest = hashlib.sha256(data).hexdigest()
    state = SUP / f"last_{b['slug']}.sha256"
    if state.exists() and state.read_text().strip() == digest:
        return f"{b['city']}: не изменился"
    raw = SUP / "raw" / today / "filials" / b["slug"]
    raw.mkdir(parents=True, exist_ok=True)
    (raw / Path(urllib.parse.urlparse(b["url"]).path).name).write_bytes(data)
    parser = load_module(SUP / "parser.py", "mc_parser")
    tmp = Path(tempfile.mkdtemp()) / "branch.csv"
    parser.main(str(raw), str(tmp), b["city"])
    target = ROOT / "catalog" / f"metallservis_{b['slug']}.csv"
    old, new = read_catalog(target), read_catalog(tmp)
    problems = validate(old, new)
    if problems:
        return f"⚠️ {b['city']}: НЕ обновлён — " + "; ".join(problems)
    shutil.move(tmp, target)
    state.write_text(digest + "\n")
    return f"{b['city']}: {len(new)} позиций, " + diff_report(old, new).split("\n")[0]


def update_branches(today, report):
    lines = []
    for b in BRANCHES:
        try:
            lines.append(update_branch(b, today))
        except Exception as e:  # один филиал упал — остальные обновляем
            lines.append(f"⚠️ {b['city']}: {e}")
    report.append("Филиалы: " + "; ".join(lines))


def prune_raw(keep_days=30):
    cutoff = dt.date.today() - dt.timedelta(days=keep_days)
    months = {}
    for d in sorted((SUP / "raw").iterdir()):
        try:
            day = dt.date.fromisoformat(d.name)
        except ValueError:
            continue
        first_of_month = months.setdefault(day.strftime("%Y-%m"), d) == d
        if day < cutoff and not first_of_month:
            shutil.rmtree(d)


# ---------- ставки на перевозки ----------

def update_freight(report):
    della = load_module(ROOT / "scripts" / "freight_della.py", "della")
    rows, added = della.save(della.fetch())
    report.append(f"Della: +{added} сделок по Казахстану (всего {len(rows)})")
    fafa = load_module(ROOT / "scripts" / "freight_fafa.py", "fafa")
    got, best, failed = {}, {}, 0
    for f, t in FAFA_ROUTES:
        try:
            q = fafa.quote(f, t)
            fafa.save(q)
            got[(f, t)] = q["t20"]
            if t not in best or q["t20"] < got[(best[t], t)]:
                best[t] = f
        except Exception:  # маршрут мог пропасть с биржи — не валим всё обновление
            failed += 1
        time.sleep(0.5)
    line = "; ".join(f"→{t}: Москва {got[('Москва', t)] / 1e6:.2f}, дешевле всего {best[t]} "
                     f"{got[(best[t], t)] / 1e6:.2f} млн ₸" for t in KZ_HUBS if ("Москва", t) in got and t in best)
    report.append("Фура 20 т (fa-fa): " + line + (f" (не ответило маршрутов: {failed})" if failed else ""))


# ---------- отчёт ----------

def notify(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20)


def main():
    today = dt.date.today().isoformat()
    report = [f"Обновление metal-catalog {today}"]
    git("pull", "--rebase", "--autostash")
    for step in (update_mc, update_branches, update_freight):
        try:
            step(report) if step is update_freight else step(today, report)
        except Exception as e:
            report.append(f"⚠️ {step.__name__}: {e}")
            traceback.print_exc()
    prune_raw()
    git("add", "-A")
    if git("status", "--porcelain").strip():
        git("-c", "user.name=metal-catalog bot", "-c", "user.email=bot@metal-catalog",
            "commit", "-qm", f"Daily update {today}")
        git("push", "origin", "HEAD")
        report.append("Изменения отправлены в GitHub")
    text = "\n".join(report)
    print(text)
    notify(text)


if __name__ == "__main__":
    main()
