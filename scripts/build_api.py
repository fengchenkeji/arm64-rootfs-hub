#!/usr/bin/env python3
"""Build the static API for arm64-rootfs-hub.

Two API surfaces, both plain files on GitHub Pages (no server):

  JSON  (rich)      /api/systems.json, /api/systems/<id>.json,
                    /api/download/<id>/<ver>.json, /api/all.json
  TEXT  (one value) /api/t/systems.txt          -> 每行一个发行版 id
                    /api/t/names/<id>.txt        -> 一个名字
                    /api/t/versions/<id>.txt     -> 每行一个版本号
                    /api/t/url/<id>/<ver>.txt    -> 一个下载直链
                    /api/t/size/<id>/<ver>.txt   -> 一个字节数
                    /api/t/sha/<id>/<ver>.txt    -> 一个校验文件链接
                    /api/t/mirrors/<id>/<ver>.txt-> 每行一个镜像链接

Mirrors: data/mirrors.json configures a Cloudflare (R2/Worker) base and a
GitHub Release base; every candidate URL is probed, and one is chosen by
priority  cloudflare > github > official primary > official mirrors.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.json"
MIRRORS_CFG = ROOT / "data" / "mirrors.json"
PUBLIC = ROOT / "public"
API = PUBLIC / "api"
TEXT = API / "t"

UA = "arm64-rootfs-hub/2.0 (+https://github.com)"
TIMEOUT = 25


def human(n: int | None) -> str | None:
    if not n:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{int(f)} B" if u == "B" else f"{f:.1f} {u}"
        f /= 1024
    return None


def probe(url: str) -> dict:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            size = r.headers.get("Content-Length")
            return {"ok": True, "http": r.status,
                    "size": int(size) if size and size.isdigit() else None}
    except Exception:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            cr = r.headers.get("Content-Range") or ""
            total = None
            if "/" in cr:
                tail = cr.rsplit("/", 1)[1].strip()
                total = int(tail) if tail.isdigit() else None
            if total is None:
                cl = r.headers.get("Content-Length")
                if r.status == 200 and cl and cl.isdigit():
                    total = int(cl)
            return {"ok": True, "http": r.status, "size": total}
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "size": None}
    except Exception:
        return {"ok": False, "http": None, "size": None}


def mirror_urls(cfg: dict, v: dict) -> list[dict]:
    out = []
    gh = cfg.get("github") or {}
    if gh.get("enabled"):
        out.append({
            "type": "github",
            "url": gh["url_template"].format(
                owner=gh["owner"], repo=gh["repo"], tag=gh["release_tag"], file=v["file"]
            ),
        })
    cf = cfg.get("cloudflare") or {}
    if cf.get("enabled"):
        out.append({
            "type": "cloudflare",
            "url": cf["url_template"].format(file=v["file"]),
        })
    return out


def verify(catalog: dict, cfg: dict, workers: int = 16) -> dict:
    urls: list[str] = []
    for s in catalog["systems"]:
        for v in s["versions"]:
            urls.append(v["url"])
            urls.extend(v.get("mirrors") or [])
            urls.extend(m["url"] for m in mirror_urls(cfg, v))
            if v.get("checksums"):
                urls.append(v["checksums"])
    unique = list(dict.fromkeys(urls))
    res: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url, r in zip(unique, pool.map(probe, unique)):
            res[url] = r

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for s in catalog["systems"]:
        for v in s["versions"]:
            official = [{"type": "official", "url": v["url"], **res[v["url"]]}]
            official += [
                {"type": "official-mirror", "url": u, **res[u]} for u in (v.get("mirrors") or [])
            ]
            mine = [{**m, **res[m["url"]]} for m in mirror_urls(cfg, v)]

            pick = None
            for group in (mine, official):
                for c in group:
                    if c.get("ok"):
                        pick = c
                        break
                if pick:
                    break
            chosen = pick if pick else (mine + official)[0]
            size = chosen.get("size") or next(
                (c.get("size") for c in official if c.get("ok")), None)

            v["download"] = {
                "available": bool(chosen.get("ok")),
                "source": chosen.get("type"),
                "url": chosen.get("url"),
                "http_status": chosen.get("http"),
                "size_bytes": size,
                "size_human": human(size),
                "verified_at": now,
            }
            v["sources"] = mine + official
            if v.get("checksums"):
                v["checksum"] = {"url": v["checksums"], **res[v["checksums"]]}
    catalog["meta"]["verified_at"] = now
    return catalog


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not body.endswith("\n"):
        body += "\n"
    path.write_text(body, encoding="utf-8")


def slug(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-+") else "_" for c in s)


def build(catalog: dict) -> None:
    API.mkdir(parents=True, exist_ok=True)
    for d in (API / "systems", API / "download", TEXT):
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file():
                    f.unlink()

    catalog["meta"]["generated_at"] = dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0).isoformat()
    catalog["meta"]["counts"] = {
        "systems": len(catalog["systems"]),
        "versions": sum(len(s["versions"]) for s in catalog["systems"]),
        "available": sum(1 for s in catalog["systems"] for v in s["versions"]
                         if v["download"]["available"]),
    }
    write_json(API / "all.json", catalog)

    index = []
    for s in catalog["systems"]:
        vs = s["versions"]
        index.append({
            "id": s["id"], "name": s["name"], "libc": s["libc"],
            "package_manager": s["package_manager"], "rolling": s.get("rolling", False),
            "description": s["description"], "homepage": s.get("homepage"),
            "version_count": len(vs),
            "available_count": sum(1 for v in vs if v["download"]["available"]),
            "latest": vs[0]["version"] if vs else None,
            "endpoint": f"api/systems/{s['id']}.json",
            "text_endpoint": f"api/t/versions/{s['id']}.txt",
            "versions": [v["version"] for v in vs],
        })
    write_json(API / "systems.json", {"meta": catalog["meta"], "systems": index})

    for s in catalog["systems"]:
        versions = []
        for v in s["versions"]:
            versions.append({
                "version": v["version"], "series": v.get("series"),
                "codename": v.get("codename"), "flavor": v.get("flavor"),
                "kind": v.get("kind"), "arch": catalog["arch"], "file": v["file"],
                "size_bytes": v["download"]["size_bytes"],
                "size_human": v["download"]["size_human"],
                "available": v["download"]["available"],
                "source": v["download"]["source"],
                "download_endpoint": f"api/download/{s['id']}/{slug(v['version'])}.json",
                "text_endpoint": f"api/t/url/{s['id']}/{slug(v['version'])}.txt",
                "direct_url": v["download"]["url"],
                "mirrors": [c["url"] for c in v["sources"] if c.get("ok")],
                "tawcroot": v.get("tawcroot"), "note": v.get("note"),
            })
        write_json(API / "systems" / f"{s['id']}.json", {
            "id": s["id"], "name": s["name"], "libc": s["libc"],
            "package_manager": s["package_manager"], "rolling": s.get("rolling", False),
            "description": s["description"], "homepage": s.get("homepage"),
            "version_count": len(versions), "versions": versions,
        })

        for v in s["versions"]:
            write_json(API / "download" / s["id"] / f"{slug(v['version'])}.json", {
                "system": s["id"], "system_name": s["name"],
                "version": v["version"], "codename": v.get("codename"),
                "flavor": v.get("flavor"), "arch": catalog["arch"], "file": v["file"],
                "url": v["download"]["url"], "source": v["download"]["source"],
                "size_bytes": v["download"]["size_bytes"],
                "size_human": v["download"]["size_human"],
                "available": v["download"]["available"],
                "verified_at": v["download"]["verified_at"],
                "mirrors": [c["url"] for c in v["sources"] if c.get("ok")],
                "checksum_url": (v.get("checksum") or {}).get("url"),
                "tawcroot": v.get("tawcroot"), "note": v.get("note"),
            })

    # ---- TEXT: 一次请求 -> 一个值 ----
    write_text(TEXT / "systems.txt", "\n".join(s["id"] for s in catalog["systems"]))
    for s in catalog["systems"]:
        write_text(TEXT / "names" / f"{s['id']}.txt", s["name"])
        write_text(TEXT / "versions" / f"{s['id']}.txt",
                   "\n".join(v["version"] for v in s["versions"]))
        for v in s["versions"]:
            k = slug(v["version"])
            write_text(TEXT / "url" / s["id"] / f"{k}.txt", v["download"]["url"])
            write_text(TEXT / "size" / s["id"] / f"{k}.txt", str(v["download"]["size_bytes"] or 0))
            write_text(TEXT / "file" / s["id"] / f"{k}.txt", v["file"])
            write_text(TEXT / "sha" / s["id"] / f"{k}.txt",
                       (v.get("checksum") or {}).get("url") or "")
            write_text(TEXT / "mirrors" / s["id"] / f"{k}.txt",
                       "\n".join(c["url"] for c in v["sources"] if c.get("ok")))

    write_json(API / "index.json", {
        "meta": catalog["meta"],
        "text": {
            "systems": "api/t/systems.txt",
            "name": "api/t/names/{id}.txt",
            "versions": "api/t/versions/{id}.txt",
            "url": "api/t/url/{id}/{version}.txt",
            "size": "api/t/size/{id}/{version}.txt",
            "file": "api/t/file/{id}/{version}.txt",
            "sha": "api/t/sha/{id}/{version}.txt",
            "mirrors": "api/t/mirrors/{id}/{version}.txt",
        },
        "json": {
            "all": "api/all.json",
            "systems": "api/systems.json",
            "system": "api/systems/{id}.json",
            "download": "api/download/{id}/{version}.json",
        },
        "usage": [
            "GET /api/t/systems.txt                 -> 每行一个发行版",
            "GET /api/t/versions/debian.txt         -> 每行一个版本",
            "GET /api/t/url/debian/12.txt           -> 一个直链（一个值）",
            "GET /api/t/size/debian/12.txt          -> 一个字节数",
            "GET /api/t/mirrors/debian/12.txt       -> 每行一个镜像",
        ],
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    cfg = json.loads(MIRRORS_CFG.read_text(encoding="utf-8")) if MIRRORS_CFG.exists() else {}
    catalog.setdefault("meta", {})
    catalog["meta"].setdefault("schema", catalog.get("schema", "arm64-rootfs-hub/v2"))

    if not args.skip_verify:
        print("probing sources ...", file=sys.stderr)
        catalog = verify(catalog, cfg)

    build(catalog)
    print("built: {systems} systems / {versions} versions / {available} available".format(
        **catalog["meta"]["counts"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
