"""Разведка HTML-версии прайса mc.ru (запускать на сервере: с зарубежных IP сайт не открывается).

    sudo -u metal bash -c "cd ~/metal-catalog && git pull -q && .venv/bin/python scripts/mc_html_probe.py"

Скачивает страницу прайсов и HTML-версии разделов (листовой прокат, трубы, сортовой и т.д.) в
suppliers/metallservis/html_samples/, список всех ссылок — в links.txt, и отправляет в GitHub,
чтобы по образцам написать парсер.
"""

import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "suppliers" / "metallservis" / "html_samples"
PAGE = "https://mc.ru/price/msk"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MAX_PAGES = 15


def curl(url):
    r = subprocess.run(["curl", "-sS", "-L", "-m", "90", "-A", UA, "-w", "\n%{http_code} %{content_type}", url],
                       capture_output=True)
    body, _, meta = r.stdout.rpartition(b"\n")
    return body, meta.decode(errors="ignore")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    body, meta = curl(PAGE)
    (OUT / "price_msk.html").write_bytes(body)
    html = body.decode("utf-8", "ignore")
    print(f"страница прайсов: {meta}, {len(body)} байт")

    links = []
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        url = urllib.parse.urljoin(PAGE, href)
        label = re.sub(r"<[^>]+>|\s+", " ", text).strip()
        links.append((url, label))
    (OUT / "links.txt").write_text("\n".join(f"{u}\t{t}" for u, t in links), encoding="utf-8")
    print(f"ссылок на странице: {len(links)}")

    # HTML-версии разделов: ссылки с текстом HTML или ведущие на страницы прайсов (не xls/zip/pdf)
    cand = []
    for u, t in links:
        low = u.lower()
        if re.search(r"\.(xls|xlsx|zip|pdf|jpg|png)(\?|$)", low) or not low.startswith("https://mc.ru"):
            continue
        if t.upper() == "HTML" or "price" in low or "prices" in low:
            cand.append(u)
    cand = list(dict.fromkeys(cand))[:MAX_PAGES]
    for i, u in enumerate(cand, 1):
        body, meta = curl(u)
        name = f"page_{i:02d}.html"
        (OUT / name).write_bytes(body)
        print(f"{name}: {u} → {meta}, {len(body)} байт")
    (OUT / "pages.txt").write_text("\n".join(f"page_{i:02d}.html\t{u}" for i, u in enumerate(cand, 1)),
                                   encoding="utf-8")

    subprocess.run(["git", "-C", str(ROOT), "add", str(OUT)], check=True)
    subprocess.run(["git", "-C", str(ROOT), "-c", "user.name=metal-catalog bot", "-c", "user.email=bot@metal-catalog",
                    "commit", "-qm", "Add mc.ru HTML price samples"], check=False)
    r = subprocess.run(["git", "-C", str(ROOT), "push", "-q", "origin", "HEAD"])
    print("отправлено в GitHub" if r.returncode == 0 else "не удалось отправить в GitHub")


if __name__ == "__main__":
    sys.exit(main())
