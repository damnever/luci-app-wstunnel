import importlib.util
import io
import pathlib
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_ipk", ROOT / "scripts/validate-ipk.py"
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def tar_bytes(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content, permissions in files:
            member = tarfile.TarInfo("./" + name)
            member.mode = permissions
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


class PackageTest(unittest.TestCase):
    def fixture(
        self, directory, mode=0o600, architecture="arm_cortex-a7_neon-vfpv4", machine=40
    ):
        binary = bytearray(32)
        binary[:4] = b"\x7fELF"
        binary[18:20] = machine.to_bytes(2, "little")
        control = f"Package: wstunnel\nVersion: 11.0.0-2\nArchitecture: {architecture}\nDepends: ca-bundle, lua\n".encode()
        payload = tar_bytes(
            [
                ("usr/bin/wstunnel", bytes(binary), 0o755),
                ("etc/init.d/wstunnel", b"#!/bin/sh\n", 0o755),
                ("etc/config/wstunnel", b"config client 'main'\n", mode),
                ("usr/share/licenses/wstunnel/LICENSE", b"License\n", 0o644),
                ("usr/share/licenses/wstunnel/COPYING", b"GPL-3.0\n", 0o644),
                ("usr/lib/lua/wstunnel/tunnel.lua", b"return {}\n", 0o644),
                ("usr/libexec/wstunnel-validate", b"#!/usr/bin/lua\n", 0o755),
            ]
        )
        metadata = tar_bytes(
            [
                ("control", control, 0o644),
                ("conffiles", b"/etc/config/wstunnel\n", 0o644),
            ]
        )
        package = pathlib.Path(directory) / f"wstunnel_11.0.0-2_{architecture}.ipk"
        package.write_bytes(
            tar_bytes(
                [
                    ("debian-binary", b"2.0\n", 0o644),
                    ("control.tar.gz", metadata, 0o644),
                    ("data.tar.gz", payload, 0o644),
                ]
            )
        )
        return package

    def luci_fixture(self, directory, dependency="wstunnel (= 11.0.0-2)"):
        control = (
            "Package: luci-app-wstunnel\nVersion: 11.0.0-2\nArchitecture: all\n"
            f"Depends: libc, luci-compat, {dependency}, wstunnel\n"
        ).encode()
        payload = tar_bytes(
            [
                ("usr/lib/lua/luci/controller/wstunnel.lua", b"controller\n", 0o644),
                ("usr/lib/lua/luci/model/cbi/wstunnel.lua", b"model\n", 0o644),
                ("usr/lib/lua/luci/i18n/wstunnel.zh-cn.lmo", b"translation\n", 0o644),
                ("usr/share/rpcd/acl.d/luci-app-wstunnel.json", b"{}\n", 0o644),
                ("etc/uci-defaults/luci-wstunnel", b"#!/bin/sh\n", 0o755),
                ("usr/share/licenses/luci-app-wstunnel/LICENSE", b"GPL-3.0\n", 0o644),
            ]
        )
        package = pathlib.Path(directory) / "luci-app-wstunnel_11.0.0-2_all.ipk"
        package.write_bytes(
            tar_bytes(
                [
                    ("debian-binary", b"2.0\n", 0o644),
                    ("control.tar.gz", tar_bytes([("control", control, 0o644)]), 0o644),
                    ("data.tar.gz", payload, 0o644),
                ]
            )
        )
        return package

    def test_luci_requires_matching_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            VALIDATOR.validate(self.luci_fixture(directory), "luci-app-wstunnel")

    def test_unversioned_or_stale_luci_runtime_dependency_rejected(self):
        for dependency in (
            "wstunnel",
            "wstunnel (= 11.0.0-1)",
            "wstunnel (>= 11.0.0-1)",
        ):
            with self.subTest(
                dependency=dependency
            ), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(AssertionError):
                    VALIDATOR.validate(
                        self.luci_fixture(directory, dependency), "luci-app-wstunnel"
                    )

    def test_valid_package(self):
        with tempfile.TemporaryDirectory() as directory:
            VALIDATOR.validate(self.fixture(directory), "wstunnel")

    def test_valid_arm64_package(self):
        with tempfile.TemporaryDirectory() as directory:
            VALIDATOR.validate(
                self.fixture(directory, architecture="aarch64_cortex-a53", machine=183),
                "wstunnel",
            )

    def test_armv7_binary_in_arm64_package_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AssertionError):
                VALIDATOR.validate(
                    self.fixture(directory, architecture="aarch64_cortex-a53"),
                    "wstunnel",
                )

    def test_world_readable_config_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AssertionError):
                VALIDATOR.validate(self.fixture(directory, mode=0o644), "wstunnel")

    def test_wrong_machine_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AssertionError):
                VALIDATOR.validate(self.fixture(directory, machine=62), "wstunnel")

    def test_architecture_independent_binary_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AssertionError):
                VALIDATOR.validate(
                    self.fixture(directory, architecture="all"), "wstunnel"
                )
