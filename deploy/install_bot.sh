#!/usr/bin/env bash
# Установка/обновление Telegram-бота как службы. Запуск от root:
#   bash /home/metal/metal-catalog/deploy/install_bot.sh
set -euo pipefail
APP=/home/metal/metal-catalog
sudo -u metal git -C "$APP" pull -q
sudo -u metal "$APP/.venv/bin/pip" -q install -r "$APP/requirements.txt"
cp "$APP/deploy/metal-bot.service" /etc/systemd/system/metal-bot.service
systemctl daemon-reload
systemctl enable -q metal-bot
systemctl restart metal-bot
# раз в сутки перезапуск, чтобы бот подхватил обновлённый код (git pull делает ежедневное обновление)
( crontab -l 2>/dev/null | grep -v "restart metal-bot" || true
  echo "45 5 * * * systemctl restart metal-bot" ) | crontab -
sleep 3
systemctl --no-pager --lines=5 status metal-bot | head -n 12
echo
echo "Готово. Напишите боту в Telegram: профтруба 40х20х2, 5 т, Караганда"
echo "Лог бота: journalctl -u metal-bot -n 50"
