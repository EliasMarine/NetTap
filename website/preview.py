"""Serve website/dist the way nginx does: the vhost's headers (CSP included), /features -> features.html, and 404.html.

Usage: website/build.sh && python3 website/preview.py [port]   (default 8787, http://127.0.0.1 only)
"""
import http.server
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
DIST = HERE / 'dist'
CONF = (HERE / 'nginx' / 'nettap.dev.conf').read_text()
# The apex server block's headers, minus HSTS (this is plain http on localhost).
HEADERS = [h for h in re.findall(r'add_header ([\w-]+) "([^"]+)" always;', CONF.split('server_name nettap.dev;')[1])
           if h[0] != 'Strict-Transport-Security']


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(DIST), **kwargs)

    def end_headers(self) -> None:
        for name, value in HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def send_head(self):
        path = pathlib.Path(self.translate_path(self.path))
        if not path.exists() and path.with_name(path.name + '.html').is_file():
            self.path = self.path.split('?')[0] + '.html'  # nginx: try_files $uri $uri.html
        return super().send_head()

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        page = DIST / '404.html'
        if code != 404 or not page.is_file():
            return super().send_error(code, message, explain)
        body = page.read_bytes()
        self.send_response(404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)


if __name__ == '__main__':
    if not (DIST / 'index.html').is_file():
        sys.exit('No website/dist yet. Run website/build.sh first.')
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f'Previewing website/dist on http://127.0.0.1:{port}/')
    http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
