#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macOS Wi-Fi Profile Manager
---------------------------
- Wi-Fi SSID 프로필(DHCP / STATIC)을 저장/관리
- 주변 스캔 결과와 대조해 '연결 가능 여부' 표시
- 프로필 선택 후 [연결] 시 SSID 접속 + 저장된 IP 설정 적용

필요 환경 : macOS 11 이상, 시스템 python3 (Tkinter 포함)
실행       : python3 wifi_profile_manager.py
"""

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import queue
import ipaddress

import types

try:                                  # GUI가 없는 환경에서도 CLI는 동작하도록 지연 처리
    import tkinter as tk
    from tkinter import ttk, messagebox
    TK_OK = True
except Exception:                     # noqa: BLE001
    TK_OK = False
    ttk = messagebox = None
    tk = types.SimpleNamespace(Tk=object)

APP_NAME = "Wi-Fi Profile Manager"
APP_VERSION = "1.2.0"
APP_DIR = os.path.expanduser("~/.wifi_profile_manager")
CONF_PATH = os.path.join(APP_DIR, "profiles.json")
KEYCHAIN_SVC = "wifi-profile-manager"
AIRPORT = ("/System/Library/PrivateFrameworks/Apple80211.framework"
           "/Versions/Current/Resources/airport")
NETSETUP = "/usr/sbin/networksetup"


# ---------------------------------------------------------------- shell utils
def run(cmd, timeout=30):
    """리스트 형태의 명령 실행 -> (rc, stdout, stderr)"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", "command not found: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:                                   # noqa: BLE001
        return 1, "", str(exc)


def as_quote(text):
    """AppleScript 문자열 리터럴 escape"""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_admin(shell_cmd, timeout=180):
    """
    관리자 권한이 필요한 셸 명령을 osascript 로 실행.
    GUI 암호 입력창이 1회만 뜨도록 여러 명령은 ' && ' 로 묶어서 전달할 것.
    """
    script = "do shell script %s with administrator privileges" % as_quote(shell_cmd)
    return run(["osascript", "-e", script], timeout=timeout)


# ------------------------------------------------------------ macOS wifi info
def detect_wifi_device():
    """Wi-Fi 하드웨어 포트의 디바이스명(en0 등)"""
    rc, out, _ = run([NETSETUP, "-listallhardwareports"])
    if rc == 0:
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 3, len(lines))):
                    m = re.match(r"Device:\s*(\S+)", lines[j].strip())
                    if m:
                        return m.group(1)
    return "en0"


def detect_wifi_service(device):
    """해당 디바이스에 매핑된 네트워크 서비스명(보통 'Wi-Fi')"""
    rc, out, _ = run([NETSETUP, "-listnetworkserviceorder"])
    if rc == 0:
        name = None
        for line in out.splitlines():
            m = re.match(r"\(\d+\)\s+(.+)", line.strip())
            if m:
                name = m.group(1).strip()
                continue
            m2 = re.search(r"Device:\s*(\w+)\)", line)
            if m2 and m2.group(1) == device and name:
                return name
    return "Wi-Fi"


def current_ssid(device):
    rc, out, _ = run([NETSETUP, "-getairportnetwork", device], timeout=10)
    m = re.search(r"Current Wi-Fi Network:\s*(.+)", out)
    if m:
        return m.group(1).strip()
    return None


def current_ip(device):
    rc, out, _ = run(["ipconfig", "getifaddr", device], timeout=10)
    return out.strip() if rc == 0 and out.strip() else None


def power_on(device):
    run([NETSETUP, "-setairportpower", device, "on"], timeout=15)


def _scan_with_airport():
    """구버전 macOS(~14.3) 전용 airport -s"""
    if not os.path.exists(AIRPORT):
        return None
    rc, out, _ = run([AIRPORT, "-s"], timeout=40)
    if rc != 0 or not out:
        return None
    found = {}
    for line in out.splitlines()[1:]:
        m = re.match(r"\s*(.+?)\s+([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\s+(-?\d+)", line)
        if m:
            ssid = m.group(1).strip()
            rssi = int(m.group(3))
            if ssid and (ssid not in found or rssi > found[ssid]):
                found[ssid] = rssi
    return found or None


def _walk_json(node, key, bag):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                bag.append(v)
            _walk_json(v, key, bag)
    elif isinstance(node, list):
        for v in node:
            _walk_json(v, key, bag)


