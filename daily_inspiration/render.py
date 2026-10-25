"""
책을 직접 촬영한 것처럼 보이는 이미지를 생성합니다.

1. 종이 질감 위에 본문을 조판합니다 (양쪽 정렬, 러닝헤드, 쪽번호, 형광펜 밑줄).
2. 책 가운데 접히는 부분(제본선)의 그림자와 종이의 휘어짐을 적용합니다.
3. 나무 책상 위에 비스듬히 놓고, 조명·비네팅·초점 흐림·노이즈를 더해 사진처럼 만듭니다.
"""
import hashlib
import math
import random
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent
FONT_DIR = BASE_DIR / "fonts"

# Google Fonts (SIL Open Font License) — 처음 실행할 때 자동으로 내려받습니다.
FONT_URLS = {
    "NanumMyeongjo-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/nanummyeongjo/NanumMyeongjo-Regular.ttf",
    "NanumMyeongjo-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/nanummyeongjo/NanumMyeongjo-Bold.ttf",
}

OUT_W, OUT_H = 1080, 1350          # 인스타그램 세로 피드 (4:5)
PAGE_W, PAGE_H = 1500, 2100        # 조판용 페이지 해상도
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 190, 260, 240

PAPER_TONES = [(244, 238, 224), (241, 233, 215), (246, 242, 233), (238, 229, 210)]
MARKER_COLORS = [(255, 226, 92), (255, 214, 120), (180, 230, 140), (255, 190, 200)]


def ensure_fonts():
    FONT_DIR.mkdir(exist_ok=True)
    for name, url in FONT_URLS.items():
        path = FONT_DIR / name
        if path.exists() and path.stat().st_size > 0:
            continue
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        path.write_bytes(resp.content)


def _font(name, size):
    return ImageFont.truetype(str(FONT_DIR / name), size)


# ---------------------------------------------------------------------------
# 1. 조판
# ---------------------------------------------------------------------------
def _wrap_paragraph(text, font, width, indent):
    """어절(띄어쓰기) 단위 줄바꿈. 한 어절이 줄보다 길면 글자 단위로 자릅니다.

    반환: [(words, is_last_line, line_indent)] — words는 (word, start_idx) 리스트
    """
    words, pos = [], 0
    for w in text.split(" "):
        if w:
            words.append((w, pos))
        pos += len(w) + 1

    space = font.getlength(" ")
    lines, cur, cur_w = [], [], 0.0
    line_indent = indent
    for word, start in words:
        ww = font.getlength(word)
        avail = width - line_indent
        need = ww if not cur else cur_w + space + ww
        if need <= avail:
            cur.append((word, start))
            cur_w = need
            continue
        if cur:
            # 남는 자리가 너무 크면 한국어 책처럼 어절 중간에서 끊어 채웁니다 (앞뒤 최소 2글자)
            room = avail - cur_w - space
            cut = 0
            if room > font.size * 2.5 and len(word) >= 4:
                while cut < len(word) - 2 and font.getlength(word[: cut + 1]) <= room:
                    cut += 1
            if cut >= 2:
                cur.append((word[:cut], start))
                word, start = word[cut:], start + cut
            lines.append((cur, False, line_indent))
            line_indent, cur, cur_w = 0, [], 0.0
        # 너무 긴 어절은 글자 단위로 분할
        while font.getlength(word) > width - line_indent:
            cut = len(word)
            while cut > 1 and font.getlength(word[:cut]) > width - line_indent:
                cut -= 1
            lines.append(([(word[:cut], start)], False, line_indent))
            line_indent = 0
            word, start = word[cut:], start + cut
        cur, cur_w = [(word, start)], font.getlength(word)
    if cur:
        lines.append((cur, True, line_indent))
    return lines


def _find_highlight_ranges(paragraphs, highlight):
    """하이라이트 문장이 들어 있는 (문단 번호, 시작, 끝) 범위를 찾습니다."""
    ranges = []
    if not highlight:
        return ranges
    for pi, p in enumerate(paragraphs):
        i = p.find(highlight)
        if i >= 0:
            ranges.append((pi, i, i + len(highlight)))
    return ranges


