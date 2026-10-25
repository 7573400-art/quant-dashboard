# 인스타저장 (안드로이드 앱)

광고 없는 인스타그램 동영상 다운로더 안드로이드 앱입니다.
서버 없이 폰 안에서 yt-dlp(youtubedl-android)로 바로 받아 **갤러리(Movies/InstaSaver)** 에 저장합니다.

## 설치
1. GitHub 저장소의 **Releases** 에서 최신 `인스타저장 v1.0.N` 을 엽니다.
2. `InstaSaver-…-arm64-v8a.apk` 를 휴대폰에서 받습니다. (대부분의 폰)
3. 설치 시 "출처를 알 수 없는 앱" 허용을 눌러 설치합니다.

## 사용법
- **공유로 받기:** 인스타그램 앱에서 게시물·릴스의 공유(종이비행기) → **인스타저장** → 자동 다운로드
- **링크 복사 후:** 앱을 열면 클립보드의 링크가 자동으로 채워집니다 → 다운로드
- 여러 장짜리 게시물은 동영상을 모두 받습니다.
- 받은 영상은 앱에서 바로 **열기 / 공유** 할 수 있습니다.
- 비공개 계정이나 로그인을 요구하는 경우: 오른쪽 위 메뉴 → **인스타그램 로그인**
  (로그인 정보는 폰 안의 앱 저장소에만 보관됩니다)
- 다운로드가 안 되면: 메뉴 → **다운로드 엔진 업데이트** (앱이 하루 한 번 자동으로도 합니다)

## 빌드
`insta_downloader/android/` 이하가 바뀌어 푸시되면 GitHub Actions(`.github/workflows/android.yml`)가
APK 를 빌드해 Actions 아티팩트와 Releases 에 올립니다. 로컬에서는 Android Studio 로 이 폴더를 열면 됩니다.

### 업데이트를 덮어 설치하려면 (서명 키 설정)
서명 키가 없으면 빌드마다 임시 키로 서명되어, 새 버전을 설치할 때 기존 앱을 지워야 합니다.
한 번만 아래처럼 키를 만들어 저장소 **Settings → Secrets and variables → Actions** 에 넣어 두세요.

```bash
keytool -genkeypair -v -keystore release.jks -alias insta -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 release.jks   # 출력값을 KEYSTORE_BASE64 로
```
| Secret | 값 |
|---|---|
| `KEYSTORE_BASE64` | 위 base64 출력 |
| `KEYSTORE_PASSWORD` | 키스토어 비밀번호 |
| `KEY_ALIAS` | `insta` |
| `KEY_PASSWORD` | 키 비밀번호 |

`release.jks` 파일은 잃어버리면 같은 앱으로 업데이트할 수 없으니 안전한 곳에 백업하고, 저장소에는 올리지 마세요.
