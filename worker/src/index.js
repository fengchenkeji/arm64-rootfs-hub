/**
 * arm64-rootfs-hub — Cloudflare Worker 后端
 *
 * 一个请求 -> 一个值（text/plain）。
 *
 *   GET /                              -> ok
 *   GET /?q=list                       -> 每行一个发行版 id
 *   GET /?q=count                      -> 发行版数量（一个数字）
 *   GET /?q=versions&s=debian          -> 每行一个版本号
 *   GET /?q=name&s=debian              -> 一个名字
 *   GET /?q=url&s=debian&v=12          -> 一个下载直链（一个值）
 *   GET /?q=size&s=debian&v=12         -> 一个字节数
 *   GET /?q=file&s=debian&v=12         -> 一个文件名
 *   GET /?q=sha&s=debian&v=12          -> 一个校验文件链接
 *   GET /?q=mirrors&s=debian&v=12      -> 每行一个镜像直链
 *   GET /?q=json&s=debian&v=12         -> 该版本完整 JSON（结构化兜底）
 *   GET /?q=help                       -> 用法
 *
 * 数据源：仓库里 GitHub Actions 生成的 api/all.json（已做过真实探测），
 * 边缘缓存 5 分钟；上游挂了会回落到 raw catalog.json。
 */

const PAGES_ALL = "https://fengchenkeji.github.io/arm64-rootfs-hub/api/all.json";
const RAW_CATALOG =
  "https://raw.githubusercontent.com/fengchenkeji/arm64-rootfs-hub/main/data/catalog.json";

const TTL_MS = 5 * 60 * 1000;
let memo = { at: 0, data: null };

const TEXT = "text/plain; charset=utf-8";

function text(body, status = 200) {
  return new Response(body.endsWith("\n") ? body : body + "\n", {
    status,
    headers: {
      "content-type": TEXT,
      "access-control-allow-origin": "*",
      "cache-control": "public, max-age=60",
    },
  });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2) + "\n", {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "cache-control": "public, max-age=60",
    },
  });
}

/** 统一取到 {systems:[{id,name,versions:[...]}]}，带 memo。 */
async function load() {
  const now = Date.now();
  if (memo.data && now - memo.at < TTL_MS) return memo.data;

  // 1) 首选：Pages 上已校验过的 all.json
  try {
    const r = await fetch(PAGES_ALL, { cf: { cacheTtl: 300 } });
    if (r.ok) {
      const d = await r.json();
      if (Array.isArray(d.systems) && d.systems.length) {
        memo = { at: now, data: d };
        return d;
      }
    }
  } catch (_) {
    /* 忽略，走回落 */
  }

  // 2) 回落：仓库原始 catalog，现场补一个 download.url
  const r = await fetch(RAW_CATALOG, { cf: { cacheTtl: 300 } });
  if (!r.ok) throw new Error("upstream " + r.status);
  const c = await r.json();
  for (const s of c.systems) {
    for (const v of s.versions) {
      v.download = v.download || {
        available: true,
        source: "official",
        url: v.url,
        size_bytes: null,
      };
      v.sources = v.sources || [{ type: "official", url: v.url, ok: true }];
    }
  }
  memo = { at: now, data: c };
  return c;
}

function findSystem(data, id) {
  return (data.systems || []).find((s) => s.id === id) || null;
}

function findVersion(sys, ver) {
  return (sys.versions || []).find(
    (v) => v.version === ver || String(v.version) === String(ver)
  ) || null;
}

const HELP = `arm64-rootfs-hub api (one request -> one value)

  /?q=list                        每行一个发行版
  /?q=count                       发行版数量
  /?q=versions&s=<system>         每行一个版本
  /?q=name&s=<system>             发行版名字
  /?q=url&s=<system>&v=<ver>      下载直链（一个值）
  /?q=size&s=<system>&v=<ver>     字节数
  /?q=file&s=<system>&v=<ver>     文件名
  /?q=sha&s=<system>&v=<ver>      校验文件链接
  /?q=mirrors&s=<system>&v=<ver>  每行一个镜像
  /?q=json&s=<system>&v=<ver>     完整 JSON

示例：
  curl "$API/?q=list"
  curl "$API/?q=versions&s=debian"
  URL=$(curl -s "$API/?q=url&s=debian&v=12") && curl -LO "$URL"`;

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET,HEAD,OPTIONS",
          "access-control-allow-headers": "*",
        },
      });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return text("method not allowed", 405);
    }

    const q = (url.searchParams.get("q") || "").toLowerCase();
    const s = url.searchParams.get("s") || url.searchParams.get("system") || "";
    const v = url.searchParams.get("v") || url.searchParams.get("version") || "";

    if (q === "help" || (!q && url.pathname !== "/")) return text(HELP);
    if (!q) return text("ok");

    let data;
    try {
      data = await load();
    } catch (e) {
      return text("upstream error: " + e.message, 502);
    }

    if (q === "list" || q === "systems") {
      return text(data.systems.map((x) => x.id).join("\n"));
    }
    if (q === "count") return text(String(data.systems.length));

    if (!s) return text("missing param: s", 400);
    const sys = findSystem(data, s);
    if (!sys) return text("unknown system: " + s, 404);

    if (q === "versions") return text(sys.versions.map((x) => x.version).join("\n"));
    if (q === "name") return text(sys.name || s);

    if (!v) return text("missing param: v", 400);
    const ver = findVersion(sys, v);
    if (!ver) return text("unknown version: " + v, 404);

    const d = ver.download || {};
    switch (q) {
      case "url":
        return text(d.url || "");
      case "size":
        return text(String(d.size_bytes || 0));
      case "file":
        return text(ver.file || "");
      case "sha":
        return text((ver.checksum || {}).url || "");
      case "mirrors":
        return text(
          (ver.sources || []).filter((c) => c.ok).map((c) => c.url).join("\n")
        );
      case "json":
        return json({ system: sys.id, name: sys.name, ...ver });
      default:
        return text("unknown q: " + q + "\n\n" + HELP, 400);
    }
  },
};
