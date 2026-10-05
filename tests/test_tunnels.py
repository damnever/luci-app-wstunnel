import os
import pathlib
import shlex
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "files/root/usr/libexec/wstunnel-validate"
CASES = []
for number, line in enumerate(
    (ROOT / "tests/tunnel_cases.tsv").read_text().splitlines(), start=1
):
    if not line or line.startswith("#"):
        continue
    expected, uri = line.split("\t", 1)
    assert expected in ("valid", "invalid"), f"Invalid fixture at line {number}"
    CASES.append((expected == "valid", uri))

PARSER_ACCEPTED = (
    "error: invalid value 'parser-sentinel://127.0.0.1' "
    "for '<ws[s]|http[s]|wts://wstunnel.server.com[:port]>': "
    "invalid scheme parser-sentinel"
)
EXOTIC_VALID = (
    "tcp://1234:%65xample.org:80",
    "tcp://1234:xn--bcher-kva.example:80",
    "tcp://1234:bücher.example:80",
    "tcp://1234:localhost:80?password=密码",
    "unix:///tmp/套接字.sock:localhost:80",
)
EXOTIC_INVALID = (
    "tcp://1234:bad%20host:80",
    "tcp://1234:bad%2fhost:80",
    "tcp://1234:bad%3ahost:80",
    "tcp://1234:%zz:80",
    "tcp://1234:%FF:80",
    "tcp://1234:xn--:80",
    "tcp://1234:xn--a:80",
    "tcp://1234:bad\u00a0host:80",
    "tcp://1234:bad\u0085host:80",
)


