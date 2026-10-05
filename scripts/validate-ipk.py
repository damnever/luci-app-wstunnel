import io
import pathlib
import re
import shutil
import sys
import tarfile


def members(archive):
    return {member.name.removeprefix("./"): member for member in archive}


def validate(package, name):
    with tarfile.open(package, "r:gz") as archive:
        outer = members(archive)
        assert archive.extractfile(outer["debian-binary"]).read().strip() == b"2.0"
        with tarfile.open(
            fileobj=io.BytesIO(archive.extractfile(outer["control.tar.gz"]).read()),
            mode="r:gz",
        ) as control_archive:
            control_members = members(control_archive)
            control = (
                control_archive.extractfile(control_members["control"]).read().decode()
            )
            fields = dict(
                line.split(": ", 1) for line in control.splitlines() if ": " in line
            )
            assert fields["Package"] == name
            assert fields["Version"] == "11.0.0-2"
            assert (
                package.name
                == f'{name}_{fields["Version"]}_{fields["Architecture"]}.ipk'
            )
            dependencies = re.split(r"[\s,()]+", fields.get("Depends", ""))
            if name == "wstunnel":
                assert fields["Architecture"] != "all"
                assert "ca-bundle" in dependencies
                assert "lua" in dependencies
                assert (
                    "/etc/config/wstunnel"
                    in control_archive.extractfile(control_members["conffiles"])
                    .read()
                    .decode()
                    .splitlines()
                )
            else:
                assert fields["Architecture"] == "all"
                assert "luci-compat" in dependencies and "wstunnel" in dependencies
                assert re.search(
                    r"(?:^|,)\s*wstunnel\s*\(=\s*"
                    + re.escape(fields["Version"])
                    + r"\)\s*(?:,|$)",
                    fields["Depends"],
                ), "LuCI must require the matching wstunnel runtime package"
        with tarfile.open(
            fileobj=io.BytesIO(archive.extractfile(outer["data.tar.gz"]).read()),
            mode="r:gz",
        ) as data_archive:
            data = members(data_archive)
            required = (
                (
                    "usr/bin/wstunnel",
                    "etc/init.d/wstunnel",
                    "etc/config/wstunnel",
                    "usr/lib/lua/wstunnel/tunnel.lua",
                    "usr/libexec/wstunnel-validate",
                    "usr/share/licenses/wstunnel/LICENSE",
                    "usr/share/licenses/wstunnel/COPYING",
                )
                if name == "wstunnel"
                else (
                    "usr/lib/lua/luci/controller/wstunnel.lua",
                    "usr/lib/lua/luci/model/cbi/wstunnel.lua",
                    "usr/lib/lua/luci/i18n/wstunnel.zh-cn.lmo",
                    "usr/share/rpcd/acl.d/luci-app-wstunnel.json",
                    "etc/uci-defaults/luci-wstunnel",
                    "usr/share/licenses/luci-app-wstunnel/LICENSE",
                )
            )
            for path in required:
                assert (
                    path in data and data[path].isfile() and data[path].size > 0
                ), path
                if path in (
                    "usr/bin/wstunnel",
                    "etc/init.d/wstunnel",
                    "etc/uci-defaults/luci-wstunnel",
                    "usr/libexec/wstunnel-validate",
                ):
                    assert data[path].mode & 0o111, path
            if name == "wstunnel":
                assert data["etc/config/wstunnel"].mode & 0o077 == 0
                binary = data_archive.extractfile(data["usr/bin/wstunnel"]).read()
                assert binary[:4] == b"\x7fELF"
                expected = {
                    "arm_cortex-a7_neon-vfpv4": 40,
                    "x86_64": 62,
                    "aarch64_cortex-a53": 183,
                }
                if fields["Architecture"] in expected:
                    assert (
                        int.from_bytes(binary[18:20], "little")
                        == expected[fields["Architecture"]]
                    )


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: validate-ipk.py PACKAGE_DIR OUTPUT_DIR")
    output = pathlib.Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    for name in ("wstunnel", "luci-app-wstunnel"):
        packages = list(pathlib.Path(sys.argv[1]).rglob(name + "_*.ipk"))
        if len(packages) != 1:
            raise SystemExit(f"Expected one {name} IPK, found {len(packages)}")
        validate(packages[0], name)
        shutil.copy2(packages[0], output / packages[0].name)
        print("Validated:", output / packages[0].name)


if __name__ == "__main__":
    main()
