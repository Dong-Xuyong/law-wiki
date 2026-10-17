// node gh-sync-merge.test.mjs <gh-sync.js>
// Fake GitHub Contents API; checks normal-save merge, three-way deletes, 409 retry once.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

import { spawnSync } from "node:child_process";
const COPIES = ["site/public/dong-ui/gh-sync.js"];
if (!process.argv[2]) {
  for (const rel of COPIES) {
    const p = new URL("../" + rel, import.meta.url).pathname;
    const r = spawnSync(process.execPath, [new URL(import.meta.url).pathname, p], { stdio: "inherit" });
    if (r.status !== 0) process.exit(r.status || 1);
  }
  process.exit(0);
}
const file = process.argv[2];
const src = fs.readFileSync(file, "utf8");
const b64 = (s) => Buffer.from(s, "utf8").toString("base64");

function setup(remoteData, conflicts = 0, store = {}) {
  store["dong-gh-sync"] = JSON.stringify({ token: "t", repo: "Dong-Xuyong/progress-sync" });
  const remote = { sha: "s1", data: remoteData };
  const puts = [];
  let left = conflicts;
  const fetch = async (url, opts) => {
    const method = (opts && opts.method) || "GET";
    if (method === "GET") return { status: 200, ok: true, json: async () => ({ sha: remote.sha, content: b64(JSON.stringify(remote.data)) }) };
    const body = JSON.parse(opts.body);
    puts.push({ sha: body.sha, data: JSON.parse(Buffer.from(body.content, "base64").toString("utf8")) });
    if (left > 0) {
      left--;
      remote.sha = "s" + (puts.length + 1);
      remote.data = { ...remote.data, otherDevice: "kept", items: [...(remote.data.items || []), { id: "b", v: 2 }] };
      return { status: 409, ok: false, json: async () => ({}) };
    }
    remote.sha = "ok"; remote.data = puts.at(-1).data;
    return { status: 200, ok: true, json: async () => ({ content: { sha: "ok" } }) };
  };
  const ctx = {
    fetch, console, setTimeout, clearTimeout, AbortController, escape, unescape, encodeURIComponent, decodeURIComponent,
    btoa: (s) => Buffer.from(s, "binary").toString("base64"), atob: (s) => Buffer.from(s, "base64").toString("binary"),
    localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => (store[k] = v), removeItem: (k) => delete store[k] },
    confirm: () => true, prompt: () => null,
  };
  ctx.window = ctx; ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return { GhSync: ctx.GhSync, puts, remote, store };
}
const save = (G, payload) => G.save("x", () => payload, () => {}, { quiet: true });

{ // normal save, no conflict: a field the app doesn't know survives
  const { GhSync, puts } = setup({ app: "x", agentNote: "keep me", n: 1 });
  assert.equal(await save(GhSync, { app: "x", n: 2 }), "Saved to GitHub");
  assert.equal(puts.length, 1);
  assert.deepEqual(puts[0].data, { app: "x", agentNote: "keep me", n: 2 });
}
{ // deliberate delete sticks: the app wrote `old` last time, now it doesn't
  const store = {};
  let s = setup({ app: "x", old: 1, items: [{ id: "a" }, { id: "z" }] }, 0, store);
  await save(s.GhSync, { app: "x", old: 1, items: [{ id: "a" }, { id: "z" }] }); // base recorded
  s = setup({ app: "x", old: 1, items: [{ id: "a" }, { id: "z" }], agentNote: "new" }, 0, store); // reload page
  await save(s.GhSync, { app: "x", items: [{ id: "a" }] });
  assert.deepEqual(s.puts[0].data, { app: "x", items: [{ id: "a" }], agentNote: "new" });
}
{ // record-level: the app's not-older record replaces the remote one (stale nested keys do not come back)
  const { GhSync, puts } = setup({ items: [{ id: "c", updatedAt: "2026-10-16T08:00", notion: { p: "Low", shelf: "x" } }] });
  await save(GhSync, { items: [{ id: "c", updatedAt: "2026-10-16T12:00", notion: { p: "High" } }] });
  assert.deepEqual(puts[0].data.items[0].notion, { p: "High" });
}
{ // one 409: refetch, merge, retry once
  const { GhSync, puts } = setup({ app: "x", extra: { keep: true }, items: [{ id: "a", v: 1 }], n: 1 }, 1);
  assert.equal(await save(GhSync, { app: "x", items: [{ id: "a", v: 9 }, { id: "c", v: 3 }], n: 2 }), "Saved to GitHub");
  assert.equal(puts.length, 2);
  const d = puts[1].data;
  assert.deepEqual(d.extra, { keep: true });
  assert.equal(d.otherDevice, "kept");
  assert.equal(d.n, 2);
  assert.deepEqual(d.items.map((i) => i.id), ["a", "b", "c"]);
  assert.equal(d.items[0].v, 9);
}
{ // two 409s: exactly one retry, then a non-retry 409
  const { GhSync, puts } = setup({ app: "x" }, 2);
  await assert.rejects(save(GhSync, { app: "x", n: 1 }), (e) => e.status === 409 && !/another device/.test(e.message));
  assert.equal(puts.length, 2);
}
console.log("gh-sync merge tests passed:", file);
