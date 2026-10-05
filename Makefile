include $(TOPDIR)/rules.mk

PKG_NAME:=wstunnel
PKG_VERSION:=11.0.0
PKG_RELEASE:=1
PKG_LICENSE:=BSD-3-Clause
PKG_BUILD_DEPENDS:=luci-base/host
PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)
WSTUNNEL_CPU:=$(firstword $(subst +, ,$(call qstrip,$(CONFIG_CPU_TYPE))))

ifeq ($(ARCH),aarch64)
  WSTUNNEL_ARCH:=arm64
  PKG_HASH:=b86abf73e340ed0c3ff9a77a5458aa27213784920ec65513132b36def45edc94
endif
ifeq ($(ARCH),x86_64)
  WSTUNNEL_ARCH:=amd64
  PKG_HASH:=9708a99717b5a951453c2ff7c14c25d3418d02ca7fcb96fdb382a8f2083bab5e
endif
ifeq ($(ARCH),arm)
  ifneq ($(filter cortex-a7 cortex-a9 cortex-a15,$(WSTUNNEL_CPU)),)
    WSTUNNEL_ARCH:=armv7
    PKG_HASH:=50e2855b527869b77402a902b58b83872ddd24271550df289b54729836c8abbc
  endif
endif

PKG_SOURCE:=wstunnel_$(PKG_VERSION)_linux_$(WSTUNNEL_ARCH).tar.gz
PKG_SOURCE_URL:=https://github.com/erebe/wstunnel/releases/download/v$(PKG_VERSION)

include $(INCLUDE_DIR)/package.mk

define Package/wstunnel
	SECTION:=net
	CATEGORY:=Network
	SUBMENU:=VPN
	TITLE:=WebSocket and HTTP2 tunnel client
	URL:=https://github.com/erebe/wstunnel
	DEPENDS:=@(aarch64||x86_64||arm) +ca-bundle
endef

define Package/luci-app-wstunnel
	SECTION:=luci
	CATEGORY:=LuCI
	SUBMENU:=3. Applications
	TITLE:=LuCI support for wstunnel clients
	PKGARCH:=all
	DEPENDS:=+luci-compat +wstunnel
endef

define Build/Prepare
	[ -n "$(WSTUNNEL_ARCH)" ] || { echo "Unsupported wstunnel CPU: $(ARCH) $(WSTUNNEL_CPU)"; exit 1; }
	mkdir -p $(PKG_BUILD_DIR)
	$(TAR) -C $(PKG_BUILD_DIR) -xzf $(DL_DIR)/$(PKG_SOURCE)
endef

define Build/Configure
endef

define Build/Compile
	po2lmo ./files/luci/i18n/wstunnel.zh-cn.po $(PKG_BUILD_DIR)/wstunnel.zh-cn.lmo
endef

define Package/wstunnel/conffiles
/etc/config/wstunnel
endef

define Package/wstunnel/install
	$(INSTALL_DIR) $(1)/usr/bin $(1)/etc/config $(1)/etc/init.d
	$(INSTALL_DIR) $(1)/usr/share/licenses/wstunnel
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/LICENSE $(1)/usr/share/licenses/wstunnel/LICENSE
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/wstunnel $(1)/usr/bin/wstunnel
	$(INSTALL_CONF) ./files/root/etc/config/wstunnel $(1)/etc/config/wstunnel
	$(INSTALL_BIN) ./files/root/etc/init.d/wstunnel $(1)/etc/init.d/wstunnel
endef

define Package/luci-app-wstunnel/install
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/controller $(1)/usr/lib/lua/luci/model/cbi
	$(INSTALL_DATA) ./files/luci/controller/wstunnel.lua $(1)/usr/lib/lua/luci/controller/wstunnel.lua
	$(INSTALL_DATA) ./files/luci/model/cbi/wstunnel.lua $(1)/usr/lib/lua/luci/model/cbi/wstunnel.lua
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/i18n
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/wstunnel.zh-cn.lmo $(1)/usr/lib/lua/luci/i18n/
	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d $(1)/etc/uci-defaults
	$(INSTALL_DATA) ./files/root/usr/share/rpcd/acl.d/luci-app-wstunnel.json $(1)/usr/share/rpcd/acl.d/luci-app-wstunnel.json
	$(INSTALL_BIN) ./files/root/etc/uci-defaults/luci-wstunnel $(1)/etc/uci-defaults/luci-wstunnel
endef

define Package/luci-app-wstunnel/postinst
#!/bin/sh
if [ -z "$${IPKG_INSTROOT}" ]; then
	if [ -f /etc/uci-defaults/luci-wstunnel ]; then
		( . /etc/uci-defaults/luci-wstunnel ) && rm -f /etc/uci-defaults/luci-wstunnel
	fi
	rm -rf /tmp/luci-indexcache /tmp/luci-indexcache.* /tmp/luci-modulecache
	killall -HUP rpcd 2>/dev/null || true
fi
exit 0
endef

$(eval $(call BuildPackage,wstunnel))
$(eval $(call BuildPackage,luci-app-wstunnel))
