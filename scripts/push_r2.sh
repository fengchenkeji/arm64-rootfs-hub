#!/usr/bin/env bash
# 把 arm64 rootfs 批量上传到 Cloudflare R2（S3 兼容端点）。
#
# 用法：
#   export R2_ENDPOINT="https://<accountid>.r2.cloudflarestorage.com"
#   export R2_BUCKET="rootfs"
#   export R2_ACCESS_KEY_ID="..."
#   export R2_SECRET_ACCESS_KEY="..."
#   ./scripts/push_r2.sh alpine ubuntu        # 指定发行版
#   ./scripts/push_r2.sh all                  # 全部
#
# 依赖 awscli（S3 协议兼容 R2）：
#   pip install awscli     或     apt install awscli
#
# 上传完成后，把 data/mirrors.json 里 cloudflare.enabled 改成 true，
# url_template 换成你的 R2 自定义域名，例如：
#   "url_template": "https://rootfs.example.com/{file}"
set -euo pipefail

: "${R2_ENDPOINT:?请先 export R2_ENDPOINT}"
: "${R2_BUCKET:?请先 export R2_BUCKET}"
: "${R2_ACCESS_KEY_ID:?请先 export R2_ACCESS_KEY_ID}"
: "${R2_SECRET_ACCESS_KEY:?请先 export R2_SECRET_ACCESS_KEY}"

WANT="${1:-alpine}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

python3 - "$ROOT" "$WANT" "$WORK" <<'PY'
import json, os, pathlib, sys, urllib.request
root, want, work = map(pathlib.Path, sys.argv[1:4])
root = pathlib.Path(root)
catalog = json.loads((root / "data" / "catalog.json").read_text())
pkgs = [x.strip() for x in want.split(",")]
for s in catalog["systems"]:
    if want != "all" and s["id"] not in pkgs:
        continue
    for v in s["versions"]:
        dst = work / v["file"]
        print(f"↓ {v['file']}")
        req = urllib.request.Request(v["url"], headers={"User-Agent": "rootfs-hub-mirror"})
        with urllib.request.urlopen(req, timeout=180) as r:
            dst.write_bytes(r.read())
    print(f"  {s['id']}: {len(s['versions'])} file(s)")
PY

echo "→ 上传到 s3://$R2_BUCKET/"
AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
AWS_DEFAULT_REGION=auto \
aws s3 sync "$WORK" "s3://$R2_BUCKET/" --endpoint-url "$R2_ENDPOINT"

echo "✅ 完成。记得把 data/mirrors.json 的 cloudflare.enabled 改成 true 并填域名。"
