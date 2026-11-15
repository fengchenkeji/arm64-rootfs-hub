#!/usr/bin/env python3
"""Build the static JSON API for arm64-rootfs-hub.

Reads data/catalog.json, optionally probes every download URL (HEAD, falling
back to a 1-byte ranged GET) to record availability + size, then writes the
static API tree consumed by the GitHub Pages frontend:

  public/api/index.json                     -> endpoint map + meta
  public/api/all.json                       -> whole catalog, verified
  public/api/systems.json                   -> distribution list
  public/api/systems/<id>.json              -> versions of one distribution
  public/api/download/<id>/<version>.json   -> download target for one version

No third-party dependencies: runs on the bare ubuntu-latest python3.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.json"
PUBLIC = ROOT / "public"
API = PUBLIC / "api"

UA = "arm64-rootfs-hub/1.0 (+https://github.com)"
TIMEOUT = 25


def human(n: int | None) -> str | None:
    if not n:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}" if u != "B" else f"{int(f)} B"
        f /= 1024
    return None


def probe(url: str) -> dict:
    """Return {ok, http, size, final_url, error}. Never raises."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            size = r.headers.get("Content-Length")
            return {
                "ok": True,
                "http": r.status,
                "size": int(size) if size and size.isdigit() else None,
                "final_url": r.geturl(),
            }
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        pass
    # Fallback: 1-byte ranged GET. Many CDNs reject HEAD.
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Range": "bytes=0-0"}
    )
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
            return {
                "ok": True,
                "http": r.status,
                "size": total,
                "final_url": r.geturl(),
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "size": None, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 - probe must never break the build
        return {"ok": False, "http": None, "size": None, "error": type(e).__name__}


def verify_catalog(catalog: dict, workers: int = 12) -> dict:
    urls: list[str] = []
    for s in catalog["systems"]:
        for v in s["versions"]:
            urls.append(v["url"])
            urls.extend(v.get("mirrors") or [])
            if v.get("checksums"):
                urls.append(v["checksums"])
    unique = list(dict.fromkeys(urls))
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url, res in zip(unique, pool.map(probe, unique)):
            results[url] = res

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for s in catalog["systems"]:
        for v in s["versions"]:
            primary = results[v["url"]]
            chosen_url, chosen = v["url"], primary
            if not primary["ok"]:
                for m in v.get("mirrors") or []:
                    if results[m]["ok"]:
                        chosen_url, chosen = m, results[m]
                        break
            size = chosen.get("size") or primary.get("size")
            v["download"] = {
                "available": bool(chosen.get("ok")),
                "url": chosen_url,
                "fallback_url": v["url"] if chosen_url != v["url"] else None,
                "http_status": chosen.get("http"),
                "size_bytes": size,
                "size_human": human(size),
                "final_url": chosen.get("final_url"),
                "verified_at": now,
            }
            v["sources"] = [
                {
                    "url": u,
                    "role": "primary" if u == v["url"] else "mirror",
                    "available": results[u]["ok"],
                    "http_status": results[u]["http"],
                }
                for u in ([v["url"]] + (v.get("mirrors") or []))
            ]
            if v.get("checksums"):
                c = results[v["checksums"]]
                v["checksum"] = {
                    "url": v["checksums"],
                    "available": c["ok"],
                    "http_status": c["http"],
                }
    catalog["meta"]["verified_at"] = now
    return catalog


def slug_safe(s: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "._-+") else "_" for ch in s)


