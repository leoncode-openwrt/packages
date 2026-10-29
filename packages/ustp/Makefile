include $(TOPDIR)/rules.mk

PKG_NAME:=ustp
PKG_VERSION:=2026.09.07~8d50cbac
PKG_RELEASE:=3
PKG_SOURCE_DATE:=2026-09-07
PKG_SOURCE_VERSION:=8d50cbac0c54f936dbcc47985957827d6e03a6de
PKG_SOURCE:=ustp-$(PKG_VERSION).tar.xz
# The exact git archive is supplied with this preparation bundle. No network ref.
PKG_SOURCE_URL:=file://$(TOPDIR)/custom-distfiles
PKG_HASH:=943aa57c23cf582f5d853ec453d259dc2fba5a87a0dea4a40bfb0da7ad30f5d8
PKG_LICENSE:=GPL-2.0
PKG_BUILD_FLAGS:=lto

include $(INCLUDE_DIR)/package.mk
include $(INCLUDE_DIR)/cmake.mk

CMAKE_OPTIONS += -DBUILD_TESTING=OFF

define Package/ustp
  SECTION:=net
  CATEGORY:=Network
  TITLE:=OpenWrt STP/RSTP daemon (LeonCode)
  DEPENDS:=+libubox +libubus
endef

TARGET_CFLAGS += -I$(STAGING_DIR)/usr/include

define Package/ustp/install
	$(INSTALL_DIR) $(1)/sbin $(1)/etc/init.d
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/ipkg-install/sbin/* $(1)/sbin/
	$(INSTALL_BIN) ./files/ustpd.init $(1)/etc/init.d/ustpd
endef

$(eval $(call BuildPackage,ustp))
