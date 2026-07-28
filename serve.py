#!/usr/bin/env python3
"""Local dev server for Studio 220. Serves static files + handles saving pieces.json and frame layouts."""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import psycopg2

PORT = 8000
DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get('DATABASE_URL', '')


def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        print('WARNING: DATABASE_URL not set — layout save/load disabled')
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS frame_layouts (
            user_id TEXT PRIMARY KEY,
            positions JSONB NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()
    print('Database ready')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def _check_https_redirect(self):
        """Redirect HTTP → HTTPS when behind Porter's load balancer."""
        proto = self.headers.get('X-Forwarded-Proto', '')
        if proto == 'http':
            host = self.headers.get('Host', '')
            self.send_response(301)
            self.send_header('Location', f'https://{host}{self.path}')
            self.end_headers()
            return True
        return False

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length)

    def do_GET(self):
        if self._check_https_redirect():
            return
        parsed = urlparse(self.path)
        if parsed.path == '/api/layout':
            params = parse_qs(parsed.query)
            user_id = params.get('user', [None])[0]
            if not user_id:
                return self._json_response(400, {'error': 'missing user param'})
            if not DATABASE_URL:
                return self._json_response(503, {'error': 'database not configured'})
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute('SELECT positions FROM frame_layouts WHERE user_id = %s', (user_id,))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row:
                    self._json_response(200, {'positions': row[0]})
                else:
                    self._json_response(200, {'positions': None})
            except Exception as e:
                self._json_response(500, {'error': str(e)})
        elif any(part.startswith('.') for part in parsed.path.split('/')):
            # Never serve dotfiles (e.g. /.git/*)
            self.send_response(404)
            self.end_headers()
        else:
            super().do_GET()

    def do_POST(self):
        if self._check_https_redirect():
            return
        if self.path == '/save-pieces':
            body = self._read_body()
            try:
                data = json.loads(body)
                with open(os.path.join(DIR, 'pieces.json'), 'w') as f:
                    json.dump(data, f, indent=2)
                    f.write('\n')
                self._json_response(200, {'ok': True})
            except Exception as e:
                self._json_response(400, {'error': str(e)})

        elif self.path == '/api/layout':
            if not DATABASE_URL:
                return self._json_response(503, {'error': 'database not configured'})
            body = self._read_body()
            try:
                data = json.loads(body)
                user_id = data.get('user')
                positions = data.get('positions')
                if not user_id or positions is None:
                    return self._json_response(400, {'error': 'missing user or positions'})
                conn = get_db()
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO frame_layouts (user_id, positions, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (user_id)
                    DO UPDATE SET positions = EXCLUDED.positions, updated_at = now()
                ''', (user_id, json.dumps(positions)))
                conn.commit()
                cur.close()
                conn.close()
                self._json_response(200, {'ok': True})
            except Exception as e:
                self._json_response(500, {'error': str(e)})

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    init_db()
    print(f'Studio 220 dev server → http://localhost:{PORT}')
    print(f'Spreadsheet editor   → http://localhost:{PORT}/spreadsheet.html')
    HTTPServer(('', PORT), Handler).serve_forever()