def build(catalog: dict) -> None:
    API.mkdir(parents=True, exist_ok=True)
    systems_dir = API / "systems"
    dl_dir = API / "download"
    for d in (systems_dir, dl_dir):
        if d.exists():
            for f in d.rglob("*.json"):
                f.unlink()

    catalog["meta"]["generated_at"] = dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat()
    catalog["meta"]["counts"] = {
        "systems": len(catalog["systems"]),
        "versions": sum(len(s["versions"]) for s in catalog["systems"]),
        "available": sum(
            1
            for s in catalog["systems"]
            for v in s["versions"]
            if v["download"]["available"]
        ),
    }

    write(API / "all.json", catalog)

    index = []
    for s in catalog["systems"]:
        versions = s["versions"]
        available = sum(1 for v in versions if v["download"]["available"])
        index.append(
            {
                "id": s["id"],
                "name": s["name"],
                "libc": s["libc"],
                "package_manager": s["package_manager"],
                "rolling": s.get("rolling", False),
                "description": s["description"],
                "homepage": s.get("homepage"),
                "version_count": len(versions),
                "available_count": available,
                "latest": versions[0]["version"] if versions else None,
                "endpoint": f"api/systems/{s['id']}.json",
                "versions": [v["version"] for v in versions],
            }
        )
    write(API / "systems.json", {"meta": catalog["meta"], "systems": index})

    for s in catalog["systems"]:
        versions = []
        for v in s["versions"]:
            versions.append(
                {
                    "version": v["version"],
                    "series": v.get("series"),
                    "codename": v.get("codename"),
                    "kind": v.get("kind"),
                    "arch": catalog["arch"],
                    "file": v["file"],
                    "size_bytes": v["download"]["size_bytes"],
                    "size_human": v["download"]["size_human"],
                    "available": v["download"]["available"],
                    "download_endpoint": (
                        f"api/download/{s['id']}/{slug_safe(v['version'])}.json"
                    ),
                    "direct_url": v["download"]["url"],
                    "tawcroot": v.get("tawcroot"),
                    "note": v.get("note"),
                }
            )
        write(
            systems_dir / f"{s['id']}.json",
            {
                "id": s["id"],
                "name": s["name"],
                "libc": s["libc"],
                "package_manager": s["package_manager"],
                "rolling": s.get("rolling", False),
                "description": s["description"],
                "homepage": s.get("homepage"),
                "version_count": len(versions),
                "versions": versions,
            },
        )

        out = dl_dir / s["id"]
        out.mkdir(parents=True, exist_ok=True)
        for v in s["versions"]:
            write(
                out / f"{slug_safe(v['version'])}.json",
                {
                    "system": s["id"],
                    "system_name": s["name"],
                    "version": v["version"],
                    "codename": v.get("codename"),
                    "arch": catalog["arch"],
                    "file": v["file"],
                    "url": v["download"]["url"],
                    "fallback_url": v["download"]["fallback_url"],
                    "mirrors": [
                        x["url"] for x in v["sources"] if x["role"] == "mirror"
                    ],
                    "size_bytes": v["download"]["size_bytes"],
                    "size_human": v["download"]["size_human"],
                    "available": v["download"]["available"],
                    "verified_at": v["download"]["verified_at"],
                    "checksum_url": (v.get("checksum") or {}).get("url"),
                    "tawcroot": v.get("tawcroot"),
                    "note": v.get("note"),
                },
            )

    write(
        API / "index.json",
        {
            "meta": catalog["meta"],
            "endpoints": {
                "all": "api/all.json",
                "systems": "api/systems.json",
                "system": "api/systems/{id}.json",
                "download": "api/download/{id}/{version}.json",
            },
            "usage": [
                "GET /api/systems.json                    -> 发行版列表",
                "GET /api/systems/{id}.json               -> 该发行版所有版本",
                "GET /api/download/{id}/{version}.json    -> 指定版本的下载信息",
            ],
        },
    )


def write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-verify", action="store_true", help="reuse existing sizes")
    args = ap.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog.setdefault("meta", {})
    catalog["meta"].setdefault("schema", catalog.get("schema", "arm64-rootfs-hub/v1"))

    if not args.skip_verify:
        print("probing download sources ...", file=sys.stderr)
        catalog = verify_catalog(catalog)

    build(catalog)
    print(
        "built: {systems} systems / {versions} versions / {available} available".format(
            **catalog["meta"]["counts"]
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
