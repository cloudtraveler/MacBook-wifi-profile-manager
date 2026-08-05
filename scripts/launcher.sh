#!/bin/bash
#
# Wi-Fi Profile Manager - 앱 번들 런처 v2
#
# Tk 8.5 는 최신 macOS에서 창이 '빈 화면'으로 그려지는 문제가 있으므로
# Tk 8.6 이상을 가진 python3 를 최우선으로 찾는다.
#
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
RES="$(cd "$HERE/../Resources" && pwd)"
SCRIPT="$RES/wifi_profile_manager.py"

LOGDIR="$HOME/.wifi_profile_manager"
LOG="$LOGDIR/launcher.log"
mkdir -p "$LOGDIR" 2>/dev/null || true
log() { echo "$(date '+%F %T') $1" >> "$LOG" 2>/dev/null; }

alert() {
  /usr/bin/osascript -e "display dialog \"$1\" buttons {\"확인\"} default button 1 with icon caution with title \"Wi-Fi Profile Manager\"" >/dev/null 2>&1
}

log "=== launch ==="

# --- 후보 인터프리터 수집 -----------------------------------------------
CANDIDATES=(
  "/opt/homebrew/bin/python3"
  "/usr/local/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
)
# 개발자 도구가 있어야 /usr/bin/python3 가 설치 프롬프트 없이 동작한다
if /usr/bin/xcode-select -p >/dev/null 2>&1; then
  CANDIDATES+=("/usr/bin/python3")
fi
EXTRA="$(command -v python3 2>/dev/null || true)"
[ -n "$EXTRA" ] && CANDIDATES+=("$EXTRA")

# --- 1순위: Tk 8.6 이상 --------------------------------------------------
PY=""
for c in "${CANDIDATES[@]}"; do
  [ -x "$c" ] || continue
  V="$("$c" -c 'import tkinter; print(tkinter.TkVersion)' 2>/dev/null || true)"
  log "check $c -> TkVersion=${V:-none}"
  if [ -n "$V" ] && [ "$(printf '%s\n8.6\n' "$V" | sort -g | head -1)" = "8.6" ]; then
    PY="$c"; log "selected (Tk>=8.6): $PY"; break
  fi
done

# --- 2순위: Tkinter는 있으나 8.5 (경고 후 실행) --------------------------
if [ -z "$PY" ]; then
  for c in "${CANDIDATES[@]}"; do
    [ -x "$c" ] || continue
    if "$c" -c 'import tkinter' >/dev/null 2>&1; then
      PY="$c"
      log "selected (Tk 8.5 → 앱이 브라우저 UI로 자동 전환함): $PY"
      break
    fi
  done
fi

# --- 3순위: Tkinter 없음 → 안내 -----------------------------------------
if [ -z "$PY" ]; then
  for c in "${CANDIDATES[@]}"; do
    [ -x "$c" ] && { PY="$c"; break; }
  done
fi

if [ -z "$PY" ]; then
  log "no python3 found"
  alert "python3 를 찾을 수 없습니다.\n\n터미널에서 다음을 실행해 주세요:\n    xcode-select --install\n\n또는 Homebrew 사용 시:\n    brew install python-tk"
  exit 1
fi

log "exec: $PY $SCRIPT $*"

# CLI 옵션(--list 등)이면 터미널로 그대로 출력,
# Finder에서 GUI로 띄운 경우에는 출력이 사라지므로 로그 파일로 남긴다.
CLI=0
for a in "$@"; do
  case "$a" in
    --*|-h|-v) CLI=1 ;;
  esac
done

if [ "$CLI" -eq 1 ]; then
  exec "$PY" "$SCRIPT" "$@"
else
  exec "$PY" "$SCRIPT" "$@" >> "$LOG" 2>&1
fi
