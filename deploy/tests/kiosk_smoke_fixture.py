"""Local TLS and process fixtures for kiosk_smoke.py."""

import http.client
import json
import socket
import ssl
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PUBLIC = "public.localhost"
KIOSK_A = "kiosk-a.localhost"
KIOSK_B = "kiosk-b.localhost"
PING = "/api/terminal/ping"


def certificates(directory, openssl):
    def run(*args):
        subprocess.run([openssl, *args], cwd=directory, check=True, capture_output=True)

    run(
        "req",
        "-x509",
        "-newkey",
        "ec",
        "-pkeyopt",
        "ec_paramgen_curve:P-256",
        "-nodes",
        "-subj",
        "/CN=Regsys Synthetic CA",
        "-keyout",
        "ca.key",
        "-out",
        "ca.pem",
        "-days",
        "2",
        "-addext",
        "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    server_names = ",".join(f"DNS:{host}" for host in (PUBLIC, KIOSK_A, KIOSK_B))
    for name, usage, extra in (
        ("a", "clientAuth", ""),
        ("b", "clientAuth", ""),
        ("server", "serverAuth", f"subjectAltName={server_names}\n"),
    ):
        run(
            "req",
            "-new",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-nodes",
            "-subj",
            f"/CN={name}",
            "-keyout",
            f"{name}.key",
            "-out",
            f"{name}.csr",
        )
        (directory / f"{name}.ext").write_text(
            f"basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            f"extendedKeyUsage={usage}\n{extra}",
            encoding="ascii",
        )
        run(
            "x509",
            "-req",
            "-in",
            f"{name}.csr",
            "-CA",
            "ca.pem",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-days",
            "2",
            "-extfile",
            f"{name}.ext",
            "-out",
            f"{name}.pem",
        )


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@contextmanager
def serve(command, directory, env, port, name):
    with (directory / f"{name}.log").open("wb") as log:
        process = subprocess.Popen(
            command, cwd=directory, env=env, stdout=log, stderr=log
        )
        try:
            for _ in range(160):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} stopped, check {log.name}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError(f"{name} did not listen, check {log.name}")
            yield
        finally:
            process.terminate()
            process.wait(timeout=10)


class KioskClient:
    def __init__(self, directory, port):
        self.directory = directory
        self.port = port

    def origin(self, host):
        return f"https://{host}:{self.port}"

    def request(self, host, path, *, device=None, headers=None, data=None, method=None):
        context = ssl.create_default_context(cafile=self.directory / "ca.pem")
        if device:
            context.load_cert_chain(
                self.directory / f"{device}.pem", self.directory / f"{device}.key"
            )
        connection = http.client.HTTPSConnection(
            host, self.port, timeout=8, context=context
        )
        connection.connect = lambda: connect_loopback(connection, context)
        fields = dict(headers or {})
        if data is not None:
            fields["Content-Type"] = "application/json"
        try:
            connection.request(
                method or ("POST" if data is not None else "GET"),
                path,
                body=json.dumps(data) if data is not None else None,
                headers=fields,
            )
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def assert_tls_denied(self, host, device=None, **kwargs):
        try:
            self.request(host, PING, device=device, **kwargs)
        except (ssl.SSLError, ConnectionResetError):
            return
        raise AssertionError("TLS accepted a missing or mismatched client certificate")


def connect_loopback(connection, context):
    with socket.create_connection(
        ("127.0.0.1", connection.port), connection.timeout
    ) as raw:
        connection.sock = context.wrap_socket(raw, server_hostname=connection.host)


def build_config(directory, spa, api_port, tls_port):
    deploy = REPO / "deploy"
    for filename in ("Caddyfile", "kiosk.caddy"):
        config = (deploy / filename).read_text(encoding="utf-8")
        config = config.replace("/srv/regsys", f'"{spa.as_posix()}"')
        config = config.replace("api:8000", f"127.0.0.1:{api_port}")
        server_tls = f'tls "{(directory / "server.pem").as_posix()}" "{(directory / "server.key").as_posix()}" {{'
        config = config.replace("tls {", server_tls).replace(
            "\n\t\tissuer {$RS_TLS_ISSUER:internal}", ""
        )
        (directory / filename).write_text(config, encoding="utf-8")

    config = directory / "Caddyfile"
    source = config.read_text(encoding="utf-8")
    source = source.replace(
        "admin off",
        "admin off\n\tdefault_bind 127.0.0.1\n\tauto_https disable_redirects",
    )
    config.write_text(source, encoding="utf-8")
    return config


def enable_kiosks(directory, port, token_a, token_b):
    sites = directory / "kiosks" / "sites"
    sites.mkdir(parents=True)
    example = (REPO / "deploy" / "kiosk-site.caddy.example").read_text(encoding="utf-8")
    for label, host, token in (("a", KIOSK_A, token_a), ("b", KIOSK_B, token_b)):
        (directory / f"{label}.token").write_text(token, encoding="ascii")
        site = example.replace("kiosk-a.example.test", f"{host}:{port}")
        site = site.replace(
            "/etc/caddy/kiosks/trust/client-ca.pem",
            f'"{(directory / "ca.pem").as_posix()}"',
        )
        site = site.replace(
            "/etc/caddy/kiosks/trust/kiosk-a.pem",
            f'"{(directory / f"{label}.pem").as_posix()}"',
        )
        site = site.replace(
            "{file./etc/caddy/kiosks/secrets/kiosk-a.token}",
            f'"{{file.{(directory / f"{label}.token").as_posix()}}}"',
        )
        (sites / f"{label}.caddy").write_text(site, encoding="utf-8")
