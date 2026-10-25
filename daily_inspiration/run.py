"""
오늘의 문장 → 책 사진 이미지 → 인스타그램 자동 업로드.

사용법
    python run.py --dry-run              # 이미지와 캡션만 만들고 업로드하지 않음
    python run.py                        # 오늘의 문장 생성 + 업로드
    python run.py --id rilke-01 --dry-run  # 특정 문장으로 미리보기
"""
import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

import render

BASE_DIR = Path(__file__).resolve().parent
PASSAGES_FILE = BASE_DIR / "passages.json"
HISTORY_FILE = BASE_DIR / "history.json"
OUTPUT_DIR = BASE_DIR / "output"
KST = timezone(timedelta(hours=9))

COMMON_TAGS = ["오늘의문장", "책스타그램", "글귀", "좋은글", "독서", "문장수집", "필사", "인생명언"]


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def pick_passage(passages, history, today):
    """아직 올리지 않은 문장 중 하나를 고릅니다. 모두 올렸다면 가장 오래전에 올린 것부터 다시."""
    used = {h["id"]: h["date"] for h in history}
    fresh = [p for p in passages if p["id"] not in used]
    if fresh:
        # 날짜를 시드로 써서 같은 날 다시 실행해도 같은 문장이 나오게
        return random.Random(today).choice(fresh)
    return min(passages, key=lambda p: used[p["id"]])


def build_caption(p):
    source = f"『{p['book']}』" + (f" {p['chapter']}" if p.get("chapter") else "")
    tags = " ".join("#" + t.replace(" ", "") for t in dict.fromkeys(p.get("tags", []) + COMMON_TAGS))
    parts = []
    if p.get("highlight"):
        parts.append(f"“{p['highlight']}”")
    parts += [
        p["text"].replace("\n", "\n\n"),
        f"— {p['author']}, {source}",
        "오늘 하루, 이 문장과 함께하시길 🌿",
        tags,
    ]
    return "\n\n".join(parts)[:2200]  # 인스타그램 캡션 최대 길이


def main():
    parser = argparse.ArgumentParser(description="오늘의 문장 인스타그램 자동 업로드")
    parser.add_argument("--dry-run", action="store_true", help="업로드하지 않고 이미지/캡션만 생성")
    parser.add_argument("--id", help="특정 문장 ID로 생성")
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env")
    load_dotenv()
    today = datetime.now(KST).strftime("%Y-%m-%d")

    passages = load_json(PASSAGES_FILE, [])
    history = load_json(HISTORY_FILE, [])

    if not args.id and not args.dry_run and any(h["date"] == today for h in history):
        print(f"[skip] {today} 에는 이미 게시했습니다.")
        return 0

    if args.id:
        matches = [p for p in passages if p["id"] == args.id]
        if not matches:
            print(f"[error] 문장 ID를 찾을 수 없습니다: {args.id}")
            return 1
        passage = matches[0]
    else:
        passage = pick_passage(passages, history, today)

    others = [p for p in passages if p["id"] != passage["id"]]
    filler = random.choice(others)["text"] if others else None
    image_path = render.render_photo(passage, OUTPUT_DIR / f"{today}_{passage['id']}.jpg", filler_text=filler)
    caption = build_caption(passage)
    image_path.with_suffix(".txt").write_text(caption, encoding="utf-8")
    print(f"[ok] 이미지: {image_path}")
    print("-" * 40 + "\n" + caption + "\n" + "-" * 40)

    if args.dry_run:
        return 0

    import instagram

    image_url = instagram.host_image(image_path)
    print(f"[ok] 공개 URL: {image_url}")
    media_id = instagram.publish_photo(image_url, caption)
    print(f"[ok] 게시 완료: media_id={media_id}")

    history.append({"date": today, "id": passage["id"], "media_id": media_id})
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
