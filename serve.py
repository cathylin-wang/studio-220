#!/usr/bin/env python3
"""Local dev server for Studio 220. Serves static files + handles saving pieces.json."""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 8000
DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_POST(self):
        if self.path == '/save-pieces':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                with open(os.path.join(DIR, 'pieces.json'), 'w') as f:
                    json.dump(data, f, indent=2)
                    f.write('\n')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    print(f'Studio 220 dev server → http://localhost:{PORT}')
    print(f'Spreadsheet editor   → http://localhost:{PORT}/spreadsheet.html')
    HTTPServer(('', PORT), Handler).serve_forever()