class TunnelValidationTest(unittest.TestCase):
    def validate(self, uri):
        environment = os.environ.copy()
        environment["LUA_PATH"] = str(ROOT / "files/root/usr/lib/lua/?.lua") + ";;"
        return subprocess.run(
            [os.environ.get("WSTUNNEL_LUA", "luajit"), str(VALIDATOR), uri],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_forwarding_address_corpus(self):
        for valid, uri in CASES:
            with self.subTest(uri=uri):
                result = self.validate(uri)
                self.assertEqual(result.returncode, 0 if valid else 1, result.stderr)

    def test_unix_requires_nonempty_socket_path(self):
        # The client parses an empty path but cannot bind it; reject it before apply.
        result = self.validate("unix://:localhost:80")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_unsupported_or_undocumented_addresses(self):
        # The client has additional modes and permissive parsing outside this UI's grammar.
        for uri in ("stdio://localhost:80", "socks5://127.0.0.1:1080:80"):
            with self.subTest(uri=uri):
                result = self.validate(uri)
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_empty_and_control_character_addresses(self):
        for uri in ("", "tcp://1234:local\nhost:80", "socks5://1080\r"):
            with self.subTest(uri=uri):
                result = self.validate(uri)
                self.assertEqual(result.returncode, 1, result.stderr)

    def parser_stub(self, uri, diagnostic=PARSER_ACCEPTED, missing=False):
        environment = os.environ.copy()
        environment.update(
            LUA_PATH=str(ROOT / "files/root/usr/lib/lua/?.lua") + ";;",
            TEST_URI=uri,
            TEST_DIAGNOSTIC=diagnostic,
            TEST_MISSING="1" if missing else "0",
        )
        result = subprocess.run(
            [
                os.environ.get("WSTUNNEL_LUA", "luajit"),
                "-e",
                """
local command, calls, closed = nil, 0, false
io.popen = function(value)
    command, calls = value, calls + 1
    if os.getenv("TEST_MISSING") == "1" then return nil end
    return {
        read = function(_, mode)
            assert(mode == "*l")
            return os.getenv("TEST_DIAGNOSTIC")
        end,
        close = function() closed = true end,
    }
end
local valid = require("wstunnel.tunnel").validate(os.getenv("TEST_URI"))
print(valid and "valid" or "invalid")
print(calls)
print(closed and "closed" or "open")
print(command or "")
""",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.splitlines()

    def test_exotic_addresses_delegate_to_bundled_parser(self):
        for uri in EXOTIC_VALID:
            with self.subTest(uri=uri):
                output = self.parser_stub(uri)
                self.assertEqual(output[:3], ["valid", "1", "closed"])
        output = self.parser_stub("tcp://1234:example.org:80")
        self.assertEqual(output[:3], ["valid", "0", "open"])

    def test_exotic_addresses_fail_closed_without_parser_success(self):
        uri = EXOTIC_VALID[0]
        output = self.parser_stub(uri, missing=True)
        self.assertEqual(output[:3], ["invalid", "1", "open"])
        for diagnostic in (
            "",
            "sh: wstunnel: command not found",
            "error: invalid value for '--local-to-remote'",
            "warning: invalid scheme parser-sentinel",
            PARSER_ACCEPTED + " extra",
            "unexpected output\n" + PARSER_ACCEPTED,
        ):
            with self.subTest(diagnostic=diagnostic):
                output = self.parser_stub(uri, diagnostic=diagnostic)
                self.assertEqual(output[:3], ["invalid", "1", "closed"])

    def test_parser_command_quotes_uri_as_one_shell_argument(self):
        uri = "tcp://1234:%65xample.org:80?password=';$(touch /tmp/injected);\""
        output = self.parser_stub(uri)
        self.assertEqual(output[:3], ["valid", "1", "closed"])
        self.assertEqual(
            shlex.split(output[3]),
            [
                "NO_COLOR=false",
                "/usr/bin/wstunnel",
                "client",
                "--no-color",
                "-L",
                uri,
                "parser-sentinel://127.0.0.1",
                "2>&1",
            ],
        )


@unittest.skipUnless(
    os.environ.get("WSTUNNEL_PARSER_BINARY"),
    "Set WSTUNNEL_PARSER_BINARY to a native pinned v11.0.0 client for parser parity",
)
class PinnedClientParserTest(unittest.TestCase):
    def test_exotic_forwarding_addresses_use_real_bundled_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / "client"
            binary.symlink_to(
                pathlib.Path(os.environ["WSTUNNEL_PARSER_BINARY"]).resolve()
            )
            # Relocate the production adapter's installed executable path;
            # retain its command construction and use the real client parser.
            module = pathlib.Path(directory) / "wstunnel/tunnel.lua"
            module.parent.mkdir()
            module.write_text(
                (ROOT / "files/root/usr/lib/lua/wstunnel/tunnel.lua")
                .read_text()
                .replace(
                    "/usr/bin/wstunnel client", shlex.quote(str(binary)) + " client"
                )
            )
            environment = os.environ.copy()
            environment["LUA_PATH"] = directory + "/?.lua;;"
            # Verify the production adapter controls the inherited color setting.
            environment["NO_COLOR"] = "1"
            for valid, uri in (
                *((True, uri) for uri in EXOTIC_VALID),
                *((False, uri) for uri in EXOTIC_INVALID),
            ):
                with self.subTest(uri=uri):
                    result = subprocess.run(
                        [os.environ.get("WSTUNNEL_LUA", "luajit"), str(VALIDATOR), uri],
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(
                        result.returncode, 0 if valid else 1, result.stderr
                    )
            marker = pathlib.Path(directory) / "injected"
            uri = (
                "tcp://1234:%65xample.org:80?password=';$(touch " + str(marker) + ");'"
            )
            result = subprocess.run(
                [os.environ.get("WSTUNNEL_LUA", "luajit"), str(VALIDATOR), uri],
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            result = subprocess.run(
                [
                    os.fsencode(os.environ.get("WSTUNNEL_LUA", "luajit")),
                    os.fsencode(VALIDATOR),
                    b"tcp://1234:bad\xffhost:80",
                ],
                env=environment,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 1, result.stderr)

    def test_forwarding_address_corpus_matches_client(self):
        environment = os.environ.copy()
        # Some runners set NO_COLOR=1, while this client expects a boolean value.
        environment.pop("NO_COLOR", None)
        binary = os.environ["WSTUNNEL_PARSER_BINARY"]
        version = subprocess.run(
            [binary, "--version"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(version.stdout.strip(), "wstunnel-cli 11.0.0")
        for valid, uri in CASES:
            with self.subTest(uri=uri):
                result = subprocess.run(
                    [
                        binary,
                        "client",
                        "-L",
                        uri,
                        "parser-sentinel://127.0.0.1",
                    ],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 2, output)
                if valid:
                    # The bad server scheme stops the client after parsing the forward.
                    self.assertIn("invalid scheme parser-sentinel", output)
                else:
                    self.assertIn("invalid value", output)
                    self.assertIn("for '--local-to-remote", output)
                    self.assertNotIn("invalid scheme parser-sentinel", output)
