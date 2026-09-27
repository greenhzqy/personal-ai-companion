/* ============================================================
   sense-server.js  --  the smallest useful companion server

   Zero dependencies. Node only. Listens on 127.0.0.1.

   Endpoints
     GET  /                 static files from this folder
     GET  /sense            { idleSec, proc, title, activity }
     GET  /keys?since=N     long-poll: hangs until the key count changes
     POST /keys  {vks:[..]} keyboard watcher reports virtual key codes

   Privacy by design -- do NOT "optimise" these away:
     - only virtual key codes are accepted, never characters
     - the last key + a counter live in memory only, never on disk
     - the server binds 127.0.0.1, never 0.0.0.0
   ============================================================ */
"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const os = require("os");

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 8765);
const SENSE_PS1 = path.join(ROOT, "_sense.ps1");
const SENSE_TTL = 5000;          // reuse a sample for this long (ms)
// Why 5000 and not 1500: each sample spawns PowerShell, measured at ~476-489ms.
// A 1.5s TTL means ~2400 spawns/hour, which fights the whole point of the
// power-saving work. If you want to run this 24/7, replace the spawn-per-request
// design with a long-lived sampler that writes the JSON file every few seconds
// and let this server simply READ that file -- one startup cost instead of 720+
// spawns an hour. See references/5-工程化与护屏.md, "取数成本".
const HOLD_MS = 25000;           // long-poll hold time

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

/* ---------------- sensing ---------------- */
let senseCache = { at: 0, data: null };
let senseBusy = null;

function runSense() {
  return new Promise((resolve) => {
    // A unique output file per call: no race, no shared temp state.
    const out = path.join(os.tmpdir(), "sense-" + process.pid + "-" + Date.now() + ".json");
    let child;
    try {
      // stdio ignored on purpose: some hosts forbid piped stdio for children
      // (node then throws EPERM on spawn). The child writes the result itself.
      child = spawn("powershell.exe", [
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", SENSE_PS1, "-Out", out,
      ], { stdio: "ignore", windowsHide: true });
    } catch (e) {
      return resolve({ ok: false, error: "spawn-failed" });
    }

    let waited = 0;
    const timer = setInterval(() => {
      waited += 60;
      if (fs.existsSync(out)) {
        clearInterval(timer);
        let data = null;
        try { data = JSON.parse(fs.readFileSync(out, "utf8")); } catch (e) {}
        try { fs.unlinkSync(out); } catch (e) {}
        resolve(data || { ok: false, error: "parse-failed" });
        return;
      }
      if (waited >= 2500) {
        clearInterval(timer);
        try { child.kill(); } catch (e) {}
        resolve({ ok: false, error: "sense-timeout" });
      }
    }, 60);
  });
}

function getSense() {
  const now = Date.now();
  if (senseCache.data && now - senseCache.at < SENSE_TTL) {
    return Promise.resolve(senseCache.data);
  }
  if (senseBusy) return senseBusy;              // collapse concurrent calls
  senseBusy = runSense().then((d) => {
    if (d && d.ok) senseCache = { at: Date.now(), data: d };
    senseBusy = null;
    return d;
  });
  return senseBusy;
}

/* ---------------- keyboard push (privacy-preserving) ---------------- */
let lastKeys = [];
let keyAt = 0;
let keyCount = 0;                 // monotonic counter = the long-poll cursor
let waiters = [];

function flushWaiters() {
  const w = waiters;
  waiters = [];
  for (const x of w) { clearTimeout(x.timer); x.send(); }
}

/* ---------------- http ---------------- */
function json(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, {
    "Content-Type": "application/json; charset=utf-8",   // charset: or CJK titles break
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-store",
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  const u = new URL(req.url, "http://127.0.0.1");

  if (u.pathname === "/sense") {
    getSense().then((d) => json(res, 200, d));
    return;
  }

  if (u.pathname === "/keys") {
    if (req.method === "POST") {
      let body = "";
      req.on("data", (c) => { body += c; if (body.length > 4096) req.destroy(); });
      req.on("end", () => {
        try {
          const o = JSON.parse(body);
          const vks = Array.isArray(o.vks)
            ? o.vks.filter((v) => Number.isFinite(v) && v > 0 && v < 256).slice(0, 32)
            : [];
          if (vks.length) {
            lastKeys = vks;               // memory only
            keyAt = Date.now();
            keyCount += vks.length;
            flushWaiters();               // wake every hanging poll immediately
          }
        } catch (e) {}
        json(res, 200, { ok: true });
      });
      return;
    }
    const iAmAt = u.searchParams.get("since");
    if (iAmAt !== null && Number(iAmAt) === keyCount) {
      const w = {};
      w.timer = setTimeout(() => {
        waiters = waiters.filter((x) => x !== w);
        json(res, 200, { ok: true, vks: [], n: keyCount, wait: 1 });
      }, HOLD_MS);
      w.send = () => json(res, 200, { ok: true, vks: lastKeys, at: keyAt, n: keyCount });
      waiters.push(w);
      return;
    }
    json(res, 200, { ok: true, vks: lastKeys, at: keyAt, n: keyCount });
    return;
  }

  /* static files */
  const rel = decodeURIComponent(u.pathname === "/" ? "/wallpaper.html" : u.pathname);
  const file = path.join(ROOT, path.normalize(rel).replace(/^([/\\])+/, ""));
  if (!file.startsWith(ROOT)) { res.writeHead(403); res.end("forbidden"); return; }
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }); res.end("not found"); return; }
    res.writeHead(200, { "Content-Type": MIME[path.extname(file).toLowerCase()] || "application/octet-stream", "Cache-Control": "no-store" });
    res.end(buf);
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log("[companion] listening on http://127.0.0.1:" + PORT);
});

// Fail loudly and machine-readably.
// A server that dies quietly looks identical to one that was never started --
// and the watchdog then either restart-loops, or (worse) logs "restarted"
// while the port stays dead. Exit non-zero with a JSON error instead.
server.on("error", (err) => {
  const code = (err && err.code) || "UNKNOWN";
  const hint =
    code === "EADDRINUSE" ? "port " + PORT + " already in use -- another copy is probably running (check: netstat -ano | findstr :" + PORT + ")" :
    code === "EACCES"     ? "no permission to bind port " + PORT :
                            String((err && err.message) || err);
  console.error(JSON.stringify({ ok: false, error: code, port: PORT, hint: hint, at: Date.now() }));
  process.exit(1);
});