def _scan_with_system_profiler():
    """macOS 14.4+ 대응 (airport 제거됨). 위치 서비스 권한 필요."""
    rc, out, _ = run(["system_profiler", "-json", "SPAirPortDataType"], timeout=60)
    if rc != 0 or not out:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None

    found = {}

    def add(entry):
        if not isinstance(entry, dict):
            return
        ssid = entry.get("_name")
        if not ssid:
            return
        rssi = -100
        sn = entry.get("spairport_signal_noise") or ""
        m = re.search(r"(-?\d+)\s*dBm", str(sn))
        if m:
            rssi = int(m.group(1))
        if ssid not in found or rssi > found[ssid]:
            found[ssid] = rssi

    bag = []
    _walk_json(data, "spairport_airport_other_local_wireless_networks", bag)
    for group in bag:
        if isinstance(group, list):
            for e in group:
                add(e)

    bag = []
    _walk_json(data, "spairport_current_network_information", bag)
    for e in bag:
        add(e)

    return found or None


def scan_networks():
    """주변 SSID -> RSSI dict, 실패 시 None"""
    return _scan_with_airport() or _scan_with_system_profiler()


def preferred_networks(device):
    rc, out, _ = run([NETSETUP, "-listpreferredwirelessnetworks", device], timeout=15)
    if rc != 0:
        return []
    return [l.strip() for l in out.splitlines()[1:] if l.strip()]


# ---------------------------------------------------------------- keychain
def keychain_set(ssid, password):
    if not password:
        return
    run(["security", "add-generic-password", "-U",
         "-a", os.environ.get("USER", "user"),
         "-s", "%s:%s" % (KEYCHAIN_SVC, ssid),
         "-w", password], timeout=15)


def keychain_get(ssid):
    rc, out, _ = run(["security", "find-generic-password",
                      "-a", os.environ.get("USER", "user"),
                      "-s", "%s:%s" % (KEYCHAIN_SVC, ssid), "-w"], timeout=15)
    return out if rc == 0 and out else ""


def keychain_del(ssid):
    run(["security", "delete-generic-password",
         "-a", os.environ.get("USER", "user"),
         "-s", "%s:%s" % (KEYCHAIN_SVC, ssid)], timeout=15)


# ---------------------------------------------------------------- data store
DEFAULT_PROFILE = {
    "ssid": "",
    "location": "",          # 위치 정보 (예: 본사 3층, 자택, A공장 라인1)
    "mode": "dhcp",          # dhcp | static
    "ip": "",
    "subnet": "255.255.255.0",
    "router": "",
    "dns": "",               # 콤마/공백 구분
    "search": "",            # 검색 도메인
    "has_password": False,
}


