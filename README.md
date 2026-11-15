# ARM64 RootFS Hub

arm64 / aarch64 Linux 根文件系统下载站 + **静态 JSON API**，跑在 GitHub Pages 上，
数据由 GitHub Actions 每周自动校验并重新发布。

- 站点：`https://<owner>.github.io/arm64-rootfs-hub/`
- 覆盖：Alpine / Debian / Ubuntu / Arch Linux ARM
- 全部 arm64（aarch64）架构，适配 Termux / proot / tawcroot

## API

| 端点 | 说明 |
|---|---|
| `GET /api/index.json` | 端点索引 + 元信息 |
| `GET /api/systems.json` | 发行版列表（id、名称、libc、版本数、可用数） |
| `GET /api/systems/{id}.json` | 指定发行版的**所有版本** |
| `GET /api/download/{id}/{version}.json` | 指定版本的下载信息（直链、镜像、体积、校验文件） |
| `GET /api/all.json` | 全量目录 |

示例：

```bash
curl -s https://<owner>.github.io/arm64-rootfs-hub/api/systems.json      | jq .
curl -s https://<owner>.github.io/arm64-rootfs-hub/api/systems/debian.json | jq .
curl -s https://<owner>.github.io/arm64-rootfs-hub/api/download/ubuntu/22.04.5.json | jq .
```

`download` 响应字段：

```json
{
  "system": "ubuntu",
  "version": "22.04.5",
  "arch": "arm64",
  "file": "ubuntu-base-22.04.5-base-arm64.tar.gz",
  "url": "https://mirrors.aliyun.com/....tar.gz",
  "fallback_url": "https://cdimage.ubuntu.com/....tar.gz",
  "mirrors": ["https://mirrors.huaweicloud.com/....tar.gz"],
  "size_bytes": 30300000,
  "size_human": "28.9 MB",
  "available": true,
  "verified_at": "2026-11-15T00:00:00+00:00",
  "checksum_url": "https://cdimage.ubuntu.com/.../SHA256SUMS",
  "tawcroot": "glibc 2.35，兼容与特性平衡，proot / tawcroot 通用首选。",
  "note": "主流 LTS。"
}
```

## 维护

数据源是唯一入口文件 `data/catalog.json`，新增版本只需加一条记录：

```json
{
  "version": "12.0",
  "series": "bookworm",
  "codename": "bookworm",
  "kind": "genericcloud",
  "file": "debian-12-genericcloud-arm64.tar.xz",
  "url": "https://...",
  "mirrors": ["https://..."],
  "checksums": "https://.../SHA512SUMS",
  "tawcroot": "兼容性说明"
}
```

`url` 是主源，`mirrors` 为备用；构建时逐个探测（HEAD，失败回落 1 字节 Range GET），
自动记录体积、可用性，并优先挑一个可用的源写进 `download.url`。

## 本地跑

```bash
python3 scripts/build_api.py            # 探测 + 生成 public/api
python3 scripts/build_api.py --skip-verify   # 不探测，仅生成
python3 -m http.server -d public 8080   # 打开 http://localhost:8080
```

## 部署

1. 仓库 Settings → Pages → Source 选 **GitHub Actions**
2. push 到 `main` 即自动构建发布；也可在 Actions 里手动 `Run workflow`
3. 每周一 03:00 UTC 自动重新校验链接
