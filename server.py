"""Local server for the Nuke web preview.

Endpoints (all JSON unless noted):
  GET  /                       -> viewer.html
  GET  /api/roots              -> configured browse roots
  GET  /api/browse?path=DIR    -> {dirs, files} (.nk files only)
  GET  /api/graph?path=FILE.nk -> parsed graph (cached by mtime)
  GET  /api/versions?path=FILE -> sibling versions (name_v###.nk pattern)
  GET  /api/annotations?path=  -> sidecar annotation doc
  POST /api/annotations?path=  -> save sidecar (<file>.nk.annotations.json)

Run: python server.py [port]
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import nk_parser

_env_roots = [p for p in os.environ.get("NUKE_PREVIEW_ROOTS", "").split(os.pathsep) if p]
ROOTS = [p for p in _env_roots + [
    os.path.expanduser(os.path.join("~", ".nuke", "ToolSets")),
    os.path.expanduser("~"),
] if os.path.isdir(p)]

VERSION_RE = re.compile(r"^(.*?[_.]?[vV])(\d+)(\.nk)$")
_cache = {}


def parse_cached(path):
    st = os.stat(path)
    key = (str(path), st.st_mtime)
    if key not in _cache:
        if len(_cache) > 24:
            _cache.clear()
        _cache[key] = nk_parser.parse_file(path)
    return _cache[key]


def file_info(p):
    st = p.stat()
    return {"name": p.name, "path": str(p), "size": st.st_size,
            "mtime": int(st.st_mtime)}


def versions_of(path):
    p = Path(path)
    m = VERSION_RE.match(p.name)
    if not m or not p.parent.is_dir():
        return [dict(file_info(p), version=None)] if p.exists() else []
    prefix = m.group(1)
    out = []
    for f in p.parent.iterdir():
        if not f.name.lower().endswith(".nk"):
            continue
        m2 = VERSION_RE.match(f.name)
        if m2 and m2.group(1) == prefix:
            out.append(dict(file_info(f), version=int(m2.group(2))))
    out.sort(key=lambda x: x["version"])
    return out


def sidecar(path):
    return Path(str(path) + ".annotations.json")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(
            body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, msg, code=400):
        self._send(code, {"error": msg})

    def _qpath(self):
        q = parse_qs(urlparse(self.path).query)
        return q.get("path", [None])[0]

    def do_GET(self):
        route = urlparse(self.path).path
        try:
            if route in ("/", "/viewer.html", "/index.html"):
                self._send(200, (HERE / "viewer.html").read_bytes(),
                           "text/html; charset=utf-8")
            elif route == "/api/roots":
                self._send(200, {"roots": ROOTS})
            elif route == "/api/browse":
                p = Path(self._qpath() or ROOTS[0])
                if not p.is_dir():
                    return self._err("not a directory: " + str(p))
                dirs, files = [], []
                for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                    try:
                        if c.is_dir():
                            dirs.append({"name": c.name, "path": str(c)})
                        elif c.name.lower().endswith(".nk"):
                            files.append(file_info(c))
                    except OSError:
                        continue
                parent = str(p.parent) if p.parent != p else None
                self._send(200, {"path": str(p), "parent": parent,
                                 "dirs": dirs, "files": files})
            elif route == "/api/graph":
                p = self._qpath()
                if not p or not os.path.isfile(p):
                    return self._err("file not found: " + str(p), 404)
                g = dict(parse_cached(p))
                g["path"] = p
                self._send(200, g)
            elif route == "/api/versions":
                p = self._qpath()
                if not p:
                    return self._err("path required")
                self._send(200, {"versions": versions_of(p)})
            elif route == "/api/annotations":
                p = self._qpath()
                sc = sidecar(p) if p else None
                if sc and sc.exists():
                    self._send(200, sc.read_bytes())
                else:
                    self._send(200, {"state": [], "history": [[]],
                                     "historyIndex": 0})
            else:
                self._err("unknown route: " + route, 404)
        except Exception as e:
            self._err(f"{type(e).__name__}: {e}", 500)

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            if route == "/api/annotations":
                p = self._qpath()
                if not p or not os.path.isfile(p):
                    return self._err("script not found: " + str(p), 404)
                n = int(self.headers.get("Content-Length", 0))
                doc = json.loads(self.rfile.read(n).decode("utf-8"))
                doc["script"] = os.path.basename(p)
                sidecar(p).write_text(
                    json.dumps(doc, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                self._send(200, {"ok": True})
            else:
                self._err("unknown route: " + route, 404)
        except Exception as e:
            self._err(f"{type(e).__name__}: {e}", 500)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    print(f"nuke-web-preview server on http://localhost:{port}  roots={ROOTS}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
