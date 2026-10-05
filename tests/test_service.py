import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE = ROOT / "files/root/etc/init.d/wstunnel"


class ServiceTest(unittest.TestCase):
    def run_service(self, settings, local=None, remote=None):
        with tempfile.TemporaryDirectory() as directory:
            fixture = pathlib.Path(directory) / "fixture.sh"
            values = {"enabled": "1", "server": "wss://example.com", **settings}
            commands = []
            for key, value in values.items():
                quoted = "'" + value.replace("'", "'\\''") + "'"
                commands.append(f"{key}) fixture_value={quoted} ;;")
            fixture.write_text(
                'config_get() { local fixture_value; case "$3" in\n'
                + "\n".join(commands)
                + '\n*) fixture_value="${4-}" ;; esac; eval "$1=\\"\\$fixture_value\\""; }\n'
                + 'config_get_bool() { config_get "$@"; }\n'
                + 'config_list_foreach() { case "$2" in\n'
                + "\n".join(
                    f"{key}) "
                    + "; ".join(
                        '"$3" ' + "'" + value.replace("'", "'\\''") + "'" + ' "${4-}"'
                        for value in items
                    )
                    + " ;;"
                    for key, items in (
                        ("local_forward", local or []),
                        ("remote_forward", remote or []),
                    )
                    if items
                )
                + "\nesac; }\n"
                + 'procd_open_instance() { printf "OPEN:%s\\n" "$1"; }\n'
                + "procd_close_instance() { echo CLOSE; }\n"
                + 'procd_set_param() { printf "SET:%s\\n" "$@"; }\n'
                + 'procd_append_param() { printf "ARG:%s\\n" "$@"; }\n'
                + 'logger() { printf "ERROR:%s\\n" "$*"; }\n'
                + 'procd_add_reload_trigger() { printf "RELOAD:%s\\n" "$1"; }\n'
            )
            return subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"; . "$2"; start_client main; service_triggers',
                    "test",
                    str(fixture),
                    str(SERVICE),
                ],
                text=True,
                capture_output=True,
                check=True,
            ).stdout

    def test_disabled(self):
        output = self.run_service({"enabled": "0"})
        self.assertNotIn("OPEN:", output)
        self.assertIn("RELOAD:wstunnel", output)

    def test_missing_tunnel(self):
        output = self.run_service({})
        self.assertIn("Missing or unsupported tunnel", output)
        self.assertNotIn("OPEN:", output)

    def test_invalid_server(self):
        output = self.run_service({"server": "--help"}, ["tcp://1234:localhost:80"])
        self.assertIn("Invalid server URL", output)
        self.assertNotIn("OPEN:", output)

    def test_invalid_protocol(self):
        output = self.run_service({}, ["stdio://localhost:80"])
        self.assertIn("Missing or unsupported tunnel", output)
        self.assertNotIn("OPEN:", output)

    def test_invalid_log_level(self):
        self.assertNotIn(
            "OPEN:",
            self.run_service({"log_level": "--help"}, ["tcp://1234:localhost:80"]),
        )

    def test_local_forward_ignores_reverse_arguments(self):
        output = self.run_service(
            {},
            ["tcp://127.0.0.1:1234:localhost:80", "udp://127.0.0.1:1235:localhost:53"],
            ["socks5://127.0.0.1:1080"],
        )
        self.assertEqual(output.count("OPEN:"), 1)
        self.assertEqual(output.count("ARG:-L"), 2)
        self.assertNotIn("ARG:-R", output)
        self.assertIn("ARG:--tls-verify-certificate", output)
        self.assertIn("SET:respawn\nSET:3600\nSET:5\nSET:5", output)
        self.assertIn("ARG:wss://example.com\nSET:respawn", output)

    def test_reverse_only_does_not_start(self):
        output = self.run_service({}, remote=["tcp://127.0.0.1:8080:localhost:80"])
        self.assertNotIn("OPEN:", output)
        self.assertIn("Missing or unsupported tunnel", output)

    def test_worker_threads_default_omitted(self):
        output = self.run_service({}, ["tcp://1234:localhost:80"])
        self.assertNotIn("--nb-worker-threads", output)

    def test_worker_threads_explicit(self):
        output = self.run_service(
            {"nb_worker_threads": "2"}, ["tcp://1234:localhost:80"]
        )
        self.assertIn("ARG:--nb-worker-threads\nARG:2", output)

    def test_invalid_worker_threads_do_not_start(self):
        for value in ("0", "00", "-1", "1.5", "abc", "2;touch /tmp/injected"):
            with self.subTest(value=value):
                output = self.run_service(
                    {"nb_worker_threads": value}, ["tcp://1234:localhost:80"]
                )
                self.assertNotIn("OPEN:", output)
                self.assertIn("Invalid worker thread count", output)

    def test_tls_opt_out_and_optional_arguments(self):
        output = self.run_service(
            {
                "tls_verify": "0",
                "sni": "example.org",
                "path_prefix": "secret",
                "http_proxy": "http://localhost:8888",
                "credentials": "user:password",
            },
            ["tcp://1234:localhost:80"],
        )
        self.assertNotIn("--tls-verify-certificate", output)
        for flag, value in (
            ("--tls-sni-override", "example.org"),
            ("--http-upgrade-path-prefix", "secret"),
            ("--http-proxy", "http://localhost:8888"),
            ("--http-upgrade-credentials", "user:password"),
        ):
            self.assertIn(f"ARG:{flag}\nARG:{value}", output)

    def test_shell_characters_are_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = pathlib.Path(directory) / "injected"
            value = f"tcp://1234:localhost:80?password=$(touch {marker});'"
            output = self.run_service({"credentials": value}, [value])
            self.assertIn("ARG:" + value, output)
            self.assertFalse(marker.exists())

    def test_default_config_and_acl(self):
        config = (ROOT / "files/root/etc/config/wstunnel").read_text()
        self.assertIn("option enabled '0'", config)
        self.assertIn("option tls_verify '1'", config)
        acl = json.loads(
            (
                ROOT / "files/root/usr/share/rpcd/acl.d/luci-app-wstunnel.json"
            ).read_text()
        )
        self.assertEqual(acl["luci-app-wstunnel"]["write"]["uci"], ["wstunnel"])
        self.assertEqual(acl["luci-app-wstunnel"]["read"]["ubus"], {"service": ["list"]})
        self.assertNotIn("ubus", acl["luci-app-wstunnel"]["write"])

    def test_shell_syntax(self):
        for script in (
            SERVICE,
            ROOT / "files/root/etc/uci-defaults/luci-wstunnel",
            ROOT / "tests/run.sh",
        ):
            subprocess.run(["sh", "-n", str(script)], check=True)
