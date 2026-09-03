#!/usr/bin/env bash
# =============================================================================
# Oracle Cloud Free Tier (Ubuntu 24.04) Discord Bot kurulum scripti
#
# ADIMLAR:
#   1) Oracle Cloud konsolundan "Always Free" ARM Ampere VM (Ubuntu 24.04)
#      oluşturun. Ubuntu 24.04 varsayılan olarak Python 3.12 ile gelir.
#   2) SSH ile sunucuya girin ve kodu taşıyın:
#        scp -r DiscordBot kullanici@IP:/tmp/
#      (İsterseniz önce git repo açıp `git clone` da yapabilirsiniz.)
#   3) config.json VE data/ klasörünü kopyalamayı unutmayın:
#        scp -r DiscordBot/config.json DiscordBot/data kullanici@IP:/tmp/DiscordBot/
#      data/bot.db içindeki tüm mevcut verileriniz böylece korunur.
#   4) Scripti proje kökünden root olarak çalıştırın:
#        sudo bash /tmp/DiscordBot/deploy/install.sh
#
# NOT: YouTube zaman zaman veri merkezi (bulut) IP'lerini engellediği için
#      müzik özelliği bu sunucuda arada bir çalışmayabilir. music.py'de
#      android player_client kullanılarak 403 hatası büyük ölçüde giderildi;
#      yine de garanti değildir. Diğer tüm özellikler sorunsuz çalışır.
# =============================================================================
set -euo pipefail

APP_DIR="/opt/discordbot"
SERVICE="discordbot"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Sistem paketleri kuruluyor..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip \
    ffmpeg libopus0 libopus-dev \
    git curl rsync \
    fonts-dejavu-core fonts-liberation fonts-noto-core

echo "==> Uygulama kullanıcısı oluşturuluyor..."
id -u discordbot &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin discordbot

echo "==> Proje /opt/discordbot içine kopyalanıyor..."
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
    --exclude 'deploy' \
    "$SRC_DIR/" "$APP_DIR/"
mkdir -p "$APP_DIR/data"
chown -R discordbot:discordbot "$APP_DIR"

echo "==> Python ortamı kuruluyor..."
if [ ! -d "$APP_DIR/.venv" ]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> systemd servisi kuruluyor..."
cp "$SRC_DIR/deploy/discordbot.service" /etc/systemd/system/discordbot.service
systemctl daemon-reload
systemctl enable discordbot
systemctl restart discordbot

echo ""
echo "==> Durum:"
systemctl --no-pager status "$SERVICE" || true
echo ""
echo "Loglar:            journalctl -u discordbot -f"
echo "Yeniden başlat:    sudo systemctl restart discordbot"
echo "Durdur:            sudo systemctl stop discordbot"
echo "Açılışta otomatik: zaten açık (enable edildi)"
