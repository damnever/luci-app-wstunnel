import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL_VALIDATOR = """
mkdir -p /var/lock
if ! command -v lua >/dev/null 2>&1; then
    opkg update >/tmp/lua-install.log 2>&1 && opkg install lua >>/tmp/lua-install.log 2>&1 || {
        cat /tmp/lua-install.log >&2
        exit 1
    }
fi
mkdir -p /usr/lib/lua/wstunnel /usr/libexec
cp /project/files/root/usr/lib/lua/wstunnel/tunnel.lua /usr/lib/lua/wstunnel/
cp /project/files/root/usr/libexec/wstunnel-validate /usr/libexec/
chmod +x /usr/libexec/wstunnel-validate
"""


@unittest.skipUnless(
    os.environ.get("WSTUNNEL_OPENWRT_TEST") == "1",
    "Set WSTUNNEL_OPENWRT_TEST=1 for disposable OpenWrt UCI/procd tests",
)
class OpenWrtTest(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("WSTUNNEL_OPENWRT_BINARY"),
        "Set WSTUNNEL_OPENWRT_BINARY to a Linux amd64 v11.0.0 binary",
    )
    def test_real_process_lifecycle(self):
        with tempfile.TemporaryDirectory(
            prefix=".test-openwrt-", dir=ROOT
        ) as directory:
            shutil.copy2(
                os.environ["WSTUNNEL_OPENWRT_BINARY"],
                pathlib.Path(directory) / "wstunnel",
            )
            script = (
                "set -e\n"
                + INSTALL_VALIDATOR
                + """
mkdir -p /var/lock /var/run/ubus
cp /fixture/wstunnel /usr/bin/wstunnel
cp /project/files/root/etc/init.d/wstunnel /etc/init.d/wstunnel
cp /project/files/root/etc/config/wstunnel /etc/config/wstunnel
chmod +x /usr/bin/wstunnel /etc/init.d/wstunnel
ubusd &
procd -S >/tmp/procd.log 2>&1 &
wait_service() {
    expected="$1"
    remaining=15
    while [ "$remaining" -gt 0 ]; do
        state="$(ubus call service list '{"name":"wstunnel"}' | jsonfilter -e '@.wstunnel.instances.main.running' || true)"
        [ "$state" = "$expected" ] && return 0
        remaining=$((remaining - 1))
        sleep 1
    done
    cat /tmp/procd.log >&2
    exit 1
}
remaining=15
until ubus list service 2>/dev/null | grep -q service; do
    remaining=$((remaining - 1))
    [ "$remaining" -gt 0 ] || exit 1
    sleep 1
done
sh /project/files/root/etc/uci-defaults/luci-wstunnel
/etc/init.d/wstunnel enable
test -L /etc/rc.d/S95wstunnel
/etc/init.d/wstunnel start
wait_service ''
uci set wstunnel.main.enabled=1
uci set wstunnel.main.server=ws://127.0.0.1:19090
uci delete wstunnel.main.local_forward
uci add_list wstunnel.main.local_forward='tcp://127.0.0.1:51820:xn--bcher-kva.example:80'
uci commit wstunnel
ubus call service event '{"type":"config.change","data":{"package":"wstunnel"}}'
wait_service true
pid="$(ubus call service list '{"name":"wstunnel"}' | jsonfilter -e '@.wstunnel.instances.main.pid')"
kill -9 "$pid"
remaining=15
while [ "$remaining" -gt 0 ]; do
    replacement="$(ubus call service list '{"name":"wstunnel"}' | jsonfilter -e '@.wstunnel.instances.main.pid' || true)"
    [ -n "$replacement" ] && [ "$replacement" != "$pid" ] && break
    remaining=$((remaining - 1))
    sleep 1
done
[ "$remaining" -gt 0 ]
wait_service true
uci delete wstunnel.main.local_forward
uci add_list wstunnel.main.local_forward='tcp://127.0.0.1:65536:localhost:80'
uci commit wstunnel
ubus call service event '{"type":"config.change","data":{"package":"wstunnel"}}'
wait_service ''
uci delete wstunnel.main.local_forward
uci add_list wstunnel.main.local_forward='tcp://127.0.0.1:51820:bad%20host:80'
uci commit wstunnel
ubus call service event '{"type":"config.change","data":{"package":"wstunnel"}}'
wait_service ''
uci delete wstunnel.main.local_forward
uci add_list wstunnel.main.local_forward='tcp://127.0.0.1:51820:xn--bcher-kva.example:80'
uci commit wstunnel
ubus call service event '{"type":"config.change","data":{"package":"wstunnel"}}'
wait_service true
uci set wstunnel.main.enabled=0
uci commit wstunnel
ubus call service event '{"type":"config.change","data":{"package":"wstunnel"}}'
wait_service ''
/etc/init.d/wstunnel stop
echo lifecycle-passed
"""
            )
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--platform",
                    "linux/amd64",
                    "--mount",
                    f"type=bind,src={ROOT},dst=/project,readonly",
                    "--mount",
                    f"type=bind,src={directory},dst=/fixture,readonly",
                    "--entrypoint",
                    "/bin/sh",
                    "openwrt/rootfs:x86-64-v23.05.5",
                    "-c",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("lifecycle-passed", result.stdout)

    def test_real_uci_and_procd_arguments(self):
        with tempfile.TemporaryDirectory(
            prefix=".test-openwrt-", dir=ROOT
        ) as directory:
            config = pathlib.Path(directory) / "wstunnel"
            config.write_text(
                """config client 'disabled'
    option enabled '0'
config client 'forward'
    option enabled '1'
    option nb_worker_threads '2'
    option server 'wss://example.org'
    list local_forward 'udp://127.0.0.1:51820:localhost:51820?timeout_sec=0'
    list local_forward 'tcp://127.0.0.1:8080:localhost:80'
config client 'second'
    option enabled '1'
    option server 'ws://example.org'
    option tls_verify '0'
    list local_forward 'tcp://127.0.0.1:8081:localhost:80'
config client 'invalid'
    option enabled '1'
    option server 'wss://example.org'
config client 'invalid_port'
    option enabled '1'
    option server 'wss://example.org'
    list local_forward 'tcp://127.0.0.1:65536:localhost:80'
config client 'invalid_address'
    option enabled '1'
    option server 'wss://example.org'
    list local_forward 'tcp://[gggg::1]:8080:localhost:80'
"""
            )
            script = (
                INSTALL_VALIDATOR
                + """mkdir -p /var/lock
cp /fixture/wstunnel /etc/config/wstunnel
chmod 600 /etc/config/wstunnel
initscript=/project/files/root/etc/init.d/wstunnel
. /lib/functions.sh
. /lib/functions/procd.sh
. "$initscript"
procd_open_service wstunnel "$initscript"
start_service
json_set_namespace procd
json_dump
"""
            )
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--platform",
                    "linux/amd64",
                    "--mount",
                    f"type=bind,src={ROOT},dst=/project,readonly",
                    "--mount",
                    f"type=bind,src={directory},dst=/fixture,readonly",
                    "--entrypoint",
                    "/bin/sh",
                    "openwrt/rootfs:x86-64-v23.05.5",
                    "-c",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            service = json.loads(result.stdout)
            self.assertEqual(set(service["instances"]), {"forward", "second"})
            forward = service["instances"]["forward"]
            self.assertEqual(
                forward["command"],
                [
                    "/usr/bin/wstunnel",
                    "client",
                    "--no-color",
                    "--log-lvl",
                    "INFO",
                    "--tls-verify-certificate",
                    "--nb-worker-threads",
                    "2",
                    "-L",
                    "udp://127.0.0.1:51820:localhost:51820?timeout_sec=0",
                    "-L",
                    "tcp://127.0.0.1:8080:localhost:80",
                    "wss://example.org",
                ],
            )
            self.assertEqual(forward["respawn"], ["3600", "5", "5"])
            self.assertTrue(forward["stdout"])
            second = service["instances"]["second"]["command"]
            self.assertNotIn("--tls-verify-certificate", second)
            self.assertIn("-L", second)
            self.assertNotIn("-R", second)
