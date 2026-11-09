import importlib.util
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "smoke.py"


class Handler(BaseHTTPRequestHandler):
    broken = None

    def do_GET(self):
        if self.path == "/health":
            status, content_type, body = (
                200,
                "application/json",
                b'{"status":"ok","db":"ok"}',
            )
        elif self.path.startswith("/api/"):
            status, content_type, body = (
                401,
                "application/json",
                b'{"code":"unauthenticated"}',
            )
        else:
            status, content_type, body = (
                200,
                "text/html",
                b'<!doctype html><div id="root"></div>',
            )
        if self.broken == "spa-api" and self.path.startswith("/api/"):
            status, content_type, body = (
                200,
                "text/html",
                b"<html>wrong SPA fallback</html>",
            )
        if self.broken == "db" and self.path == "/health":
            body = b'{"status":"ok","db":"error"}'
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class SmokeTests(unittest.TestCase):
    def test_real_http_success_and_wrong_api_or_database(self):
        self.assertTrue(SCRIPT.is_file(), "Нужна HTTP smoke-проверка")
        spec = importlib.util.spec_from_file_location("smoke", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for broken in (None, "spa-api", "db"):
            with self.subTest(broken=broken):
                handler = type("ScenarioHandler", (Handler,), {"broken": broken})
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = f"http://127.0.0.1:{server.server_port}"
                    if broken:
                        with self.assertRaises(module.SmokeError):
                            module.check(url)
                    else:
                        self.assertEqual(len(module.check(url)), 4)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
