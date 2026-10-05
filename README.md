# LuCI wstunnel client

An OpenWrt client package for [wstunnel](https://github.com/erebe/wstunnel), with LuCI configuration, automatic startup, and process status.

## Build

Requires Docker and network access. Packages are written to `bin/` by default:

```sh
./scripts/build-docker.sh
```

For ARM64 (`aarch64_cortex-a53`):

```sh
BUILD_SDK_IMAGE=docker.io/openwrt/sdk:mediatek-filogic-v23.05.5 \
BUILD_PACKAGE_ARCH=aarch64_cortex-a53 \
BUILD_OUTPUT="$PWD/bin/aarch64_cortex-a53" ./scripts/build-docker.sh
```

## Install

Check `opkg print-architecture`, then copy both matching IPKs to the router:

```sh
opkg update
opkg install /tmp/wstunnel_*.ipk /tmp/luci-app-wstunnel_*.ipk
```

When upgrading, copy and install both packages from the same build. The LuCI
package requires the matching `wstunnel` package, which contains the shared Lua
validator. Package release `11.0.0-2` upgrades older `11.0.0-1` installations.

To check the installed validator:

```sh
lua -e 'require("wstunnel.tunnel")'
```

## Note

- Packages wstunnel **11.0.0** upstream static binaries using the OpenWrt **23.05.5 SDK**, in **IPK** format.
- Built for ARMv7 (`arm_cortex-a7_neon-vfpv4`, default) and ARM64 (`aarch64_cortex-a53`).
- Client-side local forwarding only. No server management, reverse tunnels, or automatic routing/firewall configuration.

## TODO

- [ ] Expand the build matrix for common platforms and verify CPU/ABI, firmware, and package format compatibility.

## Tests

Run `./tests/run.sh` with Python 3 and LuaJIT, or set `WSTUNNEL_LUA=lua5.1`.
Set `WSTUNNEL_PARSER_BINARY` to a pinned v11.0.0 client to also check the forwarding fixtures against its argument parser.
For package upgrade tests, set `WSTUNNEL_OPENWRT_TEST=1` and `WSTUNNEL_UPGRADE_PACKAGES` to the directory containing built IPKs.

## License

This project's code is licensed under [GPL-3.0-only](LICENSE).
The bundled upstream wstunnel binary retains its [BSD-3-Clause license](https://github.com/erebe/wstunnel/blob/v11.0.0/LICENSE).
The wstunnel package includes both licenses; the LuCI package includes GPL-3.0.
