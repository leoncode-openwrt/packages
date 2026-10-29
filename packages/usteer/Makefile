include $(TOPDIR)/rules.mk

PKG_NAME:=usteer
PKG_VERSION:=2026.09.07
PKG_RELEASE:=3

# Final reviewed source; runtime/CMake/install files match deployed f0699d0.
USTEER_SOURCE_COMMIT:=947969722087281b874fe7b4dbfe36c5b462c1fc
PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION)-$(USTEER_SOURCE_COMMIT).tar.xz
# stage-sdk.sh places the verified, unpublished source archive here.
PKG_SOURCE_URL:=file://$(TOPDIR)/custom-distfiles
PKG_HASH:=c19f7b38b0f5045c114107a772f9b4c0d88a326b212c59901691e6b470b9f45d

PKG_LICENSE:=GPL-2.0-only
PKG_BUILD_DEPENDS:=libpcap
PKG_BUILD_PARALLEL:=1

include $(INCLUDE_DIR)/package.mk
include $(INCLUDE_DIR)/cmake.mk

CMAKE_OPTIONS += -DBUILD_TESTING=ON

define Package/usteer
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Usteer with bounded remote updates
  DEPENDS:=+libubox +libubus +libblobmsg-json +libnl-tiny
endef

define Package/usteer/description
 Usteer with the deployed MTU-safe remote-update and socket-startup fixes.
 Rebuilt as revision 3 for the OpenWrt 25.12.6 userspace ABI.
endef

define Package/usteer/conffiles
/etc/config/usteer
endef

define Package/usteer/install
	$(INSTALL_DIR) $(1)/sbin $(1)/etc/init.d $(1)/etc/config
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/usteerd $(1)/sbin/
	$(INSTALL_BIN) ./files/etc/init.d/usteer $(1)/etc/init.d/usteer
	$(INSTALL_CONF) ./files/etc/config/usteer $(1)/etc/config/usteer
endef

$(eval $(call BuildPackage,usteer))
