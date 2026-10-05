import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MakefileTest(unittest.TestCase):
    def inspect(self, architecture, cpu=""):
        with tempfile.TemporaryDirectory() as directory:
            sdk = pathlib.Path(directory)
            (sdk / "include").mkdir()
            (sdk / "rules.mk").write_text(
                'qstrip=$(strip $(subst ",,$(1)))\n'
                "ARCH:=$(call qstrip,$(CONFIG_ARCH))\n"
                "INCLUDE_DIR:=$(TOPDIR)/include\n"
                "BUILD_DIR:=$(TOPDIR)/build\n"
            )
            (sdk / "include/package.mk").write_text("")
            inspect = sdk / "inspect.mk"
            inspect.write_text(
                "inspect:\n\t@printf '%s\\n' '$(WSTUNNEL_ARCH)'\n"
            )
            result = subprocess.run(
                [
                    "make",
                    "-s",
                    "-f",
                    str(ROOT / "Makefile"),
                    "-f",
                    str(inspect),
                    "inspect",
                    f"TOPDIR={sdk}",
                    f'CONFIG_ARCH="{architecture}"',
                    f'CONFIG_CPU_TYPE="{cpu}"',
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            return result.stdout.splitlines()

    def test_default_sdk_cpu_configuration(self):
        self.assertEqual(self.inspect("arm", "cortex-a7+neon-vfpv4")[0], "armv7")

    def test_other_supported_architectures(self):
        self.assertEqual(self.inspect("aarch64")[0], "arm64")
        self.assertEqual(self.inspect("x86_64")[0], "amd64")

    def test_unsupported_cpu_has_no_binary_mapping(self):
        self.assertEqual(self.inspect("arm", "arm1176jzf-s")[0], "")
        self.assertEqual(self.inspect("mips")[0], "")
