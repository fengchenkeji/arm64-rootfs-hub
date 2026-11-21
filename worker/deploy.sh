#!/usr/bin/env bash
# 一键部署 Worker 到 Cloudflare（在本机跑，不依赖 CI secret）
#
#   export CLOUDFLARE_API_TOKEN="..."    # 从 Dashboard 创建的 API Token，约 40 位，无 cfat_ 前缀
#   export CLOUDFLARE_ACCOUNT_ID="533e4deb177f68c8581bb64b5be90f5d"
#   ./worker/deploy.sh
#
# 需要 Node 18+。首次会提示授权（浏览器登录亦可：npx wrangler login）。
set -euo pipefail
cd "$(dirname "$0")"

: "${CLOUDFLARE_API_TOKEN:?请先 export CLOUDFLARE_API_TOKEN}"
: "${CLOUDFLARE_ACCOUNT_ID:?请先 export CLOUDFLARE_ACCOUNT_ID}"

node --check src/index.js
node test.mjs

npx --yes wrangler@3 deploy
npx --yes wrangler@3 deployments list 2>/dev/null | head -5 || true
echo "✅ 部署完成，地址形如 https://arm64-rootfs-hub.<子域>.workers.dev"
