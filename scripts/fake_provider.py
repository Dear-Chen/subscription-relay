"""Local fake subscription provider for development / manual testing.

Serves:
  GET /sub         subscription body (Content-Type text/yaml) with extra headers
  GET /redirect    302 redirect to /sub (tests relay redirect handling)
  GET /make_fail   subsequent /sub responses return 500
  GET /make_ok     reset /sub to normal
  GET /state       JSON dump of request state (fetch count, last User-Agent)
"""

import http.server
import json

STATE = {"fail": False, "count": 0, "last_ua": None}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def do_GET(self):
        if self.path == "/make_fail":
            STATE["fail"] = True
            return self._send(200, b"ok")
        if self.path == "/make_ok":
            STATE["fail"] = False
            return self._send(200, b"ok")
        if self.path == "/state":
            return self._send(200, json.dumps(STATE).encode(),
                              {"Content-Type": "application/json"})
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/sub")
            self.end_headers()
            return
        if self.path.startswith("/sub"):
            STATE["last_ua"] = self.headers.get("User-Agent")
            if STATE["fail"]:
                return self._send(500, b"boom")
            STATE["count"] += 1
            body = (
                "proxies:\n"
                f"  # fetch #{STATE['count']}\n"
                f"  - name: node{STATE['count']}\n"
            ).encode()
            return self._send(200, body, {
                "Content-Type": "text/yaml; charset=utf-8",
                "subscription-userinfo":
                    "upload=1; download=2; total=3; expire=1893456000",
                "profile-update-interval": "24",
                "X-Custom-Blocked": "should-not-be-forwarded",
            })
        return self._send(404, b"not found")

    def _send(self, code, body, extra=None):
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    http.server.HTTPServer(("127.0.0.1", 9123), Handler).serve_forever()
