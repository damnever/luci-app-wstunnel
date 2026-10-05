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

## Note

- Packages wstunnel **11.0.0** upstream static binaries using the OpenWrt **23.05.5 SDK**, in **IPK** format.
- Built for ARMv7 (`arm_cortex-a7_neon-vfpv4`, default) and ARM64 (`aarch64_cortex-a53`).
- Client-side local forwarding only. No server management, reverse tunnels, or automatic routing/firewall configuration.

## TODO

- [ ] Expand the build matrix for common platforms and verify CPU/ABI, firmware, and package format compatibility.
