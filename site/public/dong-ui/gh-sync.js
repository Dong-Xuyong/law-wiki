/**
 * dong-ui GitHub progress sync: one JSON file per app in a private repo.
 * The token lives in localStorage, shared by every app on this origin.
 *
 *   GhSync.save(appId, getPayload, applyPayload, { quiet }) -> Promise<message>
 *   GhSync.load(appId, applyPayload)             -> Promise<message>
 */
(function (global) {
  "use strict";

  var CONFIG_KEY = "dong-gh-sync";
  var DEFAULT_REPO = "Dong-Xuyong/progress-sync";
  var API = "https://api.github.com/repos/";

  function getConfig() {
    var cfg = null;
    try {
      cfg = JSON.parse(localStorage.getItem(CONFIG_KEY) || "null");
    } catch (e) {}
    if (cfg && cfg.token) return cfg;
    var token = global.prompt(
      "Paste a GitHub fine-grained token with Contents read/write on " +
        DEFAULT_REPO +
        " only.\nIt is saved in this browser for all your apps."
    );
    if (!token || !token.trim()) throw new Error("No GitHub token, sync cancelled");
    cfg = { token: token.trim(), repo: DEFAULT_REPO };
    localStorage.setItem(CONFIG_KEY, JSON.stringify(cfg));
    return cfg;
  }

  function toBase64(str) {
    return btoa(unescape(encodeURIComponent(str)));
  }

  function fromBase64(b64) {
    return decodeURIComponent(escape(atob(String(b64).replace(/\s/g, ""))));
  }

  function request(cfg, method, path, body) {
    return fetch(API + cfg.repo + "/contents/" + path, {
      method: method,
      cache: "no-store",
      headers: {
        Authorization: "Bearer " + cfg.token,
        Accept: "application/vnd.github+json",
      },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (res) {
      if (res.status === 401) {
        localStorage.removeItem(CONFIG_KEY);
        throw new Error("GitHub token rejected; you will be asked for a new one");
      }
      if (res.status === 404 && method === "GET") return null;
      if (res.status === 409) throw new Error("Saved from another device meanwhile; try again");
      if (!res.ok) throw new Error("GitHub error " + res.status);
      return res.json();
    });
  }

  // dong-ui gh-sync merge (Tom, 2026-10-17). Every save GETs the file and merges before the PUT:
  // merge3(base, local, remote) where base is the payload this app last saved from this browser.
  //  - local wins on fields it has; a field only the remote has is kept unless the app had it in
  //    base (then the app deleted it on purpose and the delete sticks);
  //  - arrays of {id} objects merge per id with the same rule; when both copies carry updatedAt and
  //    the local one is not older, the app's record is taken as-is (record-level replace);
  //  - on a 409: GET again, merge again, PUT once more; a second 409 stops (no third try).
  var BASE_PREFIX = "dong-gh-sync-base:";
  var baseMemo = {};

  function isPlainObject(v) {
    return !!v && typeof v === "object" && !Array.isArray(v);
  }

  function sameJson(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  function hasIds(arr) {
    return Array.isArray(arr) && arr.every(function (x) { return isPlainObject(x) && x.id != null; });
  }

  function indexById(arr) {
    var out = {};
    (arr || []).forEach(function (x) { out[String(x.id)] = x; });
    return out;
  }

  function merge3(base, local, remote) {
    if (local === undefined) return remote;
    if (remote === undefined) return local;
    if (Array.isArray(local) && Array.isArray(remote) && hasIds(local) && hasIds(remote) &&
        (local.length || remote.length)) {
      var b = indexById(hasIds(base) ? base : []);
      var l = indexById(local);
      var out = [];
      var seen = {};
      remote.forEach(function (r) {
        var k = String(r.id);
        seen[k] = true;
        if (k in l) {
          var li = l[k];
          var localNotOlder = li.updatedAt != null && r.updatedAt != null && String(li.updatedAt) >= String(r.updatedAt);
          out.push(localNotOlder ? li : merge3(b[k], li, r));
        } else if (!(k in b)) {
          out.push(r); // new on the remote side
        } // else: the app removed this item on purpose
      });
      local.forEach(function (li) {
        var k = String(li.id);
        if (seen[k]) return;
        if (k in b && sameJson(b[k], li)) return; // unchanged locally, deleted remotely
        out.push(li);
      });
      return out;
    }
    if (isPlainObject(local) && isPlainObject(remote)) {
      var bo = isPlainObject(base) ? base : {};
      var merged = {};
      Object.keys(remote).forEach(function (k) {
        if (k in local) merged[k] = merge3(bo[k], local[k], remote[k]);
        else if (!(k in bo)) merged[k] = remote[k]; // a field this app does not write: keep it
      });
      Object.keys(local).forEach(function (k) {
        if (k in remote) return;
        if (k in bo && sameJson(bo[k], local[k])) return; // unchanged locally, deleted remotely
        merged[k] = local[k];
      });
      return merged;
    }
    return local;
  }

  function loadBase(appId) {
    if (appId in baseMemo) return baseMemo[appId];
    try {
      var raw = global.localStorage && global.localStorage.getItem(BASE_PREFIX + appId);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function saveBase(appId, payload) {
    baseMemo[appId] = JSON.parse(JSON.stringify(payload));
    try {
      if (global.localStorage) global.localStorage.setItem(BASE_PREFIX + appId, JSON.stringify(payload));
    } catch (e) {} // quota: the in-memory copy still covers this session
  }

  function isConflict(err) {
    return !!err && (err.status === 409 || /another device/i.test(String(err.message || "")));
  }

  function mergedBody(appId, message, local, remote) {
    var data = remote && remote.data ? merge3(loadBase(appId), local, remote.data) : local;
    var body = { message: message, content: toBase64(JSON.stringify(data)) };
    if (remote && remote.sha) body.sha = remote.sha;
    return body;
  }

  // remote: the {sha, data} the caller already fetched and passed to applyPayload.
  function putWithRetry(cfg, appId, body, getPayload, applyPayload, remote) {
    var local = getPayload();
    return request(cfg, "PUT", appId + ".json", mergedBody(appId, body.message, local, remote)).then(function (res) {
      saveBase(appId, local);
      return res;
    }, function (err) {
      if (!isConflict(err)) throw err;
      return fetchRemote(cfg, appId).then(function (fresh) {
        if (fresh && fresh.data && typeof applyPayload === "function") applyPayload(fresh.data);
        var local2 = getPayload();
        return request(cfg, "PUT", appId + ".json", mergedBody(appId, body.message, local2, fresh)).then(function (res) {
          saveBase(appId, local2);
          return res;
        }, function (err2) {
          if (!isConflict(err2)) throw err2;
          // Already retried once: report without the "another device" wording so callers stop too.
          var stop = new Error("GitHub file changed again during the merge retry; not retrying");
          stop.status = 409;
          throw stop;
        });
      });
    });
  }

  function fetchRemote(cfg, appId) {
    return request(cfg, "GET", appId + ".json").then(function (file) {
      if (!file) return null;
      return { sha: file.sha, data: JSON.parse(fromBase64(file.content)) };
    });
  }

  function save(appId, getPayload, applyPayload, opts) {
    var cfg;
    if (
      !(opts && opts.quiet) &&
      (!global.confirm("Save " + appId + " progress to GitHub?") ||
        !global.confirm("Are you sure? This updates the copy your other devices load."))
    ) {
      return Promise.reject(new Error("Save cancelled"));
    }
    try {
      cfg = getConfig();
    } catch (e) {
      return Promise.reject(e);
    }
    return fetchRemote(cfg, appId).then(function (remote) {
      if (remote) applyPayload(remote.data);
      var body = {
        message: "Save " + appId + " progress",
        content: toBase64(JSON.stringify(getPayload())),
      };
      if (remote) body.sha = remote.sha;
      return putWithRetry(cfg, appId, body, getPayload, applyPayload, remote).then(function () {
        return "Saved to GitHub";
      });
    });
  }

  function load(appId, applyPayload) {
    var cfg;
    try {
      cfg = getConfig();
    } catch (e) {
      return Promise.reject(e);
    }
    return fetchRemote(cfg, appId).then(function (remote) {
      if (!remote) return "Nothing saved on GitHub yet";
      applyPayload(remote.data);
      return "Imported from GitHub";
    });
  }

  global.GhSync = { save: save, load: load };
})(typeof window !== "undefined" ? window : globalThis);
