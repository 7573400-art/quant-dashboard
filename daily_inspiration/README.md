# 📖 Daily Inspiration — 오늘의 문장 인스타그램 자동 업로드

매일 수필·고전에서 삶의 영감을 주는 문장을 골라 **책을 직접 펼쳐 찍은 사진처럼** 이미지를 만들고,
인스타그램 피드에 자동으로 게시합니다.

```
passages.json ──▶ render.py ──────────────▶ instagram.py ─────────▶ Instagram
 (문장 DB)        종이 질감·조판·형광펜      이미지 공개 URL 업로드
                  제본선 그림자·종이 휨       → Graph API 게시
                  책상·조명·초점·노이즈
```

## 파일 구성

| 파일 | 역할 |
|---|---|
| `passages.json` | 문장 데이터베이스 (작가, 책, 장, 본문, 형광펜 칠할 문장, 해시태그) |
| `render.py` | 책 사진 이미지 생성 (1080×1350, 인스타 4:5 세로 피드) |
| `instagram.py` | 이미지 호스팅 + Instagram Graph API 게시 |
| `run.py` | 오늘의 문장 선택 → 이미지 → 캡션 → 업로드, `history.json`에 기록 |
| `../.github/workflows/daily-inspiration.yml` | 매일 오전 6:47(KST) 자동 실행 |

## 1. 로컬에서 미리보기

```bash
cd daily_inspiration
pip install -r requirements.txt
python run.py --dry-run                 # output/ 에 이미지(.jpg)와 캡션(.txt) 생성
python run.py --id rilke-01 --dry-run   # 특정 문장으로 생성
```

처음 실행할 때 나눔명조 폰트(OFL 라이선스)를 `fonts/`에 자동으로 내려받습니다.
같은 문장이라도 실행할 때마다 종이색·형광펜 색·각도·조명이 조금씩 달라집니다.

## 2. 인스타그램 API 준비

인스타그램은 공식 **Graph API(Content Publishing)** 로만 안전하게 자동 게시할 수 있습니다.
(비공식 로그인 자동화는 계정 정지 위험이 있어 사용하지 않습니다.)

1. 인스타그램 계정을 **프로페셔널 계정(비즈니스/크리에이터)** 으로 전환
2. [Meta for Developers](https://developers.facebook.com/)에서 앱 생성 → *Instagram* 제품 추가
3. `instagram_business_basic`, `instagram_business_content_publish` 권한으로 **장기 액세스 토큰** 발급
4. 토큰과 함께 **Instagram 사용자 ID** 확인

| 로그인 방식 | `INSTAGRAM_GRAPH_HOST` |
|---|---|
| Instagram 로그인 (페이스북 페이지 불필요, 권장) | `graph.instagram.com` |
| Facebook 로그인 (페이스북 페이지 연결) | `graph.facebook.com` (기본값) |

> ⚠️ 장기 토큰은 **60일** 후 만료됩니다. 만료 전에 갱신해서 Secret을 바꿔 주세요.
> (Instagram 로그인 방식: `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=...`)

## 3. 이미지 호스팅

Graph API는 파일이 아닌 **공개 이미지 URL**을 받습니다. `IMAGE_HOST`로 방식을 고릅니다.

| `IMAGE_HOST` | 설명 | 필요한 값 |
|---|---|---|
| `imgbb` (기본) | 무료 이미지 호스팅에 업로드 | `IMGBB_API_KEY` ([api.imgbb.com](https://api.imgbb.com/)에서 발급) |
| `github` | 이미지를 이 저장소에 커밋하고 raw URL 사용 — **공개 저장소에서만 동작** | 없음 (Actions 기본값 사용) |
| `url` | `output/` 폴더를 직접 웹에 공개하는 경우 | `PUBLIC_IMAGE_BASE_URL` |

## 4. 매일 자동 실행 (GitHub Actions)

저장소 **Settings → Secrets and variables → Actions** 에 등록합니다.

- **Secrets**: `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `IMGBB_API_KEY`
- **Variables** (선택): `INSTAGRAM_GRAPH_HOST`, `IMAGE_HOST`

워크플로는 매일 **06:47 KST** 에 실행되고, 게시가 끝나면 `history.json`을 커밋해
같은 문장이 다시 올라가지 않게 합니다. 모든 문장을 한 번씩 올리면 가장 오래전에 올린 문장부터 다시 순환합니다.
**Actions 탭 → Daily Inspiration → Run workflow** 로 수동 실행(미리보기 포함)도 할 수 있습니다.

> GitHub의 `schedule` 트리거는 **기본 브랜치(main)** 에 있는 워크플로만 실행합니다. 이 브랜치를 main에 병합해야 매일 동작합니다.

로컬 PC/서버에서 돌리고 싶다면 `.env`에 같은 값을 넣고 cron에 등록하면 됩니다.

```bash
# crontab -e  (매일 오전 7시)
0 7 * * * cd /path/to/quant-dashboard/daily_inspiration && python run.py >> post.log 2>&1
```

## 5. 문장 추가하기

`passages.json`에 항목을 추가하면 됩니다.

```json
{
  "id": "고유-id",
  "author": "작가",
  "book": "책 제목",
  "chapter": "장 (없으면 빈 문자열)",
  "text": "본문. 문단은 \n 으로 구분합니다.",
  "highlight": "본문 안에서 형광펜을 칠할 문장 (본문에 그대로 있어야 함)",
  "tags": ["해시태그", "샵없이"]
}
```

### ⚖️ 저작권 주의

기본 문장은 모두 **저작권이 만료된 원전**(마르쿠스 아우렐리우스, 세네카, 소로, 에머슨, 몽테뉴, 릴케,
칼릴 지브란, 톨스토이, 파스칼, 니체, 노자, 장자, 공자, 김구 등)을 **직접 새로 번역·발췌**한 것입니다.
시중 번역서의 문장이나 저작권이 살아 있는 현대 수필(한국 기준 저자 사후 70년 미경과)은
짧은 인용이라도 매일 상업적 계정에 게시하면 문제가 될 수 있으니, 추가할 때 확인하세요.