class Store:
    def __init__(self, path=CONF_PATH):
        self.path = path
        self.profiles = []
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, list):
                self.profiles = [dict(DEFAULT_PROFILE, **p) for p in data]
        except (IOError, ValueError):
            self.profiles = []

    def save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(self.profiles, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def find(self, ssid):
        for p in self.profiles:
            if p["ssid"] == ssid:
                return p
        return None

    def upsert(self, prof):
        old = self.find(prof["ssid"])
        if old:
            old.update(prof)
        else:
            self.profiles.append(prof)
        self.save()

    def delete(self, ssid):
        self.profiles = [p for p in self.profiles if p["ssid"] != ssid]
        self.save()


# ---------------------------------------------------------------- validation
def valid_ipv4(text):
    try:
        ipaddress.IPv4Address(text.strip())
        return True
    except ValueError:
        return False


def valid_mask(text):
    try:
        ipaddress.IPv4Network("0.0.0.0/%s" % text.strip())
        return True
    except ValueError:
        return False


def split_list(text):
    return [t for t in re.split(r"[,\s]+", (text or "").strip()) if t]


def validate_profile(prof):
    """오류 메시지 리스트 반환 (빈 리스트면 정상)"""
    errs = []
    if not prof["ssid"].strip():
        errs.append("SSID를 입력하세요.")
    if prof["mode"] == "static":
        if not valid_ipv4(prof["ip"]):
            errs.append("IP 주소 형식이 올바르지 않습니다.")
        if not valid_mask(prof["subnet"]):
            errs.append("서브넷 마스크 형식이 올바르지 않습니다.")
        if not valid_ipv4(prof["router"]):
            errs.append("라우터(게이트웨이) 주소 형식이 올바르지 않습니다.")
        if valid_ipv4(prof["ip"]) and valid_ipv4(prof["router"]) and valid_mask(prof["subnet"]):
            net = ipaddress.IPv4Network("%s/%s" % (prof["ip"], prof["subnet"]), strict=False)
            if ipaddress.IPv4Address(prof["router"]) not in net:
                errs.append("라우터가 IP/서브넷과 같은 대역이 아닙니다.")
    for d in split_list(prof["dns"]):
        if not valid_ipv4(d):
            errs.append("DNS 주소가 올바르지 않습니다: %s" % d)
    return errs


# ---------------------------------------------------------------- apply / connect
def build_ipconfig_cmds(service, prof):
    q = shlex.quote
    cmds = []
    if prof["mode"] == "static":
        cmds.append("%s -setmanual %s %s %s %s" % (
            NETSETUP, q(service), q(prof["ip"].strip()),
            q(prof["subnet"].strip()), q(prof["router"].strip())))
    else:
        cmds.append("%s -setdhcp %s" % (NETSETUP, q(service)))

    dns = split_list(prof["dns"])
    if dns:
        cmds.append("%s -setdnsservers %s %s" % (
            NETSETUP, q(service), " ".join(q(d) for d in dns)))
    else:
        cmds.append("%s -setdnsservers %s Empty" % (NETSETUP, q(service)))

    search = split_list(prof["search"])
    if search:
        cmds.append("%s -setsearchdomains %s %s" % (
            NETSETUP, q(service), " ".join(q(s) for s in search)))
    else:
        cmds.append("%s -setsearchdomains %s Empty" % (NETSETUP, q(service)))
    return cmds


def join_ssid(device, ssid, password):
    cmd = [NETSETUP, "-setairportnetwork", device, ssid]
    if password:
        cmd.append(password)
    rc, out, err = run(cmd, timeout=60)
    msg = (out + " " + err).strip()
    ok = rc == 0 and "Failed" not in msg and "Could not" not in msg
    return ok, msg or ("연결 요청 완료: %s" % ssid)


# ---------------------------------------------------------------- GUI
class App(tk.Tk):
    POLL_MS = 120

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1300x720")
        self.minsize(1150, 650)

        self.store = Store()
        self.device = detect_wifi_device()
        self.service = detect_wifi_service(self.device)
        self.scan_result = {}
        self.cur_ssid = None
        self.rows = []                 # treeview iid -> ssid
        self.q = queue.Queue()
        self.busy = False

        self._build_ui()
        self.update_idletasks()
        self.after(self.POLL_MS, self._pump)
        self.after(60, self._kick_redraw)
        self.after(300, self.refresh_async)

    # ---------------------------------------------------------- UI 구성
    def _kick_redraw(self):
        """
        Tk 8.5 + 최신 macOS 조합에서 창 내용이 그려지지 않는 문제 회피.
        창을 앞으로 끌어오고, 1픽셀 리사이즈를 유발해 강제로 다시 그리게 한다.
        """
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
            self.after(600, lambda: self.attributes("-topmost", False))
        except Exception:                                      # noqa: BLE001
            pass
        try:
            self.update_idletasks()
            w = self.winfo_width() or 1300
            h = self.winfo_height() or 720
            self.geometry("%dx%d" % (w, h + 1))
            self.after(120, lambda: self.geometry("%dx%d" % (w, h)))
            self.after(240, self.update)
        except Exception:                                      # noqa: BLE001
            pass

    def _build_ui(self):
        style = ttk.Style(self)
        # Tk 8.5의 aqua 테마는 최신 macOS에서 위젯이 안 그려지는 사례가 있어
        # 8.6 미만이면 순수 Tk로 그리는 clam 테마를 사용한다.
        wanted = ["aqua", "clam", "default"] if tk.TkVersion >= 8.6 \
            else ["clam", "default", "aqua"]
        for name in wanted:
            try:
                style.theme_use(name)
                break
            except Exception:                                  # noqa: BLE001
                continue

        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill="x")

        self.var_status = tk.StringVar(value="준비 중…")
        ttk.Label(top, textvariable=self.var_status,
                  font=("Helvetica", 12, "bold")).pack(side="left")

        self.btn_scan = ttk.Button(top, text="스캔 새로고침", command=self.refresh_async)
        self.btn_scan.pack(side="right")

        self.var_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="자동 새로고침(30초)", variable=self.var_auto,
                        command=self._toggle_auto).pack(side="right", padx=8)

        body = ttk.Frame(self, padding=(12, 4, 12, 4))
        body.pack(fill="both", expand=True)

        # ---- 왼쪽 : 프로필 목록
        left = ttk.LabelFrame(body, text="저장된 Wi-Fi 프로필", padding=8)
        left.pack(side="left", fill="both", expand=True)

        cols = ("state", "ssid", "location", "signal", "mode", "ipinfo")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=16)
        for key, txt, w, anchor in (
                ("state", "연결가능", 90, "center"),
                ("ssid", "SSID", 165, "w"),
                ("location", "위치", 150, "w"),
                ("signal", "신호", 80, "center"),
                ("mode", "IP 방식", 80, "center"),
                ("ipinfo", "IP 설정", 190, "w")):
            self.tree.heading(key, text=txt)
            self.tree.column(key, width=w, anchor=anchor)
        self.tree.pack(fill="both", expand=True, side="left")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.connect_async())

        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        # ---- 오른쪽 : 편집 폼
        right = ttk.LabelFrame(body, text="프로필 편집", padding=10)
        right.pack(side="left", fill="y", padx=(12, 0))

        self.v_ssid = tk.StringVar()
        self.v_location = tk.StringVar()
        self.v_pw = tk.StringVar()
        self.v_mode = tk.StringVar(value="dhcp")
        self.v_ip = tk.StringVar()
        self.v_mask = tk.StringVar(value="255.255.255.0")
        self.v_gw = tk.StringVar()
        self.v_dns = tk.StringVar()
        self.v_search = tk.StringVar()

        row = 0
        ttk.Label(right, text="SSID").grid(row=row, column=0, sticky="w", pady=3)
        self.cb_ssid = ttk.Combobox(right, textvariable=self.v_ssid, width=26)
        self.cb_ssid.grid(row=row, column=1, sticky="we", pady=3)

        row += 1
        ttk.Label(right, text="위치 정보").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(right, textvariable=self.v_location, width=28)\
            .grid(row=row, column=1, sticky="we", pady=3)

        row += 1
        ttk.Label(right, text="예: 본사 3층 회의실 / 자택 / A공장 라인1",
                  foreground="#777").grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(right, text="비밀번호").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(right, textvariable=self.v_pw, show="•", width=28)\
            .grid(row=row, column=1, sticky="we", pady=3)

        row += 1
        ttk.Label(right, text="(비워두면 키체인의 기존 암호 사용)",
                  foreground="#777").grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Separator(right).grid(row=row, column=0, columnspan=2, sticky="we", pady=8)

        row += 1
        mode_box = ttk.Frame(right)
        mode_box.grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(mode_box, text="IP 설정 방식 : ").pack(side="left")
        ttk.Radiobutton(mode_box, text="DHCP", value="dhcp", variable=self.v_mode,
                        command=self._sync_mode).pack(side="left", padx=4)
        ttk.Radiobutton(mode_box, text="STATIC", value="static", variable=self.v_mode,
                        command=self._sync_mode).pack(side="left", padx=4)

        self.static_widgets = []
        for label, var in (("IP 주소", self.v_ip),
                           ("서브넷 마스크", self.v_mask),
                           ("라우터", self.v_gw)):
            row += 1
            lb = ttk.Label(right, text=label)
            lb.grid(row=row, column=0, sticky="w", pady=3)
            en = ttk.Entry(right, textvariable=var, width=28)
            en.grid(row=row, column=1, sticky="we", pady=3)
            self.static_widgets.append(en)

        row += 1
        ttk.Label(right, text="DNS 서버").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(right, textvariable=self.v_dns, width=28)\
            .grid(row=row, column=1, sticky="we", pady=3)

        row += 1
        ttk.Label(right, text="검색 도메인").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(right, textvariable=self.v_search, width=28)\
            .grid(row=row, column=1, sticky="we", pady=3)

        row += 1
        ttk.Label(right, text="여러 개는 콤마로 구분 (예: 8.8.8.8, 1.1.1.1)",
                  foreground="#777").grid(row=row, column=1, sticky="w")

        row += 1
        btns = ttk.Frame(right)
        btns.grid(row=row, column=0, columnspan=2, pady=(14, 4), sticky="we")
        ttk.Button(btns, text="새로 만들기", command=self.new_profile).pack(side="left")
        ttk.Button(btns, text="저장", command=self.save_profile).pack(side="left", padx=6)
        ttk.Button(btns, text="삭제", command=self.delete_profile).pack(side="left")

        row += 1
        self.btn_connect = ttk.Button(right, text="선택한 Wi-Fi 연결",
                                      command=self.connect_async)
        self.btn_connect.grid(row=row, column=0, columnspan=2, sticky="we", pady=6)

        row += 1
        ttk.Button(right, text="현재 연결된 SSID 가져오기",
                   command=self.pull_current).grid(row=row, column=0, columnspan=2,
                                                   sticky="we")

        # ---- 로그
        bottom = ttk.LabelFrame(self, text="로그", padding=6)
        bottom.pack(fill="both", padx=12, pady=(4, 12))
        self.log = tk.Text(bottom, height=8, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

        self._sync_mode()

    # ---------------------------------------------------------- helpers
    def logln(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _sync_mode(self):
        state = "normal" if self.v_mode.get() == "static" else "disabled"
        for w in self.static_widgets:
            w.configure(state=state)

    def _toggle_auto(self):
        if self.var_auto.get():
            self._auto_tick()

    def _auto_tick(self):
        if not self.var_auto.get():
            return
        self.refresh_async()
        self.after(30000, self._auto_tick)

    def set_busy(self, busy, note=""):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_scan.configure(state=state)
        self.btn_connect.configure(state=state)
        if note:
            self.var_status.set(note)

    # ---------------------------------------------------------- worker bridge
    def _pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.logln(payload)
                elif kind == "scan":
                    self.scan_result, self.cur_ssid, ip = payload
                    self._render_list()
                    ssids = sorted(self.scan_result.keys())
                    self.cb_ssid["values"] = ssids
                    self.var_status.set(
                        "인터페이스 %s (서비스: %s)   |   현재 연결: %s   |   IP: %s   |   주변 %d개 탐지"
                        % (self.device, self.service, self.cur_ssid or "없음",
                           ip or "없음", len(self.scan_result)))
                    self.set_busy(False)
                elif kind == "done":
                    self.set_busy(False)
                    self.refresh_async()
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._pump)

    def _spawn(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    # ---------------------------------------------------------- 스캔
    def refresh_async(self):
        if self.busy:
            return
        self.set_busy(True, "스캔 중…")

        def work():
            power_on(self.device)
            found = scan_networks()
            cur = current_ssid(self.device)
            ip = current_ip(self.device)
            if found is None:
                self.q.put(("log",
                            "[경고] 주변 Wi-Fi 스캔에 실패했습니다. "
                            "시스템 설정 > 개인정보 보호 및 보안 > 위치 서비스에서 "
                            "터미널(또는 이 앱)의 위치 권한을 허용해 주세요."))
                found = {}
            for name in preferred_networks(self.device):
                found.setdefault(name, None)   # 저장된 네트워크는 목록엔 보이되 신호 미상
            if cur:
                found.setdefault(cur, -30)
            self.q.put(("scan", (found, cur, ip)))

        self._spawn(work)

    def _bars(self, rssi):
        if rssi is None:
            return "-"
        if rssi >= -55:
            return "▂▄▆█ (%d)" % rssi
        if rssi >= -67:
            return "▂▄▆  (%d)" % rssi
        if rssi >= -75:
            return "▂▄   (%d)" % rssi
        return "▂    (%d)" % rssi

    def _render_list(self):
        sel_ssid = self.current_selection()
        self.tree.delete(*self.tree.get_children())
        self.rows = []

        for prof in sorted(self.store.profiles, key=lambda p: p["ssid"].lower()):
            ssid = prof["ssid"]
            in_range = ssid in self.scan_result
            if ssid == self.cur_ssid:
                state = "● 연결됨"
            elif in_range:
                state = "○ 연결 가능"
            else:
                state = "· 범위 밖"
            rssi = self.scan_result.get(ssid)
            if prof["mode"] == "static":
                ipinfo = "%s / %s" % (prof["ip"], prof["router"])
                mode = "STATIC"
            else:
                ipinfo = "자동 할당"
                mode = "DHCP"
            iid = self.tree.insert("", "end", values=(
                state, ssid, prof.get("location", ""),
                self._bars(rssi) if in_range else "-", mode, ipinfo))
            self.rows.append((iid, ssid))

        if sel_ssid:
            for iid, ssid in self.rows:
                if ssid == sel_ssid:
                    self.tree.selection_set(iid)
                    break

    def current_selection(self):
        sel = self.tree.selection()
        if not sel:
            return None
        for iid, ssid in self.rows:
            if iid == sel[0]:
                return ssid
        return None

    # ---------------------------------------------------------- 폼 <-> 데이터
    def _on_select(self, _event=None):
        ssid = self.current_selection()
        if not ssid:
            return
        prof = self.store.find(ssid)
        if not prof:
            return
        self.v_ssid.set(prof["ssid"])
        self.v_location.set(prof.get("location", ""))
        self.v_pw.set("")
        self.v_mode.set(prof["mode"])
        self.v_ip.set(prof["ip"])
        self.v_mask.set(prof["subnet"] or "255.255.255.0")
        self.v_gw.set(prof["router"])
        self.v_dns.set(prof["dns"])
        self.v_search.set(prof["search"])
        self._sync_mode()

    def _form_to_profile(self):
        return {
            "ssid": self.v_ssid.get().strip(),
            "location": self.v_location.get().strip(),
            "mode": self.v_mode.get(),
            "ip": self.v_ip.get().strip(),
            "subnet": self.v_mask.get().strip(),
            "router": self.v_gw.get().strip(),
            "dns": self.v_dns.get().strip(),
            "search": self.v_search.get().strip(),
            "has_password": bool(self.v_pw.get()),
        }

    def new_profile(self):
        self.tree.selection_remove(*self.tree.selection())
        self.v_ssid.set("")
        self.v_location.set("")
        self.v_pw.set("")
        self.v_mode.set("dhcp")
        self.v_ip.set("")
        self.v_mask.set("255.255.255.0")
        self.v_gw.set("")
        self.v_dns.set("")
        self.v_search.set("")
        self._sync_mode()

    def save_profile(self):
        prof = self._form_to_profile()
        errs = validate_profile(prof)
        if errs:
            messagebox.showerror("입력 오류", "\n".join(errs), parent=self)
            return
        pw = self.v_pw.get()
        if pw:
            keychain_set(prof["ssid"], pw)
        else:
            prof["has_password"] = bool(keychain_get(prof["ssid"]))
        self.store.upsert(prof)
        self.v_pw.set("")
        self.logln("[저장] %s%s (%s)" % (
            prof["ssid"],
            " @ %s" % prof["location"] if prof["location"] else "",
            prof["mode"].upper()))
        self._render_list()

    def delete_profile(self):
        ssid = self.current_selection() or self.v_ssid.get().strip()
        if not ssid or not self.store.find(ssid):
            messagebox.showinfo(APP_NAME, "삭제할 프로필을 목록에서 선택하세요.", parent=self)
            return
        if not messagebox.askyesno(APP_NAME, "'%s' 프로필을 삭제할까요?" % ssid, parent=self):
            return
        self.store.delete(ssid)
        keychain_del(ssid)
        self.logln("[삭제] %s" % ssid)
        self.new_profile()
        self._render_list()

    def pull_current(self):
        """현재 시스템에 적용된 Wi-Fi/IP 설정을 폼에 채워 넣는다."""
        ssid = current_ssid(self.device)
        if not ssid:
            messagebox.showinfo(APP_NAME, "현재 연결된 Wi-Fi가 없습니다.", parent=self)
            return
        self.v_ssid.set(ssid)
        rc, out, _ = run([NETSETUP, "-getinfo", self.service], timeout=15)
        if rc == 0:
            if re.search(r"DHCP Configuration", out):
                self.v_mode.set("dhcp")
            else:
                self.v_mode.set("static")
            m = re.search(r"^IP address:\s*(\S+)", out, re.M)
            if m:
                self.v_ip.set(m.group(1))
            m = re.search(r"^Subnet mask:\s*(\S+)", out, re.M)
            if m:
                self.v_mask.set(m.group(1))
            m = re.search(r"^Router:\s*(\S+)", out, re.M)
            if m:
                self.v_gw.set(m.group(1))
        rc, out, _ = run([NETSETUP, "-getdnsservers", self.service], timeout=15)
        if rc == 0 and "aren't any" not in out:
            self.v_dns.set(", ".join(out.split()))
        self._sync_mode()
        self.logln("[가져오기] 현재 설정을 폼에 반영했습니다: %s" % ssid)

    # ---------------------------------------------------------- 연결
    def connect_async(self):
        if self.busy:
            return
        ssid = self.current_selection() or self.v_ssid.get().strip()
        prof = self.store.find(ssid)
        if not prof:
            messagebox.showinfo(APP_NAME,
                                "먼저 프로필을 저장한 뒤 목록에서 선택하세요.", parent=self)
            return
        if ssid not in self.scan_result:
            if not messagebox.askyesno(
                    APP_NAME,
                    "'%s' 는 현재 스캔 목록에 없습니다(범위 밖일 수 있음).\n"
                    "그래도 연결을 시도할까요?" % ssid, parent=self):
                return

        pw = self.v_pw.get() or keychain_get(ssid)
        self.set_busy(True, "'%s' 연결 중…" % ssid)

        def work():
            self.q.put(("log", "─" * 60))
            self.q.put(("log", "[1/3] SSID 접속 시도: %s" % ssid))
            ok, msg = join_ssid(self.device, ssid, pw)
            self.q.put(("log", "      %s" % msg))
            if not ok:
                self.q.put(("log", "[중단] SSID 접속 실패. 비밀번호/신호 상태를 확인하세요."))
                self.q.put(("done", None))
                return

            self.q.put(("log", "[2/3] IP 설정 적용 (%s) — 관리자 암호 입력창이 표시됩니다."
                        % prof["mode"].upper()))
            cmds = build_ipconfig_cmds(self.service, prof)
            rc, out, err = run_admin(" && ".join(cmds))
            if rc != 0:
                self.q.put(("log", "      [실패] %s" % (err or out or "권한 거부")))
                self.q.put(("done", None))
                return
            self.q.put(("log", "      적용 완료: %s" % "; ".join(
                c.replace(NETSETUP + " ", "networksetup ") for c in cmds)))

            self.q.put(("log", "[3/3] 결과 확인"))
            import time
            for _ in range(10):
                ip = current_ip(self.device)
                if ip:
                    break
                time.sleep(1)
            ip = current_ip(self.device)
            cur = current_ssid(self.device)
            self.q.put(("log", "      SSID=%s / IP=%s" % (cur or "없음", ip or "미할당")))
            if prof["mode"] == "static" and ip and ip != prof["ip"].strip():
                self.q.put(("log",
                            "      [주의] 지정한 %s 와 실제 IP가 다릅니다. "
                            "설정 반영에 몇 초 더 걸릴 수 있습니다." % prof["ip"]))
            self.q.put(("done", None))

        self._spawn(work)


# ---------------------------------------------------------------- CLI 모드
USAGE = """{name} {ver}

사용법:
  wifi_profile_manager                 GUI 실행 (기본)
  wifi_profile_manager --list          저장된 프로필과 연결 가능 여부 출력
  wifi_profile_manager --scan          주변 Wi-Fi 스캔 결과 출력
  wifi_profile_manager --connect SSID  해당 프로필로 접속 + IP 설정 적용
  wifi_profile_manager --info          현재 Wi-Fi/IP 상태 출력
  wifi_profile_manager --web           브라우저 UI로 실행 (Tk 문제 우회)
  wifi_profile_manager --tk            Tk GUI 강제 실행
  wifi_profile_manager --doctor        실행 환경 진단 (화면이 안 보일 때)
  wifi_profile_manager --help          이 도움말
""".format(name=APP_NAME, ver=APP_VERSION)


def cli_scan(device):
    power_on(device)
    found = scan_networks()
    if not found:
        print("스캔 결과가 없습니다. 위치 서비스 권한을 확인하세요.")
        return 1
    for ssid, rssi in sorted(found.items(), key=lambda kv: -(kv[1] or -100)):
        print("  %-32s %s dBm" % (ssid, rssi if rssi is not None else "?"))
    return 0


def cli_list(device, store):
    power_on(device)
    found = scan_networks() or {}
    cur = current_ssid(device)
    if not store.profiles:
        print("저장된 프로필이 없습니다. GUI에서 먼저 프로필을 만드세요.")
        return 1
    print("%-3s %-24s %-20s %-8s %s" % ("", "SSID", "위치", "방식", "IP 설정"))
    for p in sorted(store.profiles, key=lambda x: x["ssid"].lower()):
        mark = "*" if p["ssid"] == cur else ("+" if p["ssid"] in found else "-")
        ipinfo = ("%s / %s" % (p["ip"], p["router"])) if p["mode"] == "static" else "자동 할당"
        print("%-3s %-24s %-20s %-8s %s" % (mark, p["ssid"], p.get("location", "-") or "-",
                                            p["mode"].upper(), ipinfo))
    print("\n( * 현재 연결 / + 연결 가능 / - 범위 밖 )")
    return 0


def cli_info(device, service):
    print("인터페이스 : %s (서비스: %s)" % (device, service))
    print("현재 SSID  : %s" % (current_ssid(device) or "없음"))
    print("현재 IP    : %s" % (current_ip(device) or "없음"))
    rc, out, _ = run([NETSETUP, "-getinfo", service], timeout=15)
    if rc == 0:
        print("-" * 40)
        print(out)
    return 0


def cli_connect(device, service, store, ssid):
    prof = store.find(ssid)
    if not prof:
        print("'%s' 프로필이 없습니다. --list 로 확인하세요." % ssid)
        return 1
    print("[1/3] SSID 접속: %s" % ssid)
    ok, msg = join_ssid(device, ssid, keychain_get(ssid))
    print("      %s" % msg)
    if not ok:
        return 1
    print("[2/3] IP 설정 적용 (%s) — 관리자 인증이 필요합니다." % prof["mode"].upper())
    rc, out, err = run_admin(" && ".join(build_ipconfig_cmds(service, prof)))
    if rc != 0:
        print("      실패: %s" % (err or out))
        return 1
    print("      적용 완료")
    print("[3/3] 결과 확인")
    import time
    for _ in range(10):
        if current_ip(device):
            break
        time.sleep(1)
    print("      SSID=%s / IP=%s" % (current_ssid(device) or "없음",
                                     current_ip(device) or "미할당"))
    return 0


LOG_PATH = os.path.join(APP_DIR, "app.log")


def write_log(text):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fp:
            fp.write(text.rstrip() + "\n")
    except IOError:
        pass


def cli_doctor():
    """실행 환경 진단 — '아무것도 안 보임' 증상의 원인 파악용"""
    print("=" * 62)
    print("%s %s — 실행 환경 진단" % (APP_NAME, APP_VERSION))
    print("=" * 62)
    print("파이썬 실행 파일 : %s" % sys.executable)
    print("파이썬 버전      : %s" % sys.version.split()[0])
    print("플랫폼           : %s" % sys.platform)

    ok = True
    try:
        import tkinter as _tk
        root = _tk.Tk()
        tkver = root.tk.call("info", "patchlevel")
        root.destroy()
        print("Tkinter          : 사용 가능 (TkVersion %s / patchlevel %s)"
              % (_tk.TkVersion, tkver))
        if float(_tk.TkVersion) < 8.6:
            ok = False
            print()
            print("  [문제] Tk 8.5 입니다. 최신 macOS에서 창이 '빈 화면'으로")
            print("         표시되는 것으로 알려진 조합입니다. 아래 중 하나로 해결하세요.")
            print("           brew install python-tk")
            print("           또는 python.org 설치본(Tk 8.6 포함) 사용")
    except Exception as exc:                                   # noqa: BLE001
        ok = False
        print("Tkinter          : 사용 불가 (%s)" % exc)
        print("  → xcode-select --install  또는  brew install python-tk")

    print("-" * 62)
    dev = detect_wifi_device()
    print("Wi-Fi 인터페이스 : %s" % dev)
    print("네트워크 서비스  : %s" % detect_wifi_service(dev))
    print("현재 SSID / IP   : %s / %s" % (current_ssid(dev) or "없음",
                                          current_ip(dev) or "없음"))
    print("airport CLI      : %s" % ("있음" if os.path.exists(AIRPORT)
                                     else "없음 (macOS 14.4+ → system_profiler 사용)"))
    found = scan_networks()
    print("스캔 결과        : %s"
          % ("%d개" % len(found) if found else "0개 (위치 서비스 권한 확인 필요)"))
    print("설정 파일        : %s" % CONF_PATH)
    print("로그 파일        : %s" % LOG_PATH)
    print("=" * 62)
    print("판정: %s" % ("정상 — GUI 실행 가능" if ok
                        else "위 [문제] 항목을 먼저 해결하세요"))
    return 0 if ok else 1


def start_webui(port=0):
    """Tk를 쓰지 않는 브라우저 UI 실행"""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import webui
    except ImportError as exc:
        print("웹 UI 모듈(webui.py)을 찾을 수 없습니다: %s" % exc)
        return 1
    return webui.start_web(sys.modules[__name__], port=port)


def gui_error(message):
    """GUI 실행 불가 시 macOS 알림창으로 안내"""
    print(message)
    script = 'display dialog %s buttons {"확인"} default button 1 with icon caution ' \
             'with title %s' % (as_quote(message), as_quote(APP_NAME))
    run(["osascript", "-e", script], timeout=60)


def main():
    try:                       # `--list | head` 등 파이프 사용 시 오류 방지
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]  # Finder 인자 제거

    if args and args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if args and args[0] in ("-v", "--version"):
        print("%s %s" % (APP_NAME, APP_VERSION))
        return 0
    if args and args[0] in ("--doctor", "--diag"):
        return cli_doctor()

    if sys.platform != "darwin":
        print("이 프로그램은 macOS 전용입니다.")
        return 1
    os.makedirs(APP_DIR, exist_ok=True)

    if args:
        cmd = args[0]
        device = detect_wifi_device()
        service = detect_wifi_service(device)
        store = Store()

        if cmd == "--scan":
            return cli_scan(device)
        if cmd == "--list":
            return cli_list(device, store)
        if cmd == "--info":
            return cli_info(device, service)
        if cmd in ("--doctor", "--diag"):
            return cli_doctor()
        if cmd == "--web":
            return start_webui()
        if cmd == "--connect":
            if len(args) < 2:
                print("SSID를 지정하세요. 예) --connect \"MyOffice\"")
                return 2
            return cli_connect(device, service, store, args[1])
        print(USAGE)
        return 2

    if not TK_OK:
        write_log("Tkinter 없음 → 브라우저 UI로 전환")
        print("Tkinter가 없어 브라우저 UI로 실행합니다.")
        return start_webui()

    if False:
        gui_error("Tkinter를 찾을 수 없어 GUI를 실행할 수 없습니다.\\n\\n"
                  "터미널에서 다음 중 하나를 설치하세요:\\n"
                  "  xcode-select --install\\n"
                  "  brew install python-tk\\n\\n"
                  "설치 없이도 CLI는 사용할 수 있습니다: --list, --connect \\\"SSID\\\"")
        return 1

    force_tk = bool(args) and args[0] == "--tk"

    # Tk 8.5는 최신 macOS에서 '창은 뜨는데 내용이 안 그려지는' 문제가 있다.
    # 이 경우 Tk를 포기하고 브라우저 UI로 자동 전환한다.
    if not force_tk and float(tk.TkVersion) < 8.6:
        write_log("Tk %s 감지 → 브라우저 UI로 전환" % tk.TkVersion)
        print("Tk %s 는 이 macOS에서 창 내용이 그려지지 않는 문제가 있어\n"
              "브라우저 UI로 실행합니다. (Tk를 강제하려면 --tk)" % tk.TkVersion)
        return start_webui()

    write_log("--- GUI 시작 : python=%s Tk=%s" % (sys.executable, tk.TkVersion))
    try:
        App().mainloop()
    except Exception:                                          # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        write_log(tb)
        print(tb, file=sys.stderr)
        gui_error("실행 중 오류가 발생했습니다.\\n\\n%s\\n\\n자세한 내용: %s"
                  % (tb.strip().splitlines()[-1].replace('"', "'")[:200], LOG_PATH))
        return 1
    write_log("--- GUI 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
