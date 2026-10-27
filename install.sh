#!/usr/bin/env bash
# nodeseek-hub one-shot install / update for Debian 12+ / Ubuntu 22.04+ (run as root).
#   git clone <repo> /opt/nodeseek-hub && cd /opt/nodeseek-hub && bash install.sh
# Re-run it after `git pull` to update: it rebuilds the frontend, updates Python deps and restarts the service.
# Options (environment variables): PORT=8001  SKIP_CHROME=1
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8001}"
SERVICE=nodeseek-hub

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m错误：%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "请用 root 运行（sudo bash install.sh）"
command -v apt-get >/dev/null || die "只支持 Debian / Ubuntu（需要 apt-get）"

say "安装系统依赖"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3 python3-venv python3-pip python3-dev python3-tk xvfb \
  curl wget ca-certificates openssl git >/dev/null

python3 - <<'PY' || die "需要 Python 3.10 以上"
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY

# Chrome: logging in to NodeSeek goes through a real browser (Cloudflare Turnstile)
if [ "${SKIP_CHROME:-0}" != 1 ] && ! command -v google-chrome >/dev/null && ! command -v chromium >/dev/null; then
  say "安装浏览器（登录 NodeSeek 要过人机验证）"
  if [ "$(dpkg --print-architecture)" = amd64 ]; then
    tmp="$(mktemp -d)"
    wget -q -O "$tmp/chrome.deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$tmp/chrome.deb" >/dev/null
    rm -rf "$tmp"
  else
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chromium >/dev/null \
      || echo "没装上 Chromium：签到和发布需要浏览器登录，之后手动安装"
  fi
fi

# Node.js >= 20.19 is only needed to build the frontend
node_ok() { command -v node >/dev/null && node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>20||(a==20&&b>=19)?0:1)'; }
if ! node_ok; then
  say "安装 Node.js 22（构建前端用）"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
fi

say "构建前端"
cd "$APP_DIR/frontend"
npm ci --no-audit --no-fund --loglevel=error
npm run build

say "安装后端依赖"
cd "$APP_DIR/backend"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

NEW_ENV=0
if [ ! -f .env ]; then
  say "生成 backend/.env"
  cp .env.example .env
  pw="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"
  sed -i "s|^APP_PASSWORD=.*|APP_PASSWORD=$pw|" .env
  chmod 600 .env
  NEW_ENV=1
fi

say "配置 systemd 服务（127.0.0.1:$PORT）"
cat >/etc/systemd/system/$SERVICE.service <<EOF
[Unit]
Description=nodeseek-hub
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/backend/.env
ExecStart=$APP_DIR/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT --proxy-headers
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q $SERVICE
systemctl restart $SERVICE
sleep 2
systemctl is-active -q $SERVICE || { journalctl -u $SERVICE -n 30 --no-pager; die "服务没有启动成功，看上面的日志"; }

say "完成"
echo "服务：systemctl status $SERVICE    日志：journalctl -u $SERVICE -f"
echo "面板只监听 127.0.0.1:$PORT，用 Nginx 反代并配 HTTPS 后访问（见 README），或先用 SSH 隧道："
echo "  ssh -L $PORT:127.0.0.1:$PORT root@服务器IP   然后打开 http://localhost:$PORT"
if [ "$NEW_ENV" = 1 ]; then
  echo
  echo "已生成面板密码：$(grep '^APP_PASSWORD=' .env | cut -d= -f2-)"
  echo "还要在 $APP_DIR/backend/.env 里填 LLM_API_KEY，然后 systemctl restart $SERVICE"
elif ! grep -q '^LLM_API_KEY=.\+' .env; then
  echo
  echo "提示：backend/.env 里的 LLM_API_KEY 还是空的"
fi
