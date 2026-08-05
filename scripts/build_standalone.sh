#!/bin/bash
#
# build_standalone.sh
# ------------------------------------------------------------------
# 파이썬 인터프리터까지 통째로 내장한 "완전 독립형" .app 을 만듭니다.
# (배포 대상 Mac에 python3 가 없어도 실행됨)
#
# 반드시 macOS에서 실행하세요.
#   chmod +x build_standalone.sh && ./build_standalone.sh
# ------------------------------------------------------------------
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="WiFi Profile Manager"
SRC="src/wifi_profile_manager.py"
ICON="assets/AppIcon.icns"

echo "==> 사전 점검"
[ -f "$SRC" ] || { echo "오류: $SRC 가 없습니다."; exit 1; }

if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  cat <<'EOF'
오류: 현재 python3 에 Tkinter가 없습니다. 빌드에 Tkinter가 반드시 필요합니다.

  Homebrew 사용 시 :  brew install python-tk
  또는 python.org 설치본 사용 (Tkinter 기본 포함)
EOF
  exit 1
fi

ARCH="$(uname -m)"
echo "    python3 : $(python3 -V)  ($(command -v python3))"
echo "    아키텍처 : $ARCH"

echo "==> PyInstaller 설치/확인"
python3 -m pip install --quiet --upgrade --user pyinstaller
PYI="$(python3 -c 'import PyInstaller, os, sys; print(sys.executable)')"

echo "==> 기존 빌드 정리"
rm -rf build "dist_standalone" "${APP_NAME}.spec"

echo "==> 빌드 시작 (수 분 소요)"
python3 -m PyInstaller \
  --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --icon "$ICON" \
  --osx-bundle-identifier "com.local.wifiprofilemanager" \
  --distpath "dist_standalone" \
  --hidden-import tkinter \
  --hidden-import tkinter.ttk \
  --hidden-import tkinter.messagebox \
  --add-data "src/webui.py:." \
  "$SRC"

BUNDLE="dist_standalone/${APP_NAME}.app"
PLIST="$BUNDLE/Contents/Info.plist"
[ -d "$BUNDLE" ] || { echo "오류: 번들 생성 실패"; exit 1; }

echo "==> Info.plist 권한 설명 추가 (Wi-Fi 스캔용 위치 권한 등)"
add_str() {
  /usr/libexec/PlistBuddy -c "Delete :$1" "$PLIST" >/dev/null 2>&1 || true
  /usr/libexec/PlistBuddy -c "Add :$1 string $2" "$PLIST"
}
add_str NSLocationUsageDescription "주변 Wi-Fi 네트워크를 스캔하려면 위치 권한이 필요합니다."
add_str NSLocationWhenInUseUsageDescription "주변 Wi-Fi 네트워크를 스캔하려면 위치 권한이 필요합니다."
add_str NSAppleEventsUsageDescription "IP 설정 변경을 위한 관리자 인증 창을 표시하는 데 사용됩니다."
add_str LSMinimumSystemVersion "11.0"
add_str NSHighResolutionCapable "true"

echo "==> 애드혹 코드 서명 (Apple Silicon 실행에 필요)"
codesign --force --deep --sign - "$BUNDLE"
codesign --verify --deep --verbose=2 "$BUNDLE" 2>&1 | tail -3 || true

echo "==> 격리 속성 제거"
xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null || true

echo
echo "완료 : $BUNDLE"
echo "설치 : cp -R \"$BUNDLE\" /Applications/"
echo "실행 : open \"$BUNDLE\""
