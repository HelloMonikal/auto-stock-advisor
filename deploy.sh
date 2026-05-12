#!/bin/bash
# 智能股票助手 - 阿里云服务器一键部署脚本
# 使用方式：bash deploy.sh
set -e

APP_DIR="/opt/stock-advisor"
IMAGE="hellomonika/stock-advisor:latest"

echo "======================================"
echo "  智能股票助手 一键部署"
echo "======================================"

# ── 1. 安装 Docker ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "[1/5] 安装 Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
  echo "Docker 安装完成"
else
  echo "[1/5] Docker 已安装 $(docker --version)"
fi

# ── 2. 创建应用目录 ────────────────────────────────────────────────────────
echo "[2/5] 创建应用目录 $APP_DIR ..."
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# ── 3. 写入 docker-compose.yml ────────────────────────────────────────────
echo "[3/5] 写入 docker-compose.yml ..."
cat > docker-compose.yml << 'EOF'
services:
  web:
    image: hellomonika/stock-advisor:latest
    command: python3 -m streamlit run app.py
    ports:
      - "8501:8501"
    env_file: .env
    volumes:
      - stock_data:/app/.tmp
      - stock_logs:/app/logs
    restart: unless-stopped

volumes:
  stock_data:
  stock_logs:
EOF

# ── 4. 检查 .env ──────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo ""
  echo "⚠️  未找到 .env 文件，正在生成模板..."
  cat > .env << 'ENVEOF'
DEEPSEEK_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
APP_PASSWORD=
ENVEOF
  echo ""
  echo "请编辑 $APP_DIR/.env 填入密钥后重新运行此脚本："
  echo "  nano $APP_DIR/.env"
  echo ""
  exit 1
fi

# 检查关键变量是否已填写
if grep -q "^DEEPSEEK_API_KEY=$" .env; then
  echo "⚠️  .env 中 DEEPSEEK_API_KEY 为空，请先填写后重新运行。"
  echo "  nano $APP_DIR/.env"
  exit 1
fi

# ── 5. 拉取镜像并启动 ─────────────────────────────────────────────────────
echo "[4/5] 拉取最新镜像..."
docker pull "$IMAGE"

echo "[5/5] 启动服务..."
docker compose down 2>/dev/null || true
docker compose up -d

echo ""
echo "======================================"
echo "  部署完成！"
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "your-server-ip")
echo "  访问地址：http://${PUBLIC_IP}:8501"
echo ""
echo "  查看日志：docker compose -f $APP_DIR/docker-compose.yml logs -f"
echo "  停止服务：docker compose -f $APP_DIR/docker-compose.yml down"
echo "  更新版本：docker pull $IMAGE && docker compose -f $APP_DIR/docker-compose.yml up -d"
echo "======================================"
