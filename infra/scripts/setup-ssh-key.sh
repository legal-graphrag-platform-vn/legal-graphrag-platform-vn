#!/usr/bin/env bash
# ==============================================================================
# Script khởi tạo SSH Key & Cấu hình máy chủ từ xa (Deployment Setup)
# ==============================================================================

set -euo pipefail

KEY_PATH="${KEY_PATH:-$HOME/.ssh/id_ed25519_deploy}"
DEPLOY_HOST="${DEPLOY_HOST:-}"
DEPLOY_USER="${DEPLOY_USER:-}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"

echo "=== SSH Deployment Infrastructure Setup ==="

if [ -z "$DEPLOY_HOST" ] || [ -z "$DEPLOY_USER" ]; then
    echo "Lỗi: Thiếu thông tin máy chủ từ xa."
    echo "Cú pháp: DEPLOY_HOST=<host> DEPLOY_USER=<user> [DEPLOY_PORT=22] [KEY_PATH=~/.ssh/id_ed25519_deploy] ./infra/scripts/setup-ssh-key.sh"
    exit 1
fi

# 1.   Tạo SSH Key Pair nếu chưa tồn tại
if [ ! -f "$KEY_PATH" ]; then
    echo "--> Chưa tìm thấy SSH key tại $KEY_PATH. Đang khởi tạo SSH key mới (Ed25519)..."
    ssh-keygen -t ed25519 -C "deploy@legal-graphrag" -f "$KEY_PATH" -N ""
    echo "--> Khởi tạo SSH key thành công."
else
    echo "--> Đã tìm thấy SSH key tại $KEY_PATH."
fi

# 2.   Copy Public Key lên Server từ xa
echo "--> Đang copy Public Key lên $DEPLOY_USER@$DEPLOY_HOST (port $DEPLOY_PORT)..."
echo "Lưu ý: Bạn có thể cần nhập mật khẩu SSH của Server trong lần đầu tiên này."

ssh-copy-id -i "${KEY_PATH}.pub" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST"

# 3.   Kiểm tra kết nối không dùng mật khẩu
echo "--> Đang kiểm tra kết nối SSH không cần mật khẩu..."
if ssh -i "$KEY_PATH" -p "$DEPLOY_PORT" -o BatchMode=yes "$DEPLOY_USER@$DEPLOY_HOST" "echo OK" >/dev/null 2>&1; then
    echo "================================================================="
    echo "✅ Kết nối SSH thành công! Máy chủ đã sẵn sàng cho deployment."
    echo "   Public Key content (${KEY_PATH}.pub):"
    cat "${KEY_PATH}.pub"
    echo "================================================================="
else
    echo "❌ Kết nối không thành công. Vui lòng kiểm tra lại cấu hình Server."
    exit 1
fi
