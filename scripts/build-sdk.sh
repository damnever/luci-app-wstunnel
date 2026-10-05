#!/bin/sh
set -eu
source_dir=/my/openwrt
output_dir=/my/output
jobs=${BUILD_JOBS:-1}
if [ ! -x scripts/feeds ]; then
	/bin/bash ./setup.sh
fi
[ -w "$output_dir" ] || { echo "Output directory must be writable by the SDK user." >&2; exit 1; }
package_dir=package/luci-app-wstunnel
mkdir -p "$package_dir"
cp "$source_dir/Makefile" "$package_dir/"
cp "$source_dir/LICENSE" "$package_dir/"
cp -R "$source_dir/files" "$package_dir/"
feeds_config=feeds.conf.default
[ ! -f feeds.conf ] || feeds_config=feeds.conf
sed -i \
	-e 's|https://github.com/openwrt/packages\.git|https://git.openwrt.org/feed/packages.git|' \
	-e 's|https://github.com/openwrt/luci\.git|https://git.openwrt.org/project/luci.git|' \
	"$feeds_config"
sed -i '/^src-.*[[:space:]]base[[:space:]]/c\src-git base https://git.openwrt.org/openwrt/openwrt.git^28cf53e6bd9bb68958aae7958e7950d967f02b46' "$feeds_config"
fetch_feed() {
	local feed="$1" revision="$2" repository="$3"
	mkdir -p "feeds/$feed"
	git -C "feeds/$feed" init --quiet
	git -C "feeds/$feed" remote add origin "$repository"
	git -c http.version=HTTP/1.1 -C "feeds/$feed" fetch --depth=1 origin "$revision"
	git -c advice.detachedHead=false -C "feeds/$feed" checkout --detach FETCH_HEAD
	./scripts/feeds update -i "$feed"
}
fetch_feed base 28cf53e6bd9bb68958aae7958e7950d967f02b46 https://git.openwrt.org/openwrt/openwrt.git
fetch_feed packages b5ed85f6e94aa08de1433272dc007550f4a28201 https://git.openwrt.org/feed/packages.git
fetch_feed luci 63ba3cba5b7bfb803a875d4d8f01248634687fd5 https://git.openwrt.org/project/luci.git
./scripts/feeds install luci-compat ca-bundle
cat > .config <<'EOF'
# CONFIG_ALL is not set
# CONFIG_ALL_NONSHARED is not set
# CONFIG_ALL_KMODS is not set
CONFIG_PACKAGE_wstunnel=m
CONFIG_PACKAGE_luci-app-wstunnel=m
EOF
make defconfig
package_arch=$(sed -n 's/^CONFIG_TARGET_ARCH_PACKAGES="\(.*\)"$/\1/p' .config)
echo "SDK package architecture: $package_arch"
if [ -n "${BUILD_PACKAGE_ARCH:-}" ] && [ "$package_arch" != "$BUILD_PACKAGE_ARCH" ]; then
	echo "Expected $BUILD_PACKAGE_ARCH, but SDK builds $package_arch." >&2
	exit 1
fi
grep -Eq '^CONFIG_PACKAGE_wstunnel=[ym]$' .config || { echo "Unsupported SDK architecture." >&2; exit 1; }
grep -Eq '^CONFIG_PACKAGE_luci-app-wstunnel=[ym]$' .config
make "-j$jobs" package/feeds/luci/luci-base/host/compile V=s
make "-j$jobs" package/luci-app-wstunnel/compile NO_DEPS=1 V=s
python3 "$source_dir/scripts/validate-ipk.py" bin "$output_dir"
