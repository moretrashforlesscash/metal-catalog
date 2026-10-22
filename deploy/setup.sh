#!/usr/bin/env bash
# Установка metal-catalog на чистый сервер Ubuntu 22.04/24.04. Запуск от root:
#   curl -fsSL https://raw.githubusercontent.com/moretrashforlesscash/metal-catalog/main/deploy/setup.sh -o setup.sh
#   bash setup.sh
# Репозиторий приватный — если curl не скачает файл, скопируйте его содержимое вручную (см. deploy/README.md).
set -euo pipefail

REPO="git@github.com:moretrashforlesscash/metal-catalog.git"
USER_NAME="metal"
HOME_DIR="/home/$USER_NAME"
APP="$HOME_DIR/metal-catalog"
ENV_FILE="$HOME_DIR/.metal-catalog.env"

echo "== 1/6 Пакеты"
apt-get update -qq
apt-get install -y -qq git curl python3 python3-venv zip unzip >/dev/null
timedatectl set-timezone Asia/Almaty || true
systemctl restart cron 2>/dev/null || true

echo "== 2/6 Пользователь $USER_NAME"
id "$USER_NAME" >/dev/null 2>&1 || useradd -m -s /bin/bash "$USER_NAME"

echo "== 3/6 Ключ доступа к GitHub"
sudo -u "$USER_NAME" bash -c '
  mkdir -p ~/.ssh && chmod 700 ~/.ssh
  [ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -C "metal-catalog-server" -f ~/.ssh/id_ed25519
  ssh-keyscan -q github.com >> ~/.ssh/known_hosts 2>/dev/null
'
echo
echo "Скопируйте строку ниже и добавьте её на GitHub:"
echo "  репозиторий metal-catalog → Settings → Deploy keys → Add deploy key"
echo "  Title: server, Key: строка ниже, ✓ Allow write access → Add key"
echo
cat "$HOME_DIR/.ssh/id_ed25519.pub"
echo
read -r -p "Нажмите Enter, когда ключ добавлен... "

echo "== 4/6 Код и зависимости"
if [ ! -d "$APP/.git" ]; then
  sudo -u "$USER_NAME" git clone -q "$REPO" "$APP"
fi
sudo -u "$USER_NAME" bash -c "cd '$APP' && python3 -m venv .venv && .venv/bin/pip -q install -r requirements.txt"

echo "== 5/6 Telegram (можно пропустить — Enter)"
read -r -p "Токен бота от @BotFather: " TG_TOKEN
TG_CHAT=""
if [ -n "$TG_TOKEN" ]; then
  read -r -p "Напишите боту любое сообщение в Telegram и нажмите Enter... "
  TG_CHAT=$(curl -fsS "https://api.telegram.org/bot$TG_TOKEN/getUpdates" |
            python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print(r[-1]["message"]["chat"]["id"] if r else "")')
  echo "chat_id: ${TG_CHAT:-не найден — впишите вручную в $ENV_FILE}"
fi
cat > "$ENV_FILE" <<EOF
TELEGRAM_TOKEN=$TG_TOKEN
TELEGRAM_CHAT_ID=$TG_CHAT
EOF
chown "$USER_NAME:$USER_NAME" "$ENV_FILE" && chmod 600 "$ENV_FILE"

echo "== 6/6 Расписание (каждый день 11:17 и 16:17 по Алматы)"
RUN="cd $APP && set -a && . $ENV_FILE && set +a && .venv/bin/python scripts/update.py >> $HOME_DIR/update.log 2>&1"
( crontab -u "$USER_NAME" -l 2>/dev/null | grep -v "scripts/update.py" || true
  echo "CRON_TZ=Asia/Almaty"
  echo "17 11,16 * * * $RUN" ) | crontab -u "$USER_NAME" -

echo
echo "Пробный запуск..."
sudo -u "$USER_NAME" bash -c "$RUN" || true
tail -n 20 "$HOME_DIR/update.log"
echo
echo "Готово. Лог: $HOME_DIR/update.log. Ручной запуск: sudo -u $USER_NAME bash -c \"$RUN\""
