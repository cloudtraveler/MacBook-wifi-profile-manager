# -*- coding: utf-8 -*-
"""
webui.py — Tk를 전혀 쓰지 않는 브라우저 기반 UI

macOS 내장 Tk 8.5 의 '빈 창' 렌더링 버그를 완전히 우회한다.
표준 라이브러리(http.server)만 사용하며 127.0.0.1 에만 바인딩한다.
"""

import http.server
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.parse

PAGE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wi-Fi Profile Manager</title>
<style>
:root{--bg:#f5f5f7;--card:#fff;--line:#d8d8dd;--tx:#1d1d1f;--dim:#6e6e73;
      --acc:#2860d6;--ok:#1a8a3f;--warn:#b26a00;--err:#c22b2b;}
@media (prefers-color-scheme:dark){
:root{--bg:#1c1c1e;--card:#2c2c2e;--line:#3a3a3c;--tx:#f2f2f7;--dim:#98989d;
      --acc:#5b8dff;--ok:#32d15b;--warn:#ffb340;--err:#ff6961;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
 font:14px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;}
header{padding:14px 20px;border-bottom:1px solid var(--line);background:var(--card);
 display:flex;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:5}
header>*{margin-right:16px}
header>*:last-child{margin-right:0}
header b{font-size:15px}
.muted{color:var(--dim)}
.wrap{display:flex;padding:16px;align-items:flex-start;flex-wrap:wrap}
#listCard{margin:0 16px 16px 0}
#formCard{margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card h2{margin:0 0 10px;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim)}
#listCard{flex:1 1 660px;min-width:520px}
#formCard{flex:0 0 360px}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-weight:600}
tr.row{cursor:pointer}
tr.row:hover{background:rgba(128,128,128,.10)}
tr.sel{background:rgba(40,96,214,.16)}
.dot{font-weight:700}
.on{color:var(--ok)} .near{color:var(--acc)} .off{color:var(--dim)}
label{display:block;margin:9px 0 3px;font-size:12px;color:var(--dim)}
input[type=text],input[type=password]{width:100%;padding:7px 9px;border:1px solid var(--line);
 border-radius:6px;background:var(--bg);color:var(--tx);font-size:13px}
input:disabled{opacity:.45}
.modes{display:flex;margin:10px 0 4px}
.modes label{margin:0 20px 0 0;color:var(--tx);font-size:13px;display:flex;align-items:center;cursor:pointer}
.modes input{margin-right:6px}
button{padding:8px 12px;border:1px solid var(--line);border-radius:7px;background:var(--card);
 color:var(--tx);font-size:13px;cursor:pointer}
button:hover{border-color:var(--acc)}
button.p{background:var(--acc);border-color:var(--acc);color:#fff;width:100%;padding:10px;font-weight:600;margin-top:12px}
button:disabled{opacity:.5;cursor:default}
.btns{display:flex;margin-top:12px}
.btns button{flex:1;margin-right:8px}
.btns button:last-child{margin-right:0}
#log{margin:0 16px 16px;min-height:60px;background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:12px;font:12px/1.65 ui-monospace,Menlo,monospace;white-space:pre-wrap;
 max-height:230px;overflow:auto}
#log .e{color:var(--err)} #log .w{color:var(--warn)} #log .o{color:var(--ok)}
.hint{font-size:11px;color:var(--dim);margin-top:4px}
</style></head><body>

<header>
  <b>Wi-Fi Profile Manager</b>
  <span id="stat" class="muted">불러오는 중…</span>
  <span style="flex:1"></span>
  <button id="btnScan">스캔 새로고침</button>
</header>

<div class="wrap">
  <div class="card" id="listCard">
    <h2>저장된 프로필</h2>
    <table>
      <thead><tr><th style="width:96px">연결가능</th><th>SSID</th><th style="width:150px">위치</th>
      <th style="width:78px">신호</th><th style="width:74px">방식</th><th>IP 설정</th></tr></thead>
      <tbody id="rows"><tr><td colspan="6" class="muted">불러오는 중…</td></tr></tbody>
    </table>
  </div>

  <div class="card" id="formCard">
    <h2>프로필 편집</h2>
    <label>SSID</label>
    <input type="text" id="ssid" list="scanned" autocomplete="off">
    <datalist id="scanned"></datalist>

    <label>위치 정보</label>
    <input type="text" id="location" placeholder="예: 본사 3층 회의실" autocomplete="off">

    <label>비밀번호</label>
    <input type="password" id="pw" autocomplete="new-password">
    <div class="hint">비워두면 키체인에 저장된 암호를 사용합니다</div>

    <div class="modes">
      <label><input type="radio" name="m" value="dhcp" checked> DHCP</label>
      <label><input type="radio" name="m" value="static"> STATIC</label>
    </div>

    <label>IP 주소</label><input type="text" id="ip" disabled>
    <label>서브넷 마스크</label><input type="text" id="mask" value="255.255.255.0" disabled>
    <label>라우터</label><input type="text" id="gw" disabled>
    <label>DNS 서버</label><input type="text" id="dns" placeholder="8.8.8.8, 1.1.1.1">
    <label>검색 도메인</label><input type="text" id="search">

    <div class="btns">
      <button id="btnNew">새로 만들기</button>
      <button id="btnSave">저장</button>
      <button id="btnDel">삭제</button>
    </div>
    <button class="p" id="btnConn">선택한 Wi-Fi 연결</button>
    <button id="btnPull" style="width:100%;margin-top:8px">현재 연결된 SSID 가져오기</button>
  </div>
</div>

<div id="log"></div>

<script>
var T = "__TOKEN__";
var state = {profiles: [], scan: {}, current: null};
var sel = null;

function $(id){ return document.getElementById(id); }

function log(msg, cls){
  var d = document.createElement('div');
  if(cls){ d.className = cls; }
  d.appendChild(document.createTextNode(
    new Date().toLocaleTimeString('ko-KR') + '  ' + msg));
  var box = $('log');
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}

/* XHR 기반 — 구형 Safari 포함 모든 브라우저에서 동작 */
function api(path, body, cb, errcb){
  var x = new XMLHttpRequest();
  x.open(body ? 'POST' : 'GET', path + '?t=' + encodeURIComponent(T), true);
  x.setRequestHeader('X-Token', T);
  if(body){ x.setRequestHeader('Content-Type', 'application/json'); }
  x.onreadystatechange = function(){
    if(x.readyState !== 4){ return; }
    if(x.status >= 200 && x.status < 300){
      var r = null;
      try { r = JSON.parse(x.responseText); }
      catch(e){ if(errcb) errcb('응답 해석 실패'); return; }
      if(cb) cb(r);
    } else {
      if(errcb) errcb('HTTP ' + x.status);
    }
  };
  x.send(body ? JSON.stringify(body) : null);
}

function mode(){
  var rs = document.getElementsByName('m');
  for(var i = 0; i < rs.length; i++){ if(rs[i].checked){ return rs[i].value; } }
  return 'dhcp';
}
function setMode(m){
  var rs = document.getElementsByName('m');
  for(var i = 0; i < rs.length; i++){ rs[i].checked = (rs[i].value === m); }
  syncMode();
}
function syncMode(){
  var dis = mode() !== 'static';
  var ids = ['ip', 'mask', 'gw'];
  for(var i = 0; i < ids.length; i++){ $(ids[i]).disabled = dis; }
}

function bars(v){
  if(v === null || v === undefined){ return '-'; }
  var n = v >= -55 ? 4 : (v >= -67 ? 3 : (v >= -75 ? 2 : 1));
  return '▂▄▆█'.substring(0, n) + ' (' + v + ')';
}
function esc(s){
  var d = document.createElement('div');
  d.appendChild(document.createTextNode(s == null ? '' : s));
  return d.innerHTML;
}

function render(){
  var tb = $('rows');
  tb.innerHTML = '';
  var list = state.profiles.slice();
  if(!list.length){
    tb.innerHTML = '<tr><td colspan="6" class="muted">저장된 프로필이 없습니다. 오른쪽에서 추가하세요.</td></tr>';
  }
  list.sort(function(a, b){
    return a.ssid.toLowerCase() < b.ssid.toLowerCase() ? -1 : 1;
  });
  for(var i = 0; i < list.length; i++){
    (function(p){
      var inRange = state.scan.hasOwnProperty(p.ssid);
      var cur = (p.ssid === state.current);
      var st = cur ? '<span class="dot on">● 연결됨</span>'
             : (inRange ? '<span class="dot near">○ 연결 가능</span>'
                        : '<span class="dot off">· 범위 밖</span>');
      var tr = document.createElement('tr');
      tr.className = 'row' + (sel === p.ssid ? ' sel' : '');
      tr.innerHTML = '<td>' + st + '</td><td>' + esc(p.ssid) + '</td><td>' +
        (p.location ? esc(p.location) : '<span class="muted">-</span>') + '</td><td>' +
        (inRange ? bars(state.scan[p.ssid]) : '-') + '</td><td>' +
        p.mode.toUpperCase() + '</td><td>' +
        (p.mode === 'static' ? esc(p.ip) + ' / ' + esc(p.router) : '자동 할당') + '</td>';
      tr.onclick = function(){ sel = p.ssid; fill(p); render(); };
      tr.ondblclick = connect;
      tb.appendChild(tr);
    })(list[i]);
  }
  var dl = $('scanned');
  dl.innerHTML = '';
  var keys = [];
  for(var k in state.scan){ if(state.scan.hasOwnProperty(k)){ keys.push(k); } }
  keys.sort();
  for(var j = 0; j < keys.length; j++){
    var o = document.createElement('option');
    o.value = keys[j];
    dl.appendChild(o);
  }
}

function fill(p){
  $('ssid').value = p.ssid || '';
  $('location').value = p.location || '';
  $('pw').value = '';
  setMode(p.mode || 'dhcp');
  $('ip').value = p.ip || '';
  $('mask').value = p.subnet || '255.255.255.0';
  $('gw').value = p.router || '';
  $('dns').value = p.dns || '';
  $('search').value = p.search || '';
}
function form(){
  return {ssid: $('ssid').value, location: $('location').value,
          mode: mode(), ip: $('ip').value,
          subnet: $('mask').value, router: $('gw').value,
          dns: $('dns').value, search: $('search').value,
          password: $('pw').value};
}

function refresh(){
  $('btnScan').disabled = true;
  $('stat').innerHTML = '스캔 중…';
  api('/api/state', null, function(d){
    state = d;
    render();
    $('stat').innerHTML = esc('인터페이스 ' + d.device + ' (서비스: ' + d.service +
      ')  |  현재 연결: ' + (d.current || '없음') + '  |  IP: ' + (d.ip || '없음') +
      '  |  주변 ' + countKeys(d.scan) + '개 탐지');
    if(d.scan_warning){ log(d.scan_warning, 'w'); }
    $('btnScan').disabled = false;
  }, function(e){
    log('상태 조회 실패: ' + e, 'e');
    $('stat').innerHTML = '오류';
    $('btnScan').disabled = false;
  });
}
function countKeys(o){
  var n = 0;
  for(var k in o){ if(o.hasOwnProperty(k)){ n++; } }
  return n;
}

function save(){
  api('/api/save', form(), function(r){
    if(r.errors && r.errors.length){
      for(var i = 0; i < r.errors.length; i++){ log('입력 오류: ' + r.errors[i], 'e'); }
      return;
    }
    sel = r.ssid;
    $('pw').value = '';
    log('저장됨: ' + r.ssid, 'o');
    refresh();
  }, function(e){ log('저장 실패: ' + e, 'e'); });
}
function del(){
  var s = sel || $('ssid').value;
  if(!s){ log('삭제할 프로필을 선택하세요.', 'w'); return; }
  if(!confirm("'" + s + "' 프로필을 삭제할까요?")){ return; }
  api('/api/delete', {ssid: s}, function(){
    log('삭제됨: ' + s);
    sel = null;
    newProfile();
    refresh();
  }, function(e){ log('삭제 실패: ' + e, 'e'); });
}
function newProfile(){
  sel = null;
  var ids = ['ssid', 'location', 'pw', 'ip', 'gw', 'dns', 'search'];
  for(var i = 0; i < ids.length; i++){ $(ids[i]).value = ''; }
  $('mask').value = '255.255.255.0';
  setMode('dhcp');
  render();
}
function pull(){
  api('/api/current', null, function(r){
    if(!r.ssid){ log('현재 연결된 Wi-Fi가 없습니다.', 'w'); return; }
    fill(r);
    log('현재 설정을 폼에 반영했습니다: ' + r.ssid);
  }, function(e){ log('조회 실패: ' + e, 'e'); });
}
function connect(){
  var s = sel || $('ssid').value;
  if(!s){ log('연결할 프로필을 선택하세요.', 'w'); return; }
  $('btnConn').disabled = true;
  log('──────────────────────────────────────────────');
  log("'" + s + "' 연결 시작 — 관리자 암호 입력창이 화면에 뜹니다.");
  api('/api/connect', {ssid: s, password: $('pw').value}, function(r){
    var lines = r.lines || [];
    for(var i = 0; i < lines.length; i++){ log(lines[i], r.ok ? '' : 'e'); }
    log(r.ok ? '연결 완료' : '연결 실패', r.ok ? 'o' : 'e');
    $('btnConn').disabled = false;
    refresh();
  }, function(e){
    log('연결 오류: ' + e, 'e');
    $('btnConn').disabled = false;
  });
}

(function(){
  var rs = document.getElementsByName('m');
  for(var i = 0; i < rs.length; i++){
    rs[i].onchange = syncMode;
  }
  $('btnScan').onclick = refresh;
  $('btnSave').onclick = save;
  $('btnDel').onclick  = del;
  $('btnNew').onclick  = newProfile;
  $('btnPull').onclick = pull;
  $('btnConn').onclick = connect;
  syncMode();
  log('브라우저 UI 모드로 실행 중입니다. (Tk 렌더링 문제 우회)');
  refresh();
})();
</script></body></html>
"""


def start_web(mod, port=0, open_browser=True):
    """
    mod : wifi_profile_manager 모듈 (셸 함수/스토어 재사용)
    port: 0이면 빈 포트 자동 선택
    """
    token = secrets.token_urlsafe(18)
    device = mod.detect_wifi_device()
    service = mod.detect_wifi_service(device)
    store = mod.Store()
    lock = threading.Lock()

    def gather_state():
        mod.power_on(device)
        found = mod.scan_networks()
        warn = None
        if found is None:
            warn = ("[경고] 주변 Wi-Fi 스캔 실패 — 시스템 설정 > 개인정보 보호 및 보안 > "
                    "위치 서비스에서 권한을 허용하세요.")
            found = {}
        for name in mod.preferred_networks(device):
            found.setdefault(name, None)
        cur = mod.current_ssid(device)
        if cur:
            found.setdefault(cur, -30)
        return {"device": device, "service": service, "current": cur,
                "ip": mod.current_ip(device), "scan": found,
                "profiles": store.profiles, "scan_warning": warn}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "WiFiProfileManager"

        def log_message(self, fmt, *a):          # 콘솔 스팸 방지
            pass

        # ---- 보안: 로컬 전용 + 토큰 검사 -------------------------------
        def _authorized(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False
            qs = urllib.parse.urlparse(self.path).query
            tok = urllib.parse.parse_qs(qs).get("t", [""])[0]
            return secrets.compare_digest(tok, token) or \
                secrets.compare_digest(self.headers.get("X-Token", ""), token)

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False))

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except ValueError:
                return {}

        # ---- 라우팅 ----------------------------------------------------
        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if not self._authorized():
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            if path == "/":
                return self._send(200, PAGE.replace("__TOKEN__", token),
                                  "text/html; charset=utf-8")
            if path == "/api/state":
                with lock:
                    return self._json(gather_state())
            if path == "/api/current":
                with lock:
                    return self._json(self._current_profile())
            return self._send(404, "not found", "text/plain; charset=utf-8")

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if not self._authorized():
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            body = self._body()
            with lock:
                if path == "/api/save":
                    return self._json(self._save(body))
                if path == "/api/delete":
                    ssid = (body.get("ssid") or "").strip()
                    store.delete(ssid)
                    mod.keychain_del(ssid)
                    return self._json({"ok": True})
                if path == "/api/connect":
                    return self._json(self._connect(body))
            return self._send(404, "not found", "text/plain; charset=utf-8")

        # ---- 동작 ------------------------------------------------------
        def _save(self, body):
            prof = dict(mod.DEFAULT_PROFILE)
            for k in ("ssid", "location", "mode", "ip", "subnet",
                      "router", "dns", "search"):
                prof[k] = (body.get(k) or "").strip()
            if prof["mode"] not in ("dhcp", "static"):
                prof["mode"] = "dhcp"
            errs = mod.validate_profile(prof)
            if errs:
                return {"ok": False, "errors": errs}
            pw = body.get("password") or ""
            if pw:
                mod.keychain_set(prof["ssid"], pw)
            prof["has_password"] = bool(pw) or bool(mod.keychain_get(prof["ssid"]))
            store.upsert(prof)
            return {"ok": True, "ssid": prof["ssid"], "errors": []}

        def _current_profile(self):
            ssid = mod.current_ssid(device)
            out = dict(mod.DEFAULT_PROFILE, ssid=ssid or "")
            if not ssid:
                return out
            known = store.find(ssid)
            if known:
                out["location"] = known.get("location", "")
            rc, txt, _ = mod.run([mod.NETSETUP, "-getinfo", service], timeout=15)
            if rc == 0:
                import re
                out["mode"] = "dhcp" if "DHCP Configuration" in txt else "static"
                for key, pat in (("ip", r"^IP address:\s*(\S+)"),
                                 ("subnet", r"^Subnet mask:\s*(\S+)"),
                                 ("router", r"^Router:\s*(\S+)")):
                    m = re.search(pat, txt, re.M)
                    if m:
                        out[key] = m.group(1)
            rc, txt, _ = mod.run([mod.NETSETUP, "-getdnsservers", service], timeout=15)
            if rc == 0 and "aren't any" not in txt:
                out["dns"] = ", ".join(txt.split())
            return out

        def _connect(self, body):
            ssid = (body.get("ssid") or "").strip()
            prof = store.find(ssid)
            lines = []
            if not prof:
                return {"ok": False, "lines": ["'%s' 프로필을 찾을 수 없습니다." % ssid]}
            pw = body.get("password") or mod.keychain_get(ssid)

            lines.append("[1/3] SSID 접속 시도: %s" % ssid)
            ok, msg = mod.join_ssid(device, ssid, pw)
            lines.append("      " + msg)
            if not ok:
                lines.append("[중단] SSID 접속 실패 — 비밀번호/신호 상태를 확인하세요.")
                return {"ok": False, "lines": lines}

            lines.append("[2/3] IP 설정 적용 (%s)" % prof["mode"].upper())
            cmds = mod.build_ipconfig_cmds(service, prof)
            rc, out, err = mod.run_admin(" && ".join(cmds))
            if rc != 0:
                lines.append("      [실패] %s" % (err or out or "권한 거부"))
                return {"ok": False, "lines": lines}
            lines.append("      적용 완료")

            lines.append("[3/3] 결과 확인")
            for _ in range(10):
                if mod.current_ip(device):
                    break
                time.sleep(1)
            ip = mod.current_ip(device)
            lines.append("      SSID=%s / IP=%s" % (mod.current_ssid(device) or "없음",
                                                    ip or "미할당"))
            if prof["mode"] == "static" and ip and ip != prof["ip"].strip():
                lines.append("      [주의] 지정한 %s 와 실제 IP가 다릅니다." % prof["ip"])
            return {"ok": True, "lines": lines}

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = Server(("127.0.0.1", port), Handler)
    real_port = httpd.socket.getsockname()[1]
    url = "http://127.0.0.1:%d/?t=%s" % (real_port, token)

    print("=" * 60)
    print("브라우저 UI 모드로 실행 중입니다 (Tk 미사용).")
    print("주소: %s" % url)
    print("종료하려면 이 터미널에서 Control-C 를 누르세요.")
    print("=" * 60)

    if open_browser:
        threading.Timer(0.4, lambda: subprocess.call(["open", url])).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        httpd.server_close()
    return 0
