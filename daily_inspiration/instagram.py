"""
인스타그램 업로드 (공식 Instagram Graph API — Content Publishing).

필요 조건
- 인스타그램 프로페셔널 계정(비즈니스 또는 크리에이터)
- 액세스 토큰(instagram_content_publish 권한)과 IG 사용자 ID
- Graph API는 이미지 '파일'이 아니라 '공개 URL'을 받으므로, 먼저 이미지를 공개 위치에 올려야 합니다.
"""
import base64
import os
import subprocess
import time
from pathlib import Path

import requests

GRAPH_HOST = os.getenv("INSTAGRAM_GRAPH_HOST", "graph.facebook.com")  # Instagram 로그인 방식이면 graph.instagram.com
GRAPH_VERSION = os.getenv("INSTAGRAM_GRAPH_VERSION", "v23.0")


class InstagramError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 이미지 호스팅
# ---------------------------------------------------------------------------
def host_image(path: Path) -> str:
    """이미지를 공개 URL로 올리고 URL을 반환합니다. IMAGE_HOST 환경변수로 방식을 고릅니다."""
    mode = os.getenv("IMAGE_HOST", "imgbb").lower()
    if mode == "imgbb":
        return _host_imgbb(path)
    if mode == "github":
        return _host_github(path)
    if mode == "url":
        # 이미 output 폴더가 웹에 공개되어 있는 경우 (예: 자체 서버, GitHub Pages)
        base = os.environ["PUBLIC_IMAGE_BASE_URL"].rstrip("/")
        return f"{base}/{path.name}"
    raise ValueError(f"알 수 없는 IMAGE_HOST: {mode}")


def _host_imgbb(path: Path) -> str:
    key = os.environ["IMGBB_API_KEY"]
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": key, "image": base64.b64encode(path.read_bytes()).decode()},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["data"]["url"]


def _host_github(path: Path) -> str:
    """이미지를 현재 저장소에 커밋·푸시하고 raw URL을 돌려줍니다 (공개 저장소에서만 동작)."""
    repo = os.environ["GITHUB_REPOSITORY"]          # GitHub Actions가 자동으로 설정
    branch = os.getenv("GITHUB_REF_NAME", "main")
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    rel = path.resolve().relative_to(root).as_posix()
    subprocess.run(["git", "add", "-f", rel], check=True, cwd=root)
    subprocess.run(["git", "commit", "-m", f"daily-inspiration: add {path.name}"], check=True, cwd=root)
    subprocess.run(["git", "push"], check=True, cwd=root)
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"


# ---------------------------------------------------------------------------
# Graph API
# ---------------------------------------------------------------------------
def _api(method, endpoint, **params):
    params["access_token"] = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    url = f"https://{GRAPH_HOST}/{GRAPH_VERSION}/{endpoint}"
    resp = requests.request(method, url, data=params if method == "POST" else None,
                            params=params if method == "GET" else None, timeout=60)
    body = resp.json()
    if resp.status_code != 200 or "error" in body:
        raise InstagramError(f"{endpoint}: {body.get('error', body)}")
    return body


def publish_photo(image_url: str, caption: str, timeout_sec: int = 300) -> str:
    """사진 1장을 피드에 게시하고 미디어 ID를 반환합니다."""
    ig_user = os.environ["INSTAGRAM_USER_ID"]

    # 1) 미디어 컨테이너 생성
    container = _api("POST", f"{ig_user}/media", image_url=image_url, caption=caption)["id"]

    # 2) 인스타그램이 이미지를 가져가 처리할 때까지 대기
    deadline = time.time() + timeout_sec
    while True:
        status = _api("GET", container, fields="status_code").get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"컨테이너 처리 실패: {status}")
        if time.time() > deadline:
            raise InstagramError("컨테이너 처리 시간 초과")
        time.sleep(5)

    # 3) 게시
    return _api("POST", f"{ig_user}/media_publish", creation_id=container)["id"]
