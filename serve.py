#!/usr/bin/env python3
"""Studio 220 server. Serves static files + API backed by PostgreSQL (or pieces.json fallback)."""

import json
import mimetypes
import os
import ssl
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = int(os.environ.get("PORT", 8000))
HTTPS_PORT = 8443
DIR = os.path.dirname(os.path.abspath(__file__))
CERT_DIR = os.path.join(DIR, '.certs')
CERT_FILE = os.path.join(CERT_DIR, 'localhost.pem')
KEY_FILE = os.path.join(CERT_DIR, 'localhost-key.pem')
DATABASE_URL = os.environ.get("DATABASE_URL")

# Ensure .glb files are served with the correct MIME type
mimetypes.add_type('model/gltf-binary', '.glb')

# ── Database helpers ─────────────────────────────────────────────

def get_db():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pieces (
            id                TEXT PRIMARY KEY,
            model             TEXT NOT NULL,
            label             TEXT NOT NULL DEFAULT '',
            notes             TEXT NOT NULL DEFAULT '',
            tags              TEXT[] NOT NULL DEFAULT '{}',
            target_size       REAL NOT NULL DEFAULT 1.4,
            auto_rotate_speed REAL NOT NULL DEFAULT 1.0
        )
    """)
    # Auto-seed from pieces.json if the table is empty
    cur.execute("SELECT COUNT(*) FROM pieces")
    if cur.fetchone()[0] == 0:
        json_path = os.path.join(DIR, 'pieces.json')
        if os.path.exists(json_path):
            with open(json_path) as f:
                for p in json.load(f):
                    cur.execute(
                        "INSERT INTO pieces (id, model, label, notes, tags, target_size, auto_rotate_speed) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (p["id"], p["model"], p["label"], p["notes"],
                         p["tags"], p.get("targetSize", 1.4), p.get("autoRotateSpeed", 1.0))
                    )
            print(f"Seeded database from pieces.json")
    conn.commit()
    cur.close()
    conn.close()


def get_pieces_from_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, model, label, notes, tags, target_size, auto_rotate_speed FROM pieces ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "model": r[1], "label": r[2], "notes": r[3],
         "tags": list(r[4]), "targetSize": r[5], "autoRotateSpeed": r[6]}
        for r in rows
    ]


def save_pieces_to_db(pieces):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pieces")
    for p in pieces:
        cur.execute(
            "INSERT INTO pieces (id, model, label, notes, tags, target_size, auto_rotate_speed) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (p["id"], p["model"], p["label"], p["notes"],
             p["tags"], p.get("targetSize", 1.4), p.get("autoRotateSpeed", 1.0))
        )
    conn.commit()
    cur.close()
    conn.close()


# ── Fallback: pieces.json on disk ────────────────────────────────

def get_pieces_from_file():
    with open(os.path.join(DIR, 'pieces.json')) as f:
        return json.load(f)


def save_pieces_to_file(pieces):
    with open(os.path.join(DIR, 'pieces.json'), 'w') as f:
        json.dump(pieces, f, indent=2)
        f.write('\n')


# ── Unified API ──────────────────────────────────────────────────

def get_pieces():
    return get_pieces_from_db() if DATABASE_URL else get_pieces_from_file()


def save_pieces(pieces):
    if DATABASE_URL:
        save_pieces_to_db(pieces)
    else:
        save_pieces_to_file(pieces)


# ── HTTP handler ─────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        if self.path == '/api/pieces':
            try:
                pieces = get_pieces()
                self._json_response(200, pieces)
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        else:
            super().do_GET()

    def do_POST(self):
        if self.path in ('/api/pieces', '/save-pieces'):
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                save_pieces(data)
                self._json_response(200, {"ok": True})
            except Exception as e:
                self._json_response(400, {"error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


# ── HTTPS cert generation ────────────────────────────────────────

def generate_self_signed_cert():
    os.makedirs(CERT_DIR, exist_ok=True)
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return True
    try:
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', KEY_FILE, '-out', CERT_FILE,
            '-days', '365', '-nodes',
            '-subj', '/CN=localhost',
            '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
        ], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ── Main ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    if DATABASE_URL:
        init_db()
        print(f'Database connected')
    else:
        print(f'No DATABASE_URL — using pieces.json fallback')

    use_https = '--https' in sys.argv
    scheme = 'http'

    if use_https:
        if not generate_self_signed_cert():
            print('Error: could not generate self-signed cert (is openssl installed?)')
            sys.exit(1)
        port = HTTPS_PORT
        server = HTTPServer(('', port), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT_FILE, KEY_FILE)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = 'https'
        print('(self-signed cert — your browser will show a warning)')
    else:
        port = PORT
        server = HTTPServer(('', port), Handler)

    print(f'Studio 220 dev server → {scheme}://localhost:{port}')
    print(f'Spreadsheet editor   → {scheme}://localhost:{port}/spreadsheet.html')
    server.serve_forever()
