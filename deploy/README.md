# Сервер для автообновления

Что делает сервер каждый день (11:17 и 16:17 по Алматы):
1. скачивает общий прайс mc.ru (с зарубежных IP сайт не открывается — поэтому сервер в Казахстане);
2. разбирает его, проверяет на ошибки и обновляет каталог;
3. собирает ставки на перевозки (Della — сделки по Казахстану, fa-fa — фуры из России);
4. отправляет всё в GitHub и присылает отчёт в Telegram: что подорожало, что подешевело, тревоги.

Telegram-бот, которому можно писать «труба 40х20х2, 5 т, до Караганды», — следующий этап, ставится на этот же сервер.

## Шаг 1. Арендовать сервер (~3 000–5 000 ₸/мес)
Любой VPS **в Казахстане**: например, PS Cloud (ps.kz, от 3 120 ₸/мес) или другой казахстанский хостинг.
- Система: **Ubuntu 24.04**
- Минимум: 1 vCPU, 1–2 ГБ RAM, 20 ГБ диска — хватит с запасом
После оплаты хостинг пришлёт **IP-адрес и пароль root**.

## Шаг 2. Telegram-бот для отчётов (2 минуты)
1. В Telegram найдите **@BotFather** → `/newbot` → придумайте имя → получите **токен** вида `123456:ABC...`.
2. Сохраните токен — его спросит установщик.

## Шаг 3. Подключиться к серверу
Windows: Пуск → «Терминал» (или PowerShell) → `ssh root@IP-АДРЕС` → на вопрос `yes` → пароль root
(при вводе пароль не отображается — это нормально; вставка — правый клик).

## Шаг 4. Создать ключ доступа к GitHub — вставить в терминал целиком:
```
apt-get update -qq && apt-get install -y -qq git
id metal >/dev/null 2>&1 || useradd -m -s /bin/bash metal
sudo -u metal bash -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && [ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519; ssh-keyscan -q github.com >> ~/.ssh/known_hosts 2>/dev/null; cat ~/.ssh/id_ed25519.pub'
```
Последняя строка вывода — `ssh-ed25519 AAAA... ` — это ключ. Добавьте его на GitHub:
репозиторий → **Settings → Deploy keys → Add deploy key**, Title `server`, вставить ключ,
✓ **Allow write access** → **Add key**.

## Шаг 5. Скачать код и запустить установку:
```
sudo -u metal git clone git@github.com:moretrashforlesscash/metal-catalog.git /home/metal/metal-catalog && bash /home/metal/metal-catalog/deploy/setup.sh
```
Установщик спросит ключ Claude API и токен Telegram-бота (можно пропустить Enter и вписать потом),
попросит написать боту сообщение и в конце сделает пробный запуск.

## Если что-то пошло не так
- Лог: `tail -n 50 /home/metal/update.log`
- Ручной запуск: `sudo -u metal bash -c "cd ~/metal-catalog && set -a && . ~/.metal-catalog.env && .venv/bin/python scripts/update.py"`
- Скиньте Claude текст ошибки из лога — он поправит код, сервер подхватит исправление при следующем запуске сам (`git pull`).
