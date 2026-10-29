include $(TOPDIR)/rules.mk

PKG_NAME:=ustp
PKG_VERSION:=2026.07.18~64752fd2
PKG_RELEASE:=2
PKG_SOURCE_DATE:=2026-07-18
PKG_SOURCE_VERSION:=64752fd2a3725665733169e6914082aac0d7d625
PKG_SOURCE:=ustp-$(PKG_VERSION).tar.xz
# The exact git archive is supplied with this preparation bundle. No network ref.
PKG_SOURCE_URL:=file://$(TOPDIR)/custom-distfiles
PKG_HASH:=6ad2784da13f87b9c113ec3d0352c3c49579713c5f1d0068cc3a123cf104f58f
PKG_LICENSE:=GPL-2.0
PKG_BUILD_FLAGS:=lto

include $(INCLUDE_DIR)/package.mk
include $(INCLUDE_DIR)/cmake.mk

CMAKE_OPTIONS += -DBUILD_TESTING=OFF

define Package/ustp
  SECTION:=net
  CATEGORY:=Network
  TITLE:=OpenWrt STP/RSTP daemon (router source preserved)
  DEPENDS:=+libubox +libubus
endef

TARGET_CFLAGS += -I$(STAGING_DIR)/usr/include

define Package/ustp/install
	$(INSTALL_DIR) $(1)/sbin $(1)/etc/init.d
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/ipkg-install/sbin/* $(1)/sbin/
	$(INSTALL_BIN) ./files/ustpd.init $(1)/etc/init.d/ustpd
endef

$(eval $(call BuildPackage,ustp))
