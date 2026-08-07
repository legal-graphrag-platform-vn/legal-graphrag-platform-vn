#!/usr/bin/env bash
# ==============================================================================
# Script triển khai (Deploy) dự án Legal GraphRAG lên Server qua SSH
# ==============================================================================

set -euo pipefail

KEY_PATH="${KEY_PATH:-$HOME/.ssh/id_ed25519_deploy}"
DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_USER="${DEPLOY_USER:-}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/opt/legal-graphrag}"

# Lấy root dir của dự án
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "=== Deployment Pipeline: Legal GraphRAG ==="

if [ -z "$DEPLOY_HOST" ] || [ -z "$DEPLOY_USER" ]; then
    echo "Lỗi: Thiếu thông tin máy chủ từ xa."
    echo "Cú pháp: DEPLOY_HOST=<host> DEPLOY_USER=<user> [DEPLOY_PORT=22] [REMOTE_DIR=/opt/legal-graphrag] ./infra/scripts/deploy-ssh.sh"
    exit 1
fi

SSH_CMD="ssh -i $KEY_PATH -p $DEPLOY_PORT -o StrictHostKeyChecking=accept-new"

# 1.   Kiểm tra kết nối SSH
echo "--> [1/4] Kiểm tra kết nối SSH tới $DEPLOY_USER@$DEPLOY_HOST..."
if ! $SSH_CMD "$DEPLOY_USER@$DEPLOY_HOST" "echo Connection OK" >/dev/null; then
    echo "❌ Lỗi: Không thể kết nối SSH. Hãy kiểm tra SSH Key hoặc IP Server."
    exit 1
fi

# 2.   Tạo thư mục trên Server từ xa
echo "--> [2/4] Đảm bảo thư mục mục tiêu $REMOTE_DIR tồn tại trên Server..."
$SSH_CMD "$DEPLOY_USER@$DEPLOY_HOST" "mkdir -p $REMOTE_DIR"

# 3.   Đồng bộ mã nguồn bằng rsync
echo "--> [3/4] Đồng bộ mã nguồn lên Server (rsync)..."
rsync -avz -e "ssh -i $KEY_PATH -p $DEPLOY_PORT" \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='.cache' \
    --exclude='node_modules' \
    --exclude='apps/frontend/.next' \
    --exclude='infra/data' \
    --exclude='results' \
    --exclude='experiments' \
    "$PROJECT_ROOT/" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_DIR/"

# 4.   Khởi chạy Docker Compose trên Server
echo "--> [4/4] Khởi động các dịch vụ trên Server..."
$SSH_CMD "$DEPLOY_USER@$DEPLOY_HOST" "cd $REMOTE_DIR && if docker compose version >/dev/null 2>&1; then docker compose -f infra/docker-compose.yml up -d --build; else docker-compose -f infra/docker-compose.yml up -d --build; fi"

# 5.   Kiểm tra trạng thái Container trên Server
echo "================================================================="
echo "✅ Triển khai hoàn tất! Trạng thái các container trên Server:"
$SSH_CMD "$DEPLOY_USER@$DEPLOY_HOST" "cd $REMOTE_DIR && docker compose -f infra/docker-compose.yml ps || docker-compose -f infra/docker-compose.yml ps"
echo "================================================================="
