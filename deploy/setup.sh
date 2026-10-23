#!/usr/bin/env bash
# Установка metal-catalog на сервер Ubuntu 22.04/24.04. Запуск от root.
# Обычно запускается из уже склонированного репозитория (см. deploy/README.md, шаги 3–5):
#   bash /home/metal/metal-catalog/deploy/setup.sh
# Можно и на чистом сервере — тогда скрипт сам создаст ключ и попросит добавить его на GitHub.
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

echo "== 2/6 Пользователь $USER_NAME и запасная память"
id "$USER_NAME" >/dev/null 2>&1 || useradd -m -s /bin/bash "$USER_NAME"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "== 3/6 Ключ доступа к GitHub"
sudo -u "$USER_NAME" bash -c '
  mkdir -p ~/.ssh && chmod 700 ~/.ssh
  [ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -C "metal-catalog-server" -f ~/.ssh/id_ed25519
  ssh-keyscan -q github.com >> ~/.ssh/known_hosts 2>/dev/null || true
' || true
if [ ! -d "$APP/.git" ]; then
  echo
  echo "Скопируйте строку ниже и добавьте её на GitHub:"
  echo "  репозиторий metal-catalog → Settings → Deploy keys → Add deploy key"
  echo "  Title: server, Key: строка ниже, ✓ Allow write access → Add key"
  echo
  cat "$HOME_DIR/.ssh/id_ed25519.pub"
  echo
  read -r -p "Нажмите Enter, когда ключ добавлен... "
fi

echo "== 4/6 Код и зависимости"
if [ ! -d "$APP/.git" ]; then
  sudo -u "$USER_NAME" git clone -q "$REPO" "$APP"
fi
sudo -u "$USER_NAME" bash -c "cd '$APP' && python3 -m venv .venv && .venv/bin/pip -q install -r requirements.txt"

echo "== 5/6 Ключи (можно пропустить — Enter, вписать потом в $ENV_FILE)"
read -r -p "Ключ Claude API (sk-ant-...): " ANTHROPIC_KEY
read -r -p "Токен бота от @BotFather: " TG_TOKEN
TG_CHAT=""
if [ -n "$TG_TOKEN" ]; then
  read -r -p "Напишите боту любое сообщение в Telegram и нажмите Enter... "
  TG_CHAT=$(curl -fsS "https://api.telegram.org/bot$TG_TOKEN/getUpdates" |
            python3 -c 'import json,sys; r=[u for u in json.load(sys.stdin)["result"] if "message" in u]; print(r[-1]["message"]["chat"]["id"] if r else "")' || true)
  echo "chat_id: ${TG_CHAT:-не найден — впишите вручную в $ENV_FILE}"
fi
cat > "$ENV_FILE" <<EOF
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
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
