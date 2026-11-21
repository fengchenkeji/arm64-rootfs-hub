// 本地跑通 worker 的处理器：node worker/test.mjs
// 用仓库内已生成的 api/all.json 当上游，拦截 fetch，验证每种 q 的输出。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const all = JSON.parse(
  fs.readFileSync(path.join(here, "..", "public", "api", "all.json"), "utf8")
);

globalThis.fetch = async (u) => ({
  ok: true,
  status: 200,
  json: async () => all,
});

const { default: worker } = await import("./src/index.js");
const API = "https://api.example/";

const cases = [
  ["/", "ok"],
  ["/?q=list"],
  ["/?q=count"],
  ["/?q=versions&s=debian"],
  ["/?q=name&s=debian"],
  ["/?q=url&s=debian&v=12"],
  ["/?q=size&s=debian&v=12"],
  ["/?q=file&s=debian&v=12"],
  ["/?q=sha&s=debian&v=12"],
  ["/?q=mirrors&s=alpine&v=3.24.4"],
  ["/?q=json&s=ubuntu&v=22.04.5"],
  ["/?q=url&s=nope&v=1"],
  ["/?q=url&s=debian&v=99"],
];

let fail = 0;
for (const [p, expect] of cases) {
  const res = await worker.fetch(new Request(API + p.replace(/^\//, "")));
  const body = (await res.text()).trim();
  const first = body.split("\n")[0];
  if (expect === undefined) {
    if (body.length === 0) { fail++; console.log(`✗ ${p} -> 空`); }
    else console.log(`✓ ${p} [${res.status}] ${body.length > 90 ? first.slice(0, 90) + "…" : body.replace(/\n/g, " | ")}`);
    continue;
  }
  const ok = first === expect;
  if (!ok) fail++;
  console.log(`${ok ? "✓" : "✗"} ${p} [${res.status}] ${JSON.stringify(first)}`);
}
console.log(fail ? `\n${fail} 个失败` : "\n全部通过");
process.exit(fail ? 1 : 0);
