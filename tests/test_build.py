import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DockerBuildTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = pathlib.Path(self.temporary.name)
        self.output = self.directory / "output with spaces"
        self.output.mkdir(mode=0o755)
        self.state = self.directory / "docker-state"
        self.state.mkdir()
        docker = self.directory / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "state = pathlib.Path(os.environ['FAKE_DOCKER_STATE'])\n"
            "with (state / 'calls').open('a') as log:\n"
            "    log.write(json.dumps(args) + '\\n')\n"
            "command = args[0]\n"
            "stage = 'init' if command == 'run' else command\n"
            "if stage == os.environ.get('FAIL_STAGE'):\n"
            "    sys.exit(17)\n"
            "if args[:2] == ['image', 'inspect']:\n"
            "    print(os.environ.get('SDK_USER', '1000:1000'))\n"
            "elif args == ['volume', 'create']:\n"
            "    (state / 'volume').mkdir()\n"
            "    print('test-volume')\n"
            "elif command == 'run':\n"
            "    (state / 'initialized').touch()\n"
            "elif command == 'create':\n"
            "    print('test-container')\n"
            "elif command == 'start':\n"
            "    assert (state / 'initialized').exists()\n"
            "    for package in ['wstunnel', 'luci-app-wstunnel']:\n"
            "        (state / 'volume' / (package + '_test.ipk')).write_bytes(b'package')\n"
            "elif command == 'cp':\n"
            "    assert args[1] == 'test-container:/my/output/.'\n"
            "    for package in (state / 'volume').iterdir():\n"
            "        shutil.copyfile(package, pathlib.Path(args[2]) / package.name)\n"
            "elif command == 'rm':\n"
            "    (state / 'container-removed').touch()\n"
            "elif args[:2] == ['volume', 'rm']:\n"
            "    shutil.rmtree(state / 'volume')\n"
        )
        docker.chmod(0o755)

    def run_build(self, **overrides):
        (self.state / "calls").unlink(missing_ok=True)
        (self.state / "container-removed").unlink(missing_ok=True)
        environment = {
            **os.environ,
            "PATH": f"{self.directory}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_STATE": str(self.state),
            "BUILD_OUTPUT": str(self.output),
            "BUILD_SDK_IMAGE": "test/sdk:version",
            "BUILD_JOBS": "2",
            "BUILD_PACKAGE_ARCH": "test-arch",
            **overrides,
        }
        result = subprocess.run(
            [str(ROOT / "scripts/build-docker.sh")],
            env=environment,
            text=True,
            capture_output=True,
        )
        calls = self.state / "calls"
        self.calls = (
            [json.loads(line) for line in calls.read_text().splitlines()]
            if calls.exists()
            else []
        )
        return result

    def test_build_exports_artifacts_and_cleans_resources(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            sorted(package.name for package in self.output.iterdir()),
            ["luci-app-wstunnel_test.ipk", "wstunnel_test.ipk"],
        )
        initializer = next(call for call in self.calls if call[0] == "run")
        self.assertEqual(initializer[initializer.index("--user") + 1], "root")
        self.assertEqual(initializer[-1], "1000:1000")
        build = next(call for call in self.calls if call[0] == "create")
        self.assertIn("type=volume,src=test-volume,dst=/my/output", build)
        self.assertIn(f"type=bind,src={ROOT},dst=/my/openwrt,readonly", build)
        self.assertIn("BUILD_JOBS=2", build)
        self.assertIn("BUILD_PACKAGE_ARCH=test-arch", build)
        self.assertNotIn("--user", build)
        export = next(call for call in self.calls if call[0] == "cp")
        self.assertNotIn("-a", export)
        self.assertTrue((self.state / "container-removed").exists())
        self.assertFalse((self.state / "volume").exists())

    def test_image_without_configured_user_uses_root(self):
        result = self.run_build(SDK_USER="")
        self.assertEqual(result.returncode, 0, result.stderr)
        initializer = next(call for call in self.calls if call[0] == "run")
        self.assertEqual(initializer[-1], "root")

    def test_failed_initialization_or_creation_removes_volume(self):
        for stage in ["init", "create"]:
            with self.subTest(stage=stage):
                result = self.run_build(FAIL_STAGE=stage)
                self.assertEqual(result.returncode, 17, result.stderr)
                self.assertFalse((self.state / "volume").exists())
                self.assertFalse(any(call[0] == "cp" for call in self.calls))

    def test_failed_build_or_export_removes_container_and_volume(self):
        for stage in ["start", "cp"]:
            with self.subTest(stage=stage):
                result = self.run_build(FAIL_STAGE=stage)
                self.assertEqual(result.returncode, 17, result.stderr)
                self.assertTrue((self.state / "container-removed").exists())
                self.assertFalse((self.state / "volume").exists())
                self.assertEqual(list(self.output.iterdir()), [])
                self.assertNotIn("Installable packages:", result.stdout)

    def test_failed_pull_does_not_allocate_volume(self):
        result = self.run_build(FAIL_STAGE="pull")
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertNotIn(["volume", "create"], self.calls)

    def test_invalid_job_count_fails_before_docker(self):
        result = self.run_build(BUILD_JOBS="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls, [])
        self.assertIn("BUILD_JOBS must be a positive integer", result.stderr)


@unittest.skipUnless(
    os.environ.get("WSTUNNEL_DOCKER_TEST") == "1",
    "set WSTUNNEL_DOCKER_TEST=1 to verify with the real SDK image",
)
class RealDockerBuildTest(unittest.TestCase):
    def test_sdk_output_is_writable_and_exported_as_host_user(self):
        image = os.environ.get(
            "BUILD_SDK_IMAGE", "docker.io/openwrt/sdk:mediatek-mt7623-v23.05.5"
        )
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        subprocess.run(["docker", "pull", image], check=True, capture_output=True)
        volume = subprocess.check_output(
            ["docker", "volume", "create"], text=True
        ).strip()
        self.addCleanup(
            subprocess.run,
            ["docker", "volume", "rm", "-f", volume],
            capture_output=True,
        )
        probe = [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--mount",
            f"type=volume,src={volume},dst=/my/output",
            "--entrypoint",
            "/bin/sh",
        ]
        subprocess.run(
            probe
            + [
                "--user",
                "root",
                image,
                "-c",
                "chown 1001:1001 /my/output && chmod 0755 /my/output",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            probe + ["--user", "1000:1000", image, "-c", "test ! -w /my/output"],
            check=True,
            capture_output=True,
        )
        # Keep bind-mounted input on the same Docker-shared path as the checkout.
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            source = pathlib.Path(directory)
            source.chmod(0o755)
            (source / "scripts").mkdir()
            build = source / "scripts/build-docker.sh"
            shutil.copy2(ROOT / "scripts/build-docker.sh", build)
            (source / "scripts/build-sdk.sh").write_text(
                "#!/bin/sh\nset -eu\n"
                '[ "$(id -u)" = 1000 ]\n'
                "[ -w /my/output ]\n"
                "printf 'SDK artifact' > /my/output/wstunnel_test.ipk\n"
                "printf 'LuCI artifact' > /my/output/luci-app-wstunnel_test.ipk\n"
            )
            output = source / "output"
            output.mkdir(mode=0o755)
            original = output.stat()
            result = subprocess.run(
                [str(build)],
                env={
                    **os.environ,
                    "BUILD_OUTPUT": str(output),
                    "BUILD_SDK_IMAGE": image,
                    "BUILD_JOBS": "1",
                },
                text=True,
                capture_output=True,
                timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output.stat().st_uid, original.st_uid)
            self.assertEqual(output.stat().st_mode, original.st_mode)
            for name in ["wstunnel_test.ipk", "luci-app-wstunnel_test.ipk"]:
                package = output / name
                self.assertEqual(package.stat().st_uid, os.getuid())
                self.assertTrue(package.read_bytes().endswith(b"artifact"))
