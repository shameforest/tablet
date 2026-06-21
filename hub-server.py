#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hub-Server fuer das Dashboard (laeuft auf dem Raspberry Pi).

Was er macht:
  - Liefert dashboard-v4.html (Tablet) und kontrollzentrum.html (PC) aus.
  - Stellt eine gemeinsame Datenbasis bereit:  GET/POST  /api/data   (data.json)
  - Optional: koppelt Notizen / To-Dos / Zitate mit Obsidian-Markdown-Dateien
    (in beide Richtungen: Obsidian -> Dashboard beim Lesen, Kontrollzentrum -> Obsidian beim Speichern).

Benoetigt KEINE Zusatzpakete - nur Python 3 (>=3.7), das auf dem Pi vorinstalliert ist.

Start:
    python3 hub-server.py
Dann im Browser:  http://<PI-IP>:8080/            (Dashboard)
                  http://<PI-IP>:8080/kontrollzentrum.html   (Kontrollzentrum)
Autostart per systemd: siehe Anleitung am Ende dieser Datei.
"""

import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ========================= KONFIG (anpassen) =========================
HERE       = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = HERE                                   # Ordner mit dashboard-v4.html + kontrollzentrum.html
DATA_FILE  = os.path.join(HERE, "data.json")        # gemeinsame Datenbasis
PORT       = 8080

# --- Obsidian-Kopplung (optional) ---
# Pfad zum Obsidian-Vault auf dem Pi (dorthin synchronisierst du deine Notizen).
# Leer lassen ("") => keine Kopplung; dann kommen alle Inhalte aus data.json.
OBSIDIAN_VAULT = ""                                 # z.B. "/home/pi/Obsidian/MeinVault"
# Dateinamen IM Vault. Pro Feld: Dateiname zum Koppeln, oder "" um dieses Feld NICHT zu koppeln.
MD_NOTES   = "Dashboard/Notizen.md"                 # eine Zeile = ein Stichpunkt
MD_TODOS   = "Dashboard/ToDo.md"                    # Zeilen wie:  - [ ] 09:00 Aufgabe   /   - [x] Erledigt
MD_QUOTES  = "Dashboard/Reminder.md"                # eine Zeile = ein Zitat / Reminder
# =====================================================================

DEFAULTS = {
    "city": "Straelen", "lat": 51.4419, "lon": 6.2667,
    "height": 173, "weight": 115, "age": 30, "sex": "m", "activity": 1.375, "adj": 0,
    "food": [], "todos": [], "notes": "", "quotes": "",
    "sportDays": [], "medDays": [], "journalDays": [], "unrealDays": [],
    "bVal": 450, "bThr": 100, "pin": "1234",
}

# ----------------------------- Helfer --------------------------------
def vault(name):
    return os.path.join(OBSIDIAN_VAULT, name) if (OBSIDIAN_VAULT and name) else None

def coupled_map():
    return {"notes": bool(vault(MD_NOTES)), "quotes": bool(vault(MD_QUOTES)), "todos": bool(vault(MD_TODOS))}

def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None

def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def strip_bullet(line):
    return re.sub(r"^[-*+]\s*", "", line).strip()

# --- Markdown <-> Daten ---
def md_to_lines(text):
    return "\n".join([strip_bullet(l) for l in (text or "").splitlines() if l.strip()])

_TODO = re.compile(r"^[-*+]\s*\[([ xX])\]\s*(.*)$")
_TIME = re.compile(r"^(\d{1,2}:\d{2})\s+(.*)$")
def md_to_todos(text):
    out = []
    for l in (text or "").splitlines():
        if not l.strip():
            continue
        m = _TODO.match(l.strip())
        if m:
            done = m.group(1) in "xX"
            rest = m.group(2).strip()
        else:
            done = False
            rest = strip_bullet(l)
        if not rest:
            continue
        tm = ""
        tmatch = _TIME.match(rest)
        if tmatch:
            tm = tmatch.group(1)
            rest = tmatch.group(2).strip()
        out.append({"time": tm, "text": rest, "done": done})
    return out

def lines_to_md(text):
    body = "\n".join([l for l in (text or "").splitlines()]).strip()
    return body + "\n" if body else ""

def todos_to_md(todos):
    rows = []
    for t in (todos or []):
        txt = (t.get("text") or "").strip()
        if not txt:
            continue
        box = "x" if t.get("done") else " "
        tm = (t.get("time") or "").strip()
        rows.append("- [%s] %s%s" % (box, (tm + " " if tm else ""), txt))
    return ("\n".join(rows) + "\n") if rows else ""

# --- Datenbasis lesen/schreiben ---
def read_json():
    data = dict(DEFAULTS)
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data.update(json.load(f))
    except (OSError, ValueError):
        pass
    return data

def load_data():
    data = read_json()
    p = vault(MD_NOTES)
    if p:
        t = read_text(p)
        if t is not None:
            data["notes"] = md_to_lines(t)
    p = vault(MD_QUOTES)
    if p:
        t = read_text(p)
        if t is not None:
            data["quotes"] = md_to_lines(t)
    p = vault(MD_TODOS)
    if p:
        t = read_text(p)
        if t is not None:
            data["todos"] = md_to_todos(t)
    data["_coupled"] = coupled_map()
    return data

def save_data(incoming):
    incoming = dict(incoming or {})
    incoming.pop("_coupled", None)
    data = read_json()
    data.update(incoming)
    # Gekoppelte Felder zusaetzlich nach Obsidian schreiben - aber nur, wenn der Sender sie mitgeschickt hat.
    # (Das Tablet laesst gekoppelte Felder absichtlich weg, damit es Obsidian nicht ueberschreibt.)
    p = vault(MD_NOTES)
    if p and "notes" in incoming:
        write_text(p, lines_to_md(data.get("notes", "")))
    p = vault(MD_QUOTES)
    if p and "quotes" in incoming:
        write_text(p, lines_to_md(data.get("quotes", "")))
    p = vault(MD_TODOS)
    if p and "todos" in incoming:
        write_text(p, todos_to_md(data.get("todos", [])))
    data.pop("_coupled", None)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data

# ------------------------- HTTP-Handler ------------------------------
CTYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
          ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}

class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/data":
            self._send_json(load_data())
            return
        fname = "dashboard-v4.html" if path in ("/", "") else path.lstrip("/")
        self._serve_static(fname)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/data":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            incoming = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, 400)
            return
        save_data(incoming)
        self._send_json({"ok": True})

    def _serve_static(self, fname):
        safe = os.path.normpath(fname).replace("\\", "/")
        if safe.startswith("..") or safe.startswith("/"):
            self.send_error(403)
            return
        full = os.path.join(STATIC_DIR, safe)
        if not os.path.isfile(full):
            self.send_error(404)
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = CTYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Konsole ruhig halten

if __name__ == "__main__":
    print("Hub-Server laeuft auf http://0.0.0.0:%d" % PORT)
    print("  Dashboard:        http://<PI-IP>:%d/" % PORT)
    print("  Kontrollzentrum:  http://<PI-IP>:%d/kontrollzentrum.html" % PORT)
    if OBSIDIAN_VAULT:
        print("  Obsidian-Vault:   %s" % OBSIDIAN_VAULT)
        print("  gekoppelt:        %s" % coupled_map())
    else:
        print("  Obsidian-Kopplung: AUS (OBSIDIAN_VAULT leer)")
    print("  Strg+C zum Beenden.")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

# =====================================================================
# AUTOSTART per systemd (optional):
#   sudo nano /etc/systemd/system/hub.service
#   ----------------------------------------------------------------
#   [Unit]
#   Description=Dashboard Hub Server
#   After=network-online.target
#
#   [Service]
#   ExecStart=/usr/bin/python3 /home/pi/hub/hub-server.py
#   WorkingDirectory=/home/pi/hub
#   Restart=always
#   User=pi
#
#   [Install]
#   WantedBy=multi-user.target
#   ----------------------------------------------------------------
#   sudo systemctl enable --now hub.service
# =====================================================================
