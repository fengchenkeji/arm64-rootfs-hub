# ARM64 RootFS Hub

arm64 / aarch64 Linux 根文件系统下载站 + **两种 API**，跑在 GitHub Pages 上（纯静态、无后端），
数据由 GitHub Actions 每次推送 / 每周自动校验并重新发布。

- 站点：`https://<owner>.github.io/arm64-rootfs-hub/`
- 覆盖：Alpine、Ubuntu、Debian、Arch Linux ARM、Void、Gentoo、Rocky Linux
- 下载源优先级：**Cloudflare R2 镜像 > GitHub Release 镜像 > 官方源 > 官方备用镜像**

## 一、单请求单值 API（纯文本）

一次请求只回一个值，`$(curl ...)` 直接能用：

| 端点 | 返回 |
|---|---|
| `GET /api/t/systems.txt` | 每行一个发行版 id |
| `GET /api/t/names/{id}.txt` | 发行版显示名（一个值） |
| `GET /api/t/versions/{id}.txt` | 每行一个版本号 |
| `GET /api/t/url/{id}/{version}.txt` | **一个下载直链** |
| `GET /api/t/size/{id}/{version}.txt` | 一个字节数 |
| `GET /api/t/file/{id}/{version}.txt` | 一个文件名 |
| `GET /api/t/sha/{id}/{version}.txt` | 一个校验文件链接 |
| `GET /api/t/mirrors/{id}/{version}.txt` | 每行一个镜像直链 |

```bash
S=https://fengchenkeji.github.io/arm64-rootfs-hub

curl -s $S/api/t/systems.txt
curl -s $S/api/t/versions/debian.txt
URL=$(curl -s $S/api/t/url/debian/12.txt) && curl -LO "$URL"
```

## 二、结构化 JSON API

| 端点 | 说明 |
|---|---|
| `GET /api/systems.json` | 发行版列表 |
| `GET /api/systems/{id}.json` | 该发行版所有版本 |
| `GET /api/download/{id}/{version}.json` | 指定版本下载信息 |
| `GET /api/all.json` | 全量目录 |

`download` 关键字段：`url`（已按优先级挑好的直链）、`source`
（`cloudflare` / `github` / `official` / `official-mirror`）、`size_bytes`、
`mirrors`（所有探测通过的镜像）、`checksum_url`、`tawcroot` 兼容提示。

## 三、镜像源：Cloudflare + GitHub

`data/mirrors.json`：

```json
{
  "github":     { "enabled": true,  "owner": "fengchenkeji", "repo": "arm64-rootfs-hub",
                  "release_tag": "rootfs-mirror",
                  "url_template": "https://github.com/{owner}/{repo}/releases/download/{tag}/{file}" },
  "cloudflare": { "enabled": false, "url_template": "https://rootfs.example.com/{file}" }
}
```

构建时会为每个版本拼出镜像 URL 并真实探测，探测通过才写进 API。因此：

1. **GitHub 镜像**：跑 `.github/workflows/mirror-github.yml`（手动，参数 `systems` / `max_mb`），
   资产发布到 Release `rootfs-mirror`，下次构建自动变成可用镜像。
2. **Cloudflare 镜像**：
   - 本地可用 `scripts/push_r2.sh` 批量上传到 R2；
   - 或跑 `.github/workflows/mirror-cloudflare.yml`（需 Secrets：
     `R2_ENDPOINT` `R2_BUCKET` `R2_ACCESS_KEY_ID` `R2_SECRET_ACCESS_KEY`，可选 `R2_PUBLIC_BASE`），
     未配置时自动跳过；
   - 然后把 `cloudflare.enabled` 改成 `true`、`url_template` 换成你的 R2 域名 / Worker 路由。

> 镜像关闭或未上传时，站点与 API 走官方源，不会出现 404 假链接。

## 四、维护

唯一数据源 `data/catalog.json`，加版本就是加一条：

```json
{
  "version": "12", "series": "bookworm", "codename": "bookworm", "kind": "genericcloud",
  "file": "debian-12-genericcloud-arm64.tar.xz",
  "url": "https://cloud.debian.org/.../debian-12-genericcloud-arm64.tar.xz",
  "mirrors": [],
  "checksums": "https://cloud.debian.org/.../SHA512SUMS",
  "tawcroot": "glibc 2.36，推荐",
  "note": "当前稳定 LTS"
}
```

## 五、本地跑

```bash
python3 scripts/build_api.py               # 探测 + 生成
python3 scripts/build_api.py --skip-verify # 只生成
python3 -m http.server -d public 8080      # http://localhost:8080
```

## 六、部署

1. Settings → Pages → Source = **GitHub Actions**
2. `push main` 自动构建发布；也可在 Actions 里 `Run workflow`
3. 每周一 03:00 UTC 自动重校验全部链接

## 七、JS 后端（Cloudflare Worker）

GitHub Pages 只能托管静态文件，**不能跑 JS 后端**。要"发一个请求返回一个值"，
用 `worker/` 里的 Cloudflare Worker（真正的 JS 后端，带参数路由）。

```
worker/
├── src/index.js      # 后端代码（导出 fetch 处理器）
├── wrangler.toml     # Workers 配置
└── test.mjs          # 本地测试：node worker/test.mjs
```

### 接口（一个请求 → 一个值，`text/plain`）

| 请求 | 返回 |
|---|---|
| `GET /` | `ok` |
| `GET /?q=help` | 用法 |
| `GET /?q=list` | 每行一个发行版 |
| `GET /?q=count` | 一个数字 |
| `GET /?q=versions&s=debian` | 每行一个版本 |
| `GET /?q=name&s=debian` | `Debian` |
| `GET /?q=url&s=debian&v=12` | 一个直链 |
| `GET /?q=size&s=debian&v=12` | 一个字节数 |
| `GET /?q=file&s=debian&v=12` | 一个文件名 |
| `GET /?q=sha&s=debian&v=12` | 一个校验链接 |
| `GET /?q=mirrors&s=alpine&v=3.24.4` | 每行一个镜像 |
| `GET /?q=json&s=debian&v=12` | 该版本完整 JSON |

```bash
API=https://arm64-rootfs-hub.<你的子域>.workers.dev
curl "$API/?q=versions&s=debian"
URL=$(curl -s "$API/?q=url&s=debian&v=12") && curl -LO "$URL"
```

数据源是 Pages 上的 `api/all.json`（Actions 已校验过体积/镜像），边缘缓存 5 分钟，
上游失败自动回落到仓库里的 `data/catalog.json`。

### 本地跑 / 部署

```bash
node worker/test.mjs          # 本地验证全部路由（无需网络）
cd worker && npx wrangler dev # 本地起服务（需登录 Cloudflare）
npx wrangler deploy           # 推到 Workers
```

CI：`.github/workflows/deploy-worker.yml`，需要仓库 Secrets
`CF_API_TOKEN`（Workers 编辑权限）+ `CF_ACCOUNT_ID`；未配置自动跳过。

