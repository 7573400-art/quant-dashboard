"""
광고 없는 인스타그램 동영상 다운로더 (insget 스타일)

- 인스타그램 게시물/릴스/IGTV 링크를 붙여넣으면 미디어 목록을 보여주고
  원하는 항목을 바로 다운로드할 수 있다.
- 스마트폰에서 '홈 화면에 추가'하면 앱처럼 쓸 수 있다 (PWA).
  안드로이드에서는 인스타그램 앱의 '공유' 메뉴에서 바로 이 앱으로 링크를 보낼 수 있다.

실행:
    pip install -r requirements.txt
    python app.py            # http://localhost:8000

환경변수:
    PORT                 서버 포트 (기본 8000)
    INSTA_COOKIES        로그인 쿠키 파일(Netscape 형식) 경로.
                         비공개 계정이나 로그인이 필요한 게시물에 필요하다.
"""

import mimetypes
import os
import re
import shutil
import tempfile
from urllib.parse import urlparse

import requests
import yt_dlp
from flask import Flask, Response, after_this_request, jsonify, render_template, request, send_file

app = Flask(__name__)

ALLOWED_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am"}
URL_RE = re.compile(r"https?://[^\s]+")
COOKIES = os.environ.get("INSTA_COOKIES")
HAS_FFMPEG = shutil.which("ffmpeg") is not None
# 썸네일 프록시가 접근할 수 있는 인스타그램 CDN 도메인
CDN_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")


def normalize_url(text):
    """붙여넣은 텍스트에서 인스타그램 링크만 뽑아내고 검증한다."""
    match = URL_RE.search(text or "")
    if not match:
        return None
    url = match.group(0).rstrip(").,")
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        return None
    # 추적용 쿼리(?igsh=...)는 제거
    return f"https://www.instagram.com{parsed.path}"


def ydl_opts(**extra):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        # 인스타그램 추출기만 허용해 다른 사이트 요청을 막는다
        "allowed_extractors": ["Instagram.*"],
        # ffmpeg 가 있으면 최고화질 영상+음성 병합, 없으면 음성 포함된 단일 파일
        "format": "bv*+ba/b" if HAS_FFMPEG else "b[acodec!=none][vcodec!=none]/b",
        "merge_output_format": "mp4",
    }
    if COOKIES:
        opts["cookiefile"] = COOKIES
    opts.update(extra)
    return opts


def extract(url):
    with yt_dlp.YoutubeDL(ydl_opts()) as ydl:
        return ydl.extract_info(url, download=False)


def entries_of(info):
    """단일 게시물이든 여러 장(캐러셀)이든 항목 리스트로 만든다."""
    if info.get("_type") == "playlist":
        return [e for e in info.get("entries") or [] if e]
    return [info]


def friendly_error(exc):
    msg = str(exc)
    if "login" in msg.lower() or "rate" in msg.lower() or "cookies" in msg.lower():
        return "인스타그램이 로그인을 요구합니다. 비공개 게시물이거나 요청이 많아 차단되었을 수 있어요. (INSTA_COOKIES 설정 필요)"
    if "no video" in msg.lower():
        return "이 게시물에는 동영상이 없습니다."
    return "동영상을 가져오지 못했습니다. 링크를 확인해 주세요."


@app.get("/")
def index():
    # 안드로이드 공유 메뉴(share_target)로 들어온 경우 링크를 미리 채워준다
    shared = request.args.get("url") or request.args.get("text") or ""
    return render_template("index.html", shared=normalize_url(shared) or "")


@app.post("/api/info")
def api_info():
    url = normalize_url((request.get_json(silent=True) or {}).get("url"))
    if not url:
        return jsonify(error="올바른 인스타그램 링크를 입력해 주세요."), 400
    try:
        info = extract(url)
    except yt_dlp.utils.DownloadError as e:
        return jsonify(error=friendly_error(e)), 422

    items = []
    for i, entry in enumerate(entries_of(info)):
        items.append({
            "index": i,
            "title": entry.get("title") or entry.get("description") or "",
            "thumbnail": entry.get("thumbnail"),
            "duration": entry.get("duration"),
            "width": entry.get("width"),
            "height": entry.get("height"),
        })
    return jsonify(
        url=url,
        uploader=info.get("uploader") or info.get("channel") or "",
        caption=(info.get("description") or "")[:300],
        items=items,
    )


@app.get("/api/download")
def api_download():
    url = normalize_url(request.args.get("url"))
    if not url:
        return jsonify(error="올바른 인스타그램 링크를 입력해 주세요."), 400
    try:
        index = int(request.args.get("index", 0))
    except ValueError:
        index = 0

    workdir = tempfile.mkdtemp(prefix="insta_")

    @after_this_request
    def cleanup(response):
        shutil.rmtree(workdir, ignore_errors=True)
        return response

    opts = ydl_opts(
        outtmpl=os.path.join(workdir, "%(uploader_id|instagram)s_%(id)s.%(ext)s"),
        playlist_items=str(index + 1),
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        return jsonify(error=friendly_error(e)), 422

    files = [f for f in os.listdir(workdir) if not f.endswith((".part", ".ytdl"))]
    if not files:
        return jsonify(error="다운로드할 파일을 찾지 못했습니다."), 404
    path = os.path.join(workdir, files[0])
    # 응답을 보낸 뒤 임시폴더를 지우므로 파일을 메모리가 아닌 열린 핸들로 넘긴다
    handle = open(path, "rb")
    os.unlink(path)
    return send_file(handle, as_attachment=True, download_name=files[0], mimetype=mimetypes.guess_type(files[0])[0] or "video/mp4")


@app.get("/api/thumb")
def api_thumb():
    # 인스타그램 CDN은 다른 사이트에서의 이미지 직접 로딩을 막으므로 서버가 대신 받아준다
    src = request.args.get("src", "")
    parsed = urlparse(src)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(CDN_SUFFIXES):
        return "", 400
    r = requests.get(src, timeout=10)
    if not r.ok:
        return "", 502
    return Response(r.content, mimetype=r.headers.get("Content-Type", "image/jpeg"),
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sw.js")
def service_worker():
    # 서비스워커는 루트 범위에서 제공해야 앱 전체를 제어할 수 있다
    return app.send_static_file("sw.js")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