def _paper_texture(w, h, tone, rng):
    base = np.ones((h, w, 3), dtype=np.float32) * np.array(tone, dtype=np.float32)
    # 종이 섬유: 미세 노이즈 + 저주파 얼룩
    fine = rng.normal(0, 4.0, (h, w)).astype(np.float32)
    blotch = Image.fromarray((rng.random((h // 40, w // 40)) * 255).astype(np.uint8))
    blotch = blotch.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(30))
    blotch = (np.asarray(blotch, dtype=np.float32) - 128) / 128 * 5
    fiber = Image.fromarray((rng.random((h, w // 6)) * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)
    fiber = (np.asarray(fiber, dtype=np.float32) - 128) / 128 * 2.5
    noise = (fine + blotch + fiber)[..., None]
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def render_page(passage, rng):
    """평평한 책 한 페이지(오른쪽 페이지)를 그립니다."""
    tone = PAPER_TONES[rng.integers(len(PAPER_TONES))]
    page = Image.fromarray(_paper_texture(PAGE_W, PAGE_H, tone, rng))
    draw = ImageDraw.Draw(page)

    body_font = _font("NanumMyeongjo-Regular.ttf", 50)
    head_font = _font("NanumMyeongjo-Regular.ttf", 30)
    ink = (38, 34, 30)
    sub_ink = (110, 102, 92)

    # 러닝헤드 / 쪽번호
    head = passage["book"] + (f"  ·  {passage['chapter']}" if passage.get("chapter") else "")
    hw = draw.textlength(head, font=head_font)
    draw.text(((PAGE_W - hw) / 2, 150), head, font=head_font, fill=sub_ink)
    page_no = str(int(rng.integers(17, 289)))
    pw = draw.textlength(page_no, font=head_font)
    draw.text(((PAGE_W - pw) / 2, PAGE_H - 150), page_no, font=head_font, fill=sub_ink)

    paragraphs = [p.strip() for p in passage["text"].split("\n") if p.strip()]
    hl_ranges = _find_highlight_ranges(paragraphs, passage.get("highlight", ""))
    text_w = PAGE_W - MARGIN_X * 2
    line_h = int(body_font.size * 1.85)
    indent = body_font.getlength("가")

    laid = [(_wrap_paragraph(p, body_font, text_w, indent), pi) for pi, p in enumerate(paragraphs)]
    total_lines = sum(len(l) for l, _ in laid)
    block_h = total_lines * line_h + (len(laid) - 1) * line_h * 0.35
    avail_h = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
    # 본문을 페이지 위쪽~가운데 사이에 둡니다 (책 페이지처럼 보이도록 약간 위로)
    y = MARGIN_TOP + max(0, (avail_h - block_h) * 0.38)

    marker = MARKER_COLORS[rng.integers(len(MARKER_COLORS))]
    hl_layer = Image.new("L", page.size, 0)
    hl_draw = ImageDraw.Draw(hl_layer)
    word_boxes = []

    for lines, pi in laid:
        para = paragraphs[pi]
        for words, is_last, line_indent in lines:
            widths = [body_font.getlength(w) for w, _ in words]
            gaps = len(words) - 1
            base_space = body_font.getlength(" ")
            natural = sum(widths) + gaps * base_space
            space, tracking = base_space, 0.0
            if not is_last:
                # 양쪽 정렬: 남는 폭을 띄어쓰기에 먼저 나누되, 너무 벌어지면 자간에도 나눕니다
                extra = text_w - line_indent - natural
                n_chars = sum(len(w) for w, _ in words)
                gap_extra = min(extra, gaps * base_space * 0.5)
                if gaps > 0:
                    space += gap_extra / gaps
                tracking = (extra - (gap_extra if gaps > 0 else 0)) / max(n_chars - 1, 1)
            x = MARGIN_X + line_indent
            for (word, start), ww in zip(words, widths):
                for ci, ch in enumerate(word):
                    cw = body_font.getlength(ch)
                    draw.text((x, y), ch, font=body_font, fill=ink)
                    in_hl = any(hpi == pi and hs <= start + ci < he for hpi, hs, he in hl_ranges)
                    if in_hl:
                        word_boxes.append((x, x + cw, y))
                    x += cw + tracking
                x += space - tracking
            y += line_h
        y += line_h * 0.35

    # 형광펜: 같은 줄의 박스를 이어 붙이고 손으로 그은 듯 흔들리게
    by_line = {}
    for x0, x1, ly in word_boxes:
        by_line.setdefault(ly, []).append((x0, x1))
    for ly, spans in by_line.items():
        x0 = min(s for s, _ in spans) - rng.uniform(4, 14)
        x1 = max(e for _, e in spans) + rng.uniform(4, 14)
        top = ly + body_font.size * 0.12 + rng.uniform(-4, 4)
        bot = ly + body_font.size * 1.18 + rng.uniform(-4, 4)
        tilt = rng.uniform(-5, 5)
        hl_draw.polygon([(x0, top), (x1, top + tilt), (x1 + 3, bot + tilt), (x0 - 2, bot)], fill=150)
    if word_boxes:
        hl_layer = hl_layer.filter(ImageFilter.GaussianBlur(2.2))
        streak = Image.fromarray((rng.random((PAGE_H, PAGE_W // 8)) * 70 + 185).astype(np.uint8))
        streak = streak.resize(page.size, Image.BILINEAR)
        hl_layer = ImageChops.multiply(hl_layer, streak)
        color = Image.new("RGB", page.size, marker)
        # 형광펜은 곱하기(multiply) 합성 → 아래 글자가 비쳐 보임
        marked = ImageChops.multiply(page, color)
        page = Image.composite(marked, page, hl_layer)

    # 잉크가 종이에 살짝 번진 느낌
    return page.filter(ImageFilter.GaussianBlur(0.6))


# ---------------------------------------------------------------------------
# 2. 펼친 책 (왼쪽 페이지 일부 + 제본선 + 휘어짐)
# ---------------------------------------------------------------------------
def _remap(img_arr, map_x, map_y):
    """numpy만으로 구현한 bilinear remap (영역 밖은 투명)."""
    h, w = img_arr.shape[:2]
    x0 = np.floor(map_x).astype(np.int32)
    y0 = np.floor(map_y).astype(np.int32)
    fx, fy = (map_x - x0)[..., None], (map_y - y0)[..., None]
    valid = (x0 >= 0) & (y0 >= 0) & (x0 < w - 1) & (y0 < h - 1)
    x0c, y0c = np.clip(x0, 0, w - 2), np.clip(y0, 0, h - 2)
    a = img_arr[y0c, x0c].astype(np.float32)
    b = img_arr[y0c, x0c + 1].astype(np.float32)
    c = img_arr[y0c + 1, x0c].astype(np.float32)
    d = img_arr[y0c + 1, x0c + 1].astype(np.float32)
    out = a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy
    out[~valid] = 0
    return out.astype(np.uint8)


def build_open_book(page, rng, filler):
    """오른쪽 페이지 + 잘린 왼쪽 페이지로 펼친 책을 만들고 종이를 휘게 합니다."""
    left_w = int(PAGE_W * 0.22)
    W, H = left_w + PAGE_W, PAGE_H
    spread = Image.new("RGB", (W, H))
    left = Image.fromarray(_paper_texture(left_w, H, PAPER_TONES[0], rng))
    # 왼쪽 페이지에는 희미한 글줄 흔적만 (초점 밖)
    ld = ImageDraw.Draw(left)
    font = _font("NanumMyeongjo-Regular.ttf", 50)
    filler = filler.replace("\n", " ") + " "
    yy = MARGIN_TOP + 40
    while yy < H - MARGIN_BOTTOM:
        offset = rng.integers(0, len(filler))
        ld.text((-int(rng.integers(40, 300)), yy), (filler * 3)[offset: offset + 40], font=font, fill=(60, 55, 50))
        yy += int(font.size * 1.85)
    left = left.filter(ImageFilter.GaussianBlur(3))
    spread.paste(left, (0, 0))
    spread.paste(page, (left_w, 0))

    arr = np.asarray(spread).astype(np.float32)
    gutter = left_w
    xs = np.arange(W, dtype=np.float32)

    # 제본선 근처 그림자 (양쪽으로 어두워짐)
    dist = np.abs(xs - gutter)
    shade = 1 - 0.55 * np.exp(-dist / 55) - 0.18 * np.exp(-dist / 260)
    # 바깥쪽 가장자리로 갈수록 살짝 밝게/어둡게
    shade *= 1 - 0.06 * (xs / W)
    arr *= shade[None, :, None]
    arr = np.clip(arr, 0, 255).astype(np.uint8)

    # 종이 휘어짐: 제본선 쪽이 아래로 말려 들어가고, 페이지 위·아래는 반대로 휨
    yy_, xx_ = np.mgrid[0:H, 0:W].astype(np.float32)
    rel = (xx_ - gutter) / (W - gutter)                  # 오른쪽 페이지: 0(제본선) → 1(바깥)
    curl = np.where(rel >= 0, np.exp(-rel * 4.0), np.exp(rel * 9.0))
    vy = (yy_ - H / 2) / (H / 2)                          # -1(위) → 1(아래)
    amp = rng.uniform(26, 42)
    map_y = yy_ - amp * curl * vy * 1.0 - 10 * np.sin(np.clip(rel, 0, 1) * math.pi) * vy
    # 가운데로 갈수록 가로로 압축(종이가 기울어져 보이는 효과)
    map_x = xx_ + 18 * curl * np.sign(xx_ - gutter)
    warped = _remap(arr, map_x, map_y)

    alpha = np.full((H, W), 255, dtype=np.uint8)
    alpha = _remap(alpha[..., None], map_x, map_y)[..., 0]
    img = Image.fromarray(warped).convert("RGBA")
    img.putalpha(Image.fromarray(alpha))
    return img, gutter


# ---------------------------------------------------------------------------
# 3. 촬영 효과
# ---------------------------------------------------------------------------
def _wood_background(w, h, rng):
    base = np.array(
        [(122, 86, 58), (96, 68, 46), (150, 118, 88), (70, 52, 40)][rng.integers(4)],
        dtype=np.float32,
    )
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    phase = rng.uniform(0, 100)
    lowfreq = Image.fromarray((rng.random((h // 60 + 2, 6)) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    warp = (np.asarray(lowfreq, dtype=np.float32) / 255) * 40
    grain = np.sin((x * 0.06 + warp + phase) * 1.7) * 0.5 + np.sin((x * 0.013 + warp * 0.3) * 3.1) * 0.5
    fine = rng.normal(0, 1, (h, w)).astype(np.float32)
    fine = np.asarray(Image.fromarray(((fine + 3) * 40).clip(0, 255).astype(np.uint8)).resize((w, h)).filter(ImageFilter.GaussianBlur(1)), dtype=np.float32) / 40 - 3
    lum = 1 + 0.12 * grain + 0.03 * fine
    arr = base[None, None, :] * lum[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _perspective_coeffs(src, dst):
    """dst 좌표 → src 좌표로 가는 PIL PERSPECTIVE 계수."""
    matrix = []
    for (xs, ys), (xd, yd) in zip(src, dst):
        matrix.append([xd, yd, 1, 0, 0, 0, -xs * xd, -xs * yd])
        matrix.append([0, 0, 0, xd, yd, 1, -ys * xd, -ys * yd])
    A = np.array(matrix, dtype=np.float64)
    B = np.array(src, dtype=np.float64).reshape(8)
    return np.linalg.solve(A, B).tolist()


def photograph(book, gutter, rng):
    """펼친 책을 책상 위에 놓고 사진을 찍은 것처럼 만듭니다."""
    scale = 3  # 원근 변환은 큰 캔버스에서 한 뒤 축소 (안티앨리어싱)
    CW, CH = OUT_W * scale // 2, OUT_H * scale // 2
    canvas = _wood_background(CW, CH, rng).convert("RGBA")

    bw, bh = book.size
    # 프레임 안에 오른쪽 페이지가 대부분 들어오도록 배치
    target_h = CH * rng.uniform(1.0, 1.08)
    s = target_h / bh
    book_s = book.resize((int(bw * s), int(bh * s)), Image.LANCZOS)
    bw, bh = book_s.size
    gx = gutter * s

    # 원근: 위쪽이 조금 좁아지게 (카메라가 아래쪽에서 비스듬히 내려다봄)
    k = rng.uniform(0.03, 0.06)
    skew = rng.uniform(-0.02, 0.02)
    src = [(0, 0), (bw, 0), (bw, bh), (0, bh)]
    dst = [
        (bw * (k + skew), bh * 0.01),
        (bw * (1 - k + skew), 0),
        (bw * (1 + 0.01), bh),
        (-bw * 0.01, bh * 0.99),
    ]
    coeffs = _perspective_coeffs(src, dst)
    book_p = book_s.transform((bw, bh), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    angle = rng.uniform(-3.0, 3.0)
    book_p = book_p.rotate(angle, resample=Image.BICUBIC, expand=True)

    # 위치: 제본선이 왼쪽 가장자리 근처에 오도록
    ox = int(-gx + CW * rng.uniform(0.03, 0.09))
    oy = int((CH - book_p.size[1]) / 2 + rng.uniform(-20, 20))

    # 그림자
    shadow_alpha = book_p.split()[3].point(lambda a: int(a * 0.65))
    shadow = Image.new("RGBA", book_p.size, (15, 10, 5, 0))
    shadow.putalpha(shadow_alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas.alpha_composite(shadow, (ox + 22, oy + 30))
    # 책 두께(페이지 단면) — 아래·오른쪽에 얇은 층
    edge = Image.new("RGBA", book_p.size, (214, 204, 186, 0))
    edge.putalpha(book_p.split()[3])
    for i in range(6, 0, -1):
        canvas.alpha_composite(edge, (ox + i * 2, oy + i * 3))
    canvas.alpha_composite(book_p, (ox, oy))

    img = canvas.convert("RGB").resize((OUT_W, OUT_H), Image.LANCZOS)
    arr = np.asarray(img).astype(np.float32)

    h, w = arr.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    # 창가에서 들어오는 빛: 한쪽 위에서 밝고 반대편 아래가 어두움
    lx, ly = rng.uniform(0.6, 1.1) * w, rng.uniform(-0.2, 0.2) * h
    d = np.sqrt((x - lx) ** 2 + (y - ly) ** 2) / math.hypot(w, h)
    light = 1.10 - 0.38 * d
    # 비네팅
    vx, vy = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
    vignette = 1 - 0.22 * (vx ** 2 + vy ** 2) ** 1.2
    arr *= (light * vignette)[..., None]
    # 따뜻한 색온도 + 약간 바랜 톤
    warm = np.array([1.04, 1.0, 0.92], dtype=np.float32)
    arr = arr * warm + 6
    arr = np.clip(arr, 0, 255)

    img = Image.fromarray(arr.astype(np.uint8))
    # 얕은 피사계 심도: 위·아래 가장자리를 흐리게
    blurred = img.filter(ImageFilter.GaussianBlur(4))
    focus = np.abs((y / h) - rng.uniform(0.42, 0.52)) * 2
    focus_mask = np.clip((focus - 0.45) * 2.2, 0, 1)
    img = Image.composite(blurred, img, Image.fromarray((focus_mask * 255).astype(np.uint8)))

    # 센서 노이즈
    arr = np.asarray(img).astype(np.float32)
    lum_noise = rng.normal(0, 3.2, (h, w, 1))
    chroma_noise = rng.normal(0, 1.2, (h, w, 3))
    arr = np.clip(arr + lum_noise + chroma_noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def render_photo(passage, out_path, seed=None, filler_text=None):
    """passage(dict) → 책 사진 JPEG 파일 생성. 경로를 반환합니다.

    filler_text: 흐릿하게 보이는 왼쪽 페이지에 깔 글 (없으면 본문을 재사용)
    """
    ensure_fonts()
    if seed is None:
        seed = int(hashlib.md5(passage["id"].encode()).hexdigest()[:8], 16) + random.randint(0, 10_000)
    rng = np.random.default_rng(seed)
    page = render_page(passage, rng)
    book, gutter = build_open_book(page, rng, filler_text or passage["text"])
    photo = photograph(book, gutter, rng)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    photo.save(out_path, "JPEG", quality=92, subsampling=0)
    return out_path
