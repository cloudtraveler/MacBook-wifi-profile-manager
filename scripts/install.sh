#!/bin/bash
#
# install.sh — Wi-Fi Profile Manager 설치
#   1) /Applications 로 앱 복사
#   2) 인터넷 다운로드 격리 속성(quarantine) 제거  ← 이걸 안 하면 Gatekeeper가 차단
#   3) 애드혹 코드 서명
#   4) 터미널용 wifi-profile 명령 링크(선택)
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP="dist/WiFi Profile Manager.app"
DEST="/Applications/WiFi Profile Manager.app"

if [ ! -d "$APP" ]; then
  echo "번들이 없어 먼저 빌드합니다."
  ./scripts/build_app.sh
fi
[ -d "$APP" ] || { echo "오류: 번들 생성 실패"; exit 1; }

echo "==> 실행 권한 설정"
chmod +x "$APP/Contents/MacOS/WiFiProfileManager"

echo "==> 격리 속성 제거"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "==> 애드혹 코드 서명"
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "    (서명 건너뜀 — Xcode 도구 미설치)"

echo "==> /Applications 로 설치"
if [ -d "$DEST" ]; then
  echo "    기존 버전 제거"
  rm -rf "$DEST"
fi
cp -R "$APP" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo "==> 터미널 명령 등록 (선택)"
BIN="/usr/local/bin/wifi-profile"
if [ -w "$(dirname "$BIN")" ] 2>/dev/null || sudo -n true 2>/dev/null; then
  sudo mkdir -p /usr/local/bin 2>/dev/null || true
  sudo ln -sf "$DEST/Contents/MacOS/WiFiProfileManager" "$BIN" 2>/dev/null \
    && echo "    등록됨: wifi-profile --list" \
    || echo "    건너뜀 (권한 없음)"
else
  echo "    건너뜀 (sudo 권한 없음)"
fi

echo
echo "설치 완료 → 런치패드 또는 아래 명령으로 실행"
echo "    open \"$DEST\""
