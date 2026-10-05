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
sdk_user=$(docker image inspect --format '{{.Config.User}}' "$image")
volume=
container=
cleanup() {
	[ -z "$container" ] || docker rm -f "$container" >/dev/null || true
	[ -z "$volume" ] || docker volume rm "$volume" >/dev/null || true
}
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# Bind-mount ownership comes from the host, which may use a different SDK UID.
# Build into a disposable volume, then copy artifacts as the invoking host user.
volume=$(docker volume create)
docker run --rm --platform linux/amd64 --user root \
	--mount "type=volume,src=$volume,dst=/my/output" \
	--entrypoint /bin/sh "$image" -c 'chown "$1" /my/output' sh "${sdk_user:-root}"
set --
case "$(uname -m)" in
	arm64|aarch64) set -- --env GNUTLS_CPUID_OVERRIDE=0x1 ;;
esac
container=$(docker create --platform linux/amd64 \
	--mount "type=bind,src=$source_dir,dst=/my/openwrt,readonly" \
	--mount "type=volume,src=$volume,dst=/my/output" \
	--env "BUILD_JOBS=$jobs" --env "BUILD_PACKAGE_ARCH=${BUILD_PACKAGE_ARCH:-}" "$@" \
	"$image" /bin/sh /my/openwrt/scripts/build-sdk.sh)
docker start --attach "$container"
docker cp "$container:/my/output/." "$output_dir/"
echo "Installable packages: $output_dir/wstunnel_*.ipk $output_dir/luci-app-wstunnel_*.ipk"
