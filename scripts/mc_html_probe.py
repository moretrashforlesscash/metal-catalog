"""Разведка mc.ru (запускать на сервере: с зарубежных IP сайт не открывается).

    sudo -u metal bash -c "cd ~/metal-catalog && git pull -q && .venv/bin/python scripts/mc_html_probe.py"

Скачивает в suppliers/metallservis/html_samples/:
- прайсы филиалов ближе к Казахстану (Екатеринбург, Челябинск, Омск, Новосибирск, Уфа, Барнаул) — xls/htm;
- HTML-версию листового проката (prices/listovojprokat.htm);
- страницы каталога листа (metalloprokat/listovoy) и по одной вложенной странице/карточке товара —
чтобы понять, где есть форматы листов, длины и заводы. Затем отправляет образцы в GitHub.
"""

import re
import subprocess
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "suppliers" / "metallservis" / "html_samples"
BASE = "https://mc.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CITIES = ["ekaterinburg", "chelyabinsk", "omsk", "novosibirsk", "ufa", "barnaul"]


def curl(url):
    r = subprocess.run(["curl", "-sS", "-L", "-m", "90", "-A", UA, "-w", "\n%{http_code} %{content_type}", url],
                       capture_output=True)
    body, _, meta = r.stdout.rpartition(b"\n")
    return body, meta.decode(errors="ignore")


def save(name, url, log):
    body, meta = curl(url)
    (OUT / name).write_bytes(body)
    line = f"{name}\t{url}\t{meta}\t{len(body)} байт"
    log.append(line)
    print(line)
    return body.decode("utf-8", "ignore")


def links(html, pattern):
    found = re.findall(r"""href=["']([^"']+)["']""", html)
    return list(dict.fromkeys(urllib.parse.urljoin(BASE, u) for u in found if re.search(pattern, u)))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("page_*.html"):  # образцы прошлой разведки (страницы городов) больше не нужны
        old.unlink()
    log = []
    for city in CITIES:
        html = save(f"city_{city}.html", f"{BASE}/price/{city}", log)
        for u in links(html, r"/prices/filials/[^\"']+\.(xls|htm)"):
            save(f"filial_{Path(urllib.parse.urlparse(u).path).name}", u, log)
    save("listovojprokat.htm", f"{BASE}/prices/listovojprokat.htm?v=2", log)
    html = save("catalog_listovoy.html", f"{BASE}/metalloprokat/listovoy", log)
    sub = [u for u in links(html, r"^/metalloprokat/listovoy/") if u.rstrip("/") != f"{BASE}/metalloprokat/listovoy"]
    (OUT / "catalog_listovoy_links.txt").write_text("\n".join(sub), encoding="utf-8")
    for i, u in enumerate(sub[:3], 1):
        html2 = save(f"catalog_listovoy_sub{i}.html", u, log)
        if i == 1:
            items = [x for x in links(html2, r"^/metalloprokat/") if x not in sub and "listovoy" in x]
            if items:
                save("catalog_item1.html", items[-1], log)
    (OUT / "probe_log.txt").write_text("\n".join(log), encoding="utf-8")

    subprocess.run(["git", "-C", str(ROOT), "add", "-A", str(OUT)], check=True)
    subprocess.run(["git", "-C", str(ROOT), "-c", "user.name=metal-catalog bot", "-c", "user.email=bot@metal-catalog",
                    "commit", "-qm", "Add mc.ru branch prices and catalog samples"], check=False)
    r = subprocess.run(["git", "-C", str(ROOT), "push", "-q", "origin", "HEAD"])
    print("отправлено в GitHub" if r.returncode == 0 else "не удалось отправить в GitHub")


if __name__ == "__main__":
    main()
