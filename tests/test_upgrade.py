"""Set WSTUNNEL_OPENWRT_TEST=1 and WSTUNNEL_UPGRADE_PACKAGES for opkg verification.

WSTUNNEL_UPGRADE_PACKAGES must select a directory containing built current IPKs.
Old IPKs from that directory are used when available; otherwise, controlled
old-package fixtures reproduce the missing-validator installation.
"""

import io
import os
import pathlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD_VERSION = "11.0.0-1"


def archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        directories = set()
        for name, content, mode in files:
            for parent in reversed(pathlib.PurePosixPath(name).parents):
                if str(parent) != "." and str(parent) not in directories:
                    directory = tarfile.TarInfo("./" + str(parent) + "/")
                    directory.type = tarfile.DIRTYPE
                    directory.mode = 0o755
                    tar.addfile(directory)
                    directories.add(str(parent))
            member = tarfile.TarInfo("./" + name)
            member.size = len(content)
            member.mode = mode
            tar.addfile(member, io.BytesIO(content))
    return output.getvalue()


def fixture(directory, name, version, dependencies, files, conffiles=False):
    control = (
        f"Package: {name}\nVersion: {version}\nArchitecture: all\n"
        f"Depends: {dependencies}\nDescription: Controlled upgrade fixture\n"
    ).encode()
    metadata = [("control", control, 0o644)]
    if conffiles:
        metadata.append(("conffiles", b"/etc/config/wstunnel\n", 0o644))
    path = directory / f"{name}_{version}_all.ipk"
    path.write_bytes(
        archive(
            [
                ("debian-binary", b"2.0\n", 0o644),
                ("control.tar.gz", archive(metadata), 0o644),
                ("data.tar.gz", archive(files), 0o644),
            ]
        )
    )
    return path


def package_fields(path):
    with tarfile.open(path, "r:gz") as outer:
        control_name = next(
            m.name for m in outer if m.name.removeprefix("./") == "control.tar.gz"
        )
        with tarfile.open(
            fileobj=outer.extractfile(control_name), mode="r:gz"
        ) as inner:
            name = next(m.name for m in inner if m.name.removeprefix("./") == "control")
            return dict(
                line.split(": ", 1)
                for line in inner.extractfile(name).read().decode().splitlines()
                if ": " in line
            )


def source_metadata():
    makefile = (ROOT / "Makefile").read_text()
    version = re.search(r"^PKG_VERSION:=(.+)$", makefile, re.M).group(1)
    release = re.search(r"^PKG_RELEASE:=(.+)$", makefile, re.M).group(1)
    return f"{version}-{release}"


