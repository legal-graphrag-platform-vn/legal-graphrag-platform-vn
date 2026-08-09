#!/usr/bin/env bash
# ==============================================================================
# Script triển khai sản xuất (Deploy) qua SSH sử dụng GHCR Docker Images
# ==============================================================================

set -euo pipefail

KEY_PATH="${KEY_PATH:-$HOME/.ssh/id_ed25519_deploy}"
DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_USER="${DEPLOY_USER:-}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/opt/legal-graphrag}"
GHCR_PAT="${GHCR_PAT:-}"
GHCR_USER="${GHCR_USER:-$DEPLOY_USER}"
TAG="${TAG:-latest}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "=== Deployment Pipeline: Legal GraphRAG (GHCR Mode) ==="

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
$SSH_CMD "$DEPLOY_USER@$DEPLOY_HOST" "mkdir -p $REMOTE_DIR/infra"

# 3.   Đồng bộ file cấu hình sản xuất nhẹ (docker-compose.prod.yml & .env)
echo "--> [3/4] Đồng bộ file cấu hình Production lên Server..."
rsync -avz -e "ssh -i $KEY_PATH -p $DEPLOY_PORT" \
    "$PROJECT_ROOT/infra/prod/docker-compose.yml" \
    "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_DIR/infra/prod/docker-compose.yml"

if [ -f "$PROJECT_ROOT/infra/.env" ]; then
    rsync -avz -e "ssh -i $KEY_PATH -p $DEPLOY_PORT" \
        "$PROJECT_ROOT/infra/.env" \
        "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_DIR/infra/.env"
fi

# 4.   Đăng nhập GHCR (nếu có PAT) & Pull images & Khởi động Docker Compose
echo "--> [4/4] Kéo GHCR Images và khởi động lại container trên Server..."
$SSH_CMD "$DEPLOY_USER@$DEPLOY_HOST" "
    cd $REMOTE_DIR
    if [ -n \"$GHCR_PAT\" ]; then
        echo \"$GHCR_PAT\" | docker login ghcr.io -u \"$GHCR_USER\" --password-stdin
    fi
    TAG=\"$TAG\" docker compose -f infra/prod/docker-compose.yml pull || TAG=\"$TAG\" docker-compose -f infra/prod/docker-compose.yml pull
    TAG=\"$TAG\" docker compose -f infra/prod/docker-compose.yml up -d || TAG=\"$TAG\" docker-compose -f infra/prod/docker-compose.yml up -d
"

# 5.   Trạng thái Container
echo "================================================================="
echo "✅ Triển khai hoàn tất! Trạng thái các container trên Server:"
$SSH_CMD "$DEPLOY_USER@$DEPLOY_HOST" "cd $REMOTE_DIR && docker compose -f infra/prod/docker-compose.yml ps || docker-compose -f infra/prod/docker-compose.yml ps"
echo "================================================================="
