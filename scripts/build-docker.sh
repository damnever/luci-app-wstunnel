#!/bin/sh
set -eu
source_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
image=${BUILD_SDK_IMAGE:-docker.io/openwrt/sdk:mediatek-mt7623-v23.05.5}
jobs=${BUILD_JOBS:-1}
output_dir=${BUILD_OUTPUT:-$source_dir/bin}
case "$jobs" in
	''|*[!0-9]*|0*) echo "BUILD_JOBS must be a positive integer." >&2; exit 1 ;;
esac
command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 1; }
docker info >/dev/null
mkdir -p "$output_dir"
output_dir=$(CDPATH='' cd -- "$output_dir" && pwd)
docker pull "$image"
set --
case "$(uname -m)" in
	arm64|aarch64) set -- --env GNUTLS_CPUID_OVERRIDE=0x1 ;;
esac
docker run --rm --platform linux/amd64 \
	--mount "type=bind,src=$source_dir,dst=/my/openwrt,readonly" \
	--mount "type=bind,src=$output_dir,dst=/my/output" \
	--env "BUILD_JOBS=$jobs" --env "BUILD_PACKAGE_ARCH=${BUILD_PACKAGE_ARCH:-}" "$@" \
	"$image" /bin/sh /my/openwrt/scripts/build-sdk.sh
echo "Installable packages: $output_dir/wstunnel_*.ipk $output_dir/luci-app-wstunnel_*.ipk"