@unittest.skipUnless(
    os.environ.get("WSTUNNEL_OPENWRT_TEST") == "1"
    and os.environ.get("WSTUNNEL_UPGRADE_PACKAGES"),
    "Set WSTUNNEL_OPENWRT_TEST=1 and WSTUNNEL_UPGRADE_PACKAGES to built IPKs",
)
class UpgradeTest(unittest.TestCase):
    def test_pair_upgrade_preserves_configuration_and_requires_matching_runtime(self):
        version = source_metadata()
        with tempfile.TemporaryDirectory(
            prefix=".test-upgrade-", dir=ROOT
        ) as temporary:
            directory = pathlib.Path(temporary)
            config = (
                "etc/config/wstunnel",
                (ROOT / "files/root/etc/config/wstunnel").read_bytes(),
                0o600,
            )
            model = (
                "usr/lib/lua/luci/model/cbi/wstunnel.lua",
                (ROOT / "files/luci/model/cbi/wstunnel.lua").read_bytes(),
                0o644,
            )
            fixture(
                directory, "wstunnel", OLD_VERSION, "lua", [config], conffiles=True
            ).rename(directory / "old-runtime.ipk")
            fixture(
                directory,
                "luci-app-wstunnel",
                OLD_VERSION,
                "luci-compat, wstunnel",
                [model],
            ).rename(directory / "old-luci.ipk")
            built = pathlib.Path(os.environ["WSTUNNEL_UPGRADE_PACKAGES"])
            for name, target in (
                ("wstunnel", "runtime"),
                ("luci-app-wstunnel", "luci"),
            ):
                for package_version, prefix in (
                    (version, "new"),
                    (OLD_VERSION, "old"),
                ):
                    packages = list(built.rglob(f"{name}_{package_version}_*.ipk"))
                    if prefix == "old" and not packages:
                        continue
                    self.assertEqual(
                        len(packages),
                        1,
                        f"Expected one built {name} {package_version} IPK",
                    )
                    shutil.copy2(packages[0], directory / f"{prefix}-{target}.ipk")
            runtime_fields = package_fields(directory / "new-runtime.ipk")
            luci_fields = package_fields(directory / "new-luci.ipk")
            self.assertEqual(runtime_fields["Version"], version)
            self.assertEqual(luci_fields["Version"], version)
            self.assertRegex(
                luci_fields.get("Depends", ""),
                rf"(?:^|,\s*)wstunnel\s*\(=\s*{re.escape(version)}\)",
            )
            # Reuse the UI suite's controlled Map/ubus boundary, loading only
            # the installed CBI and Lua module instead of repository copies.
            harness = (
                (ROOT / "tests/test_ui.lua")
                .read_text()
                .split('assert(options._status:cfgvalue("main")', 1)[0]
            )
            harness = "\n".join(harness.splitlines()[1:]).replace(
                'dofile("files/luci/model/cbi/wstunnel.lua")',
                'dofile("/usr/lib/lua/luci/model/cbi/wstunnel.lua")',
            )
            harness += (
                "\n"
                + """
assert(options.local_forward:validate("tcp://127.0.0.1:8080:localhost:80"))
assert(options.local_forward:validate("tcp://127.0.0.1:65536:localhost:80") == nil)
"""
            )
            (directory / "ui-check.lua").write_text(harness)
            script = """set -eu
mkdir -p /var/lock
opkg update >/tmp/prerequisites.log 2>&1 && opkg install lua luci-compat >>/tmp/prerequisites.log 2>&1 || {
    cat /tmp/prerequisites.log >&2
    exit 1
}
# Resolve package versions exclusively from the controlled local IPKs.
rm -f /etc/opkg/distfeeds.conf /etc/opkg/customfeeds.conf
rm -rf /var/opkg-lists/*
# Keep the native x86 architecture for Lua/LuCI dependencies. The target
# wstunnel binary is installed for package verification and never executed.
# Adding any arch line disables opkg's built-in defaults, so preserve them.
opkg print-architecture >/tmp/architectures
cat /tmp/architectures >>/etc/opkg.conf
if ! grep -q "^arch $RUNTIME_ARCH " /tmp/architectures; then
    printf 'arch %s 100\n' "$RUNTIME_ARCH" >>/etc/opkg.conf
fi
opkg install /fixture/old-runtime.ipk /fixture/old-luci.ipk
uci set wstunnel.main.server='wss://preserved.example'
uci commit wstunnel
cp /etc/config/wstunnel /tmp/original-config
if lua -e 'require("wstunnel.tunnel")' >/tmp/old-module.log 2>&1; then
    echo 'Old runtime unexpectedly supplies the validator' >&2
    exit 1
fi
grep -q "module 'wstunnel.tunnel' not found" /tmp/old-module.log
# opkg can exit zero after refusing a package: assert the installed state.
opkg install /fixture/new-luci.ipk >/tmp/rejected.log 2>&1 || true
cat /tmp/rejected.log
test ! -e /usr/lib/lua/wstunnel/tunnel.lua
opkg status wstunnel | grep -qx 'Version: 11.0.0-1'
opkg status luci-app-wstunnel | grep -qx 'Version: 11.0.0-1'
opkg install /fixture/new-runtime.ipk /fixture/new-luci.ipk
opkg status wstunnel | grep -qx "Version: $EXPECTED_VERSION"
opkg status luci-app-wstunnel | grep -qx "Version: $EXPECTED_VERSION"
opkg status wstunnel | grep -q '^Status: .* installed$'
opkg status luci-app-wstunnel | grep -q '^Status: .* installed$'
lua -e 'require("wstunnel.tunnel")'
lua /fixture/ui-check.lua
/usr/libexec/wstunnel-validate 'tcp://127.0.0.1:8080:localhost:80'
if /usr/libexec/wstunnel-validate 'tcp://127.0.0.1:65536:localhost:80'; then exit 1; fi
cmp /etc/config/wstunnel /tmp/original-config
test "$(uci get wstunnel.main.server)" = 'wss://preserved.example'
echo upgrade-passed
"""
            container = "wstunnel-upgrade-" + uuid.uuid4().hex
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                container,
                "--platform",
                "linux/amd64",
                "--mount",
                f"type=bind,src={directory},dst=/fixture,readonly",
                "--env",
                f"RUNTIME_ARCH={runtime_fields['Architecture']}",
                "--env",
                f"EXPECTED_VERSION={version}",
                "--entrypoint",
                "/bin/sh",
                "openwrt/rootfs:x86-64-v23.05.5",
                "-c",
                script,
            ]
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=180
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("upgrade-passed", result.stdout)
            finally:
                subprocess.run(
                    ["docker", "rm", "-f", container], capture_output=True, timeout=30
                )
