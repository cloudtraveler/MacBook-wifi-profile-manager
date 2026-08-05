# Windows에서 GitHub에 푸시하기

이 저장소는 macOS용 앱이지만, **코드를 올리는 작업은 Windows에서 해도 아무 문제가 없습니다.**
빌드는 GitHub Actions의 macOS 러너가 대신 수행합니다.

---

## 1. Git 설치

PowerShell을 열고:

```powershell
winget install --id Git.Git -e
```

winget이 없으면 <https://git-scm.com/download/win> 에서 설치 프로그램을 받습니다.
설치 시 기본 옵션 그대로 두면 됩니다. **Git Credential Manager**가 함께 설치되어
로그인이 브라우저 창으로 간편하게 처리됩니다.

설치 후 PowerShell을 **새로 열어** 확인합니다.

```powershell
git --version
```

## 2. 압축 풀기

```powershell
cd $HOME\Documents
Expand-Archive -Path "$HOME\Downloads\wifi-profile-manager-repo.zip" -DestinationPath .
cd repo
```

> 탐색기에서 우클릭 → "압축 풀기"로 해도 됩니다.
> 폴더 이름은 `wifi-profile-manager` 등으로 바꿔도 무방합니다.

커밋이 이미 들어 있는지 확인합니다.

```powershell
git log --oneline
git status
```

`nothing to commit, working tree clean` 이 나오면 정상입니다.

## 3. 커밋 작성자 이름 바꾸기 (선택)

기본값이 임시 정보로 되어 있습니다. 공개 저장소로 올릴 예정이면 본인 정보로 바꾸세요.

```powershell
git config user.name "본인이름"
git config user.email "본인메일@example.com"
git commit --amend --reset-author --no-edit
git tag -f -a v1.2.0 -m "v1.2.0"
```

> GitHub 이메일을 공개하고 싶지 않다면 GitHub 설정에서 제공하는
> `12345678+계정명@users.noreply.github.com` 형식을 쓰면 됩니다.

## 4. GitHub에 빈 저장소 만들기

<https://github.com/new> 에서 저장소를 만듭니다.

- Repository name: `wifi-profile-manager`
- **Add a README file / .gitignore / license 는 모두 체크 해제** (이미 저장소에 있어서 충돌합니다)

## 5. 원격 연결 후 푸시

```powershell
git remote add origin https://github.com/사용자명/wifi-profile-manager.git
git push -u origin main
```

첫 푸시 때 브라우저 로그인 창이 열립니다. GitHub 계정으로 승인하면
자격 증명이 Windows 자격 증명 관리자에 저장되어 다음부터는 묻지 않습니다.

이어서 태그를 푸시하면 릴리스가 자동 생성됩니다.

```powershell
git push origin v1.2.0
```

## 6. GitHub CLI로 한 번에 (대안)

저장소 생성까지 명령 한 줄로 처리할 수 있습니다.

```powershell
winget install --id GitHub.cli -e
gh auth login
gh repo create wifi-profile-manager --public --source=. --push
git push origin v1.2.0
```

---

## 브라우저 로그인이 안 될 때 — 토큰(PAT) 방식

회사 PC 등에서 브라우저 인증이 막히면 개인 액세스 토큰을 씁니다.

1. <https://github.com/settings/tokens> → **Generate new token (classic)**
2. 권한은 **`repo`** 만 체크, 만료일 지정
3. 생성된 토큰을 복사 (한 번만 보입니다)
4. 푸시할 때 사용자명은 GitHub 아이디, **비밀번호 자리에 토큰을 붙여넣기**

토큰을 URL에 직접 넣는 방식은 명령 기록에 남으므로 권장하지 않습니다.

---

## Windows에서 주의할 점

### 줄바꿈 (가장 중요)

Windows Git은 기본적으로 체크아웃 시 LF를 CRLF로 바꿉니다.
셸 스크립트가 CRLF가 되면 macOS에서 `bad interpreter` 오류로 **실행이 불가능**해집니다.

이 저장소에는 `.gitattributes` 가 포함되어 있어 `.sh` · `.py` · `.yml` 이
**항상 LF로 유지**됩니다. 별도 설정이 필요 없습니다.

혹시 확인하고 싶다면:

```powershell
git check-attr text eol -- scripts/install.sh
# scripts/install.sh: text: set
# scripts/install.sh: eol: lf
```

### 실행 권한

Windows에는 유닉스 실행 권한이 없지만, 이미 `100755` 로 커밋되어 있어
푸시해도 그대로 보존됩니다. 새 셸 스크립트를 **추가**할 때만 다음이 필요합니다.

```powershell
git add scripts\새스크립트.sh
git update-index --chmod=+x scripts/새스크립트.sh
git commit -m "add script"
```

### 한글 파일명·로그 깨짐

```powershell
git config --global core.quotepath false
```

### 줄바꿈 경고 메시지

`LF will be replaced by CRLF` 경고가 뜨면 무시해도 되지만, 끄고 싶다면:

```powershell
git config --global core.autocrlf input
```

---

## 푸시 후 확인

1. 저장소의 **Actions** 탭에서 워크플로가 초록색으로 통과하는지 확인
2. 태그를 푸시했다면 **Releases** 에 `.app` zip 두 개가 첨부됨
   - `WiFiProfileManager-1.2.0-macos.zip` (경량, python3 필요)
   - `WiFiProfileManager-1.2.0-macos-standalone.zip` (파이썬 내장)
3. README 상단 배지와 clone 주소의 `OWNER` 를 본인 계정명으로 수정

## 이후 변경사항 올리기

```powershell
git add -A
git commit -m "설명"
git push
```

새 버전을 릴리스하려면 `src/wifi_profile_manager.py` 의 `APP_VERSION` 을 올리고
`CHANGELOG.md` 를 갱신한 뒤:

```powershell
git tag -a v1.3.0 -m "v1.3.0"
git push origin v1.3.0
```
