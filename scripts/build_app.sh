#!/bin/bash
#
# build_app.sh — src/ + assets/ 로부터 .app 번들을 조립한다.
# 결과물: dist/WiFi Profile Manager.app
#
# 파이썬을 내장하지 않는 경량 번들이며, 실행 시 Tk가 동작하는 python3 를 자동 탐색한다.
# 파이썬까지 내장한 완전 독립형이 필요하면 scripts/build_standalone.sh 를 사용할 것.
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="WiFi Profile Manager"
BUNDLE="dist/${APP_NAME}.app"
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' src/wifi_profile_manager.py | head -1)"
[ -n "$VERSION" ] || VERSION="0.0.0"

echo "==> ${APP_NAME} ${VERSION} 번들 생성"

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

cp src/wifi_profile_manager.py src/webui.py "$BUNDLE/Contents/Resources/"
cp assets/AppIcon.icns "$BUNDLE/Contents/Resources/"
cp scripts/launcher.sh "$BUNDLE/Contents/MacOS/WiFiProfileManager"
chmod +x "$BUNDLE/Contents/MacOS/WiFiProfileManager"
printf 'APPL????' > "$BUNDLE/Contents/PkgInfo"

cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>WiFi Profile Manager</string>
	<key>CFBundleDisplayName</key>
	<string>Wi-Fi Profile Manager</string>
	<key>CFBundleIdentifier</key>
	<string>com.local.wifiprofilemanager</string>
	<key>CFBundleVersion</key>
	<string>${VERSION}</string>
	<key>CFBundleShortVersionString</key>
	<string>${VERSION}</string>
	<key>CFBundleExecutable</key>
	<string>WiFiProfileManager</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleSignature</key>
	<string>????</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>LSMinimumSystemVersion</key>
	<string>11.0</string>
	<key>LSApplicationCategoryType</key>
	<string>public.app-category.utilities</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>LSUIElement</key>
	<false/>
	<key>NSLocationUsageDescription</key>
	<string>주변 Wi-Fi 네트워크 목록을 스캔하려면 위치 권한이 필요합니다.</string>
	<key>NSLocationWhenInUseUsageDescription</key>
	<string>주변 Wi-Fi 네트워크 목록을 스캔하려면 위치 권한이 필요합니다.</string>
	<key>NSAppleEventsUsageDescription</key>
	<string>IP 설정 변경을 위한 관리자 인증 창을 표시하는 데 사용됩니다.</string>
	<key>NSHumanReadableCopyright</key>
	<string>MIT License</string>
</dict>
</plist>
PLIST

# macOS에서만 수행 (Apple Silicon에서 애드혹 서명이 없으면 실행이 막힘)
if [ "$(uname -s)" = "Darwin" ]; then
  codesign --force --deep --sign - "$BUNDLE" 2>/dev/null \
    && echo "    애드혹 서명 완료" \
    || echo "    서명 건너뜀 (Xcode 도구 미설치)"
  xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null || true
fi

echo
echo "완료 : $BUNDLE"
echo "설치 : ./scripts/install.sh"
echo "실행 : open \"$BUNDLE\""
