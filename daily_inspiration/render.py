"""
책을 직접 촬영한 것처럼 보이는 이미지를 생성합니다.

2D 필터를 덧씌우는 대신, 작은 3D 장면을 만들어 '촬영'합니다.

1. 조판: 종이 질감 위에 본문을 양쪽 정렬로 찍고 러닝헤드·쪽번호·형광펜·뒷면 비침을 넣습니다.
2. 장면: 펼친 책(제본선에서 휘어 올라가는 페이지, 페이지 단면, 표지)을 책상 위에 놓습니다.
3. 촬영: 스마트폰 카메라 위치에서 픽셀마다 광선을 쏘아(ray marching) 책·책상과 만나는 점을 찾고,
   표면 기울기에 따른 조명, 책의 그림자, 거리에 따른 초점 흐림을 계산합니다.
4. 폰카 후처리: 화이트밸런스, 톤커브, 렌즈 비네팅·색수차, 센서 노이즈, 샤프닝, JPEG 압축.
"""
import hashlib
import math
import random
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent
FONT_DIR = BASE_DIR / "fonts"

# Google Fonts (SIL Open Font License) — 처음 실행할 때 자동으로 내려받습니다.
FONT_URLS = {
    "NanumMyeongjo-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/nanummyeongjo/NanumMyeongjo-Regular.ttf",
    "NanumMyeongjo-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/nanummyeongjo/NanumMyeongjo-Bold.ttf",
}

OUT_W, OUT_H = 1080, 1350          # 인스타그램 세로 피드 (4:5)
SS = 1.5                           # 슈퍼샘플링 배율 (렌더 후 축소)
PAGE_W, PAGE_H = 1500, 2100        # 조판용 페이지 해상도 (3D 장면의 길이 단위이기도 함: 1 = 약 0.09mm)
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 190, 260, 240

PAPER_TONES = [(244, 238, 224), (240, 233, 216), (246, 243, 235), (236, 228, 210)]
MARKER_COLORS = [(255, 226, 92), (255, 214, 120), (186, 232, 140), (255, 192, 203)]
COVER_COLORS = [(38, 52, 74), (120, 40, 36), (226, 220, 205), (58, 74, 56), (30, 30, 32), (196, 160, 110)]


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


def _smooth_noise(h, w, cells, rng):
    """0~1 범위의 부드러운 저주파 노이즈."""
    small = Image.fromarray((rng.random((max(cells[0], 2), max(cells[1], 2))) * 255).astype(np.uint8))
    return np.asarray(small.resize((w, h), Image.BICUBIC), dtype=np.float32) / 255


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
    fine = rng.normal(0, 2.2, (h, w)).astype(np.float32)
    blotch = (_smooth_noise(h, w, (h // 90, w // 90), rng) - 0.5) * 7
    fiber = (_smooth_noise(h, w, (h, w // 7), rng) - 0.5) * 3
    return np.clip(base + (fine + blotch + fiber)[..., None], 0, 255)


def _typeset(passage, rng, page_no, filler_mode=False):
    """페이지의 잉크 마스크(L)와 형광펜 마스크(L)를 만듭니다."""
    ink = Image.new("L", (PAGE_W, PAGE_H), 0)
    draw = ImageDraw.Draw(ink)
    body_font = _font("NanumMyeongjo-Regular.ttf", 50)
    head_font = _font("NanumMyeongjo-Regular.ttf", 30)

    head = passage["book"] + (f"  ·  {passage['chapter']}" if passage.get("chapter") else "")
    if filler_mode:
        head = passage.get("author", head)
    hw = draw.textlength(head, font=head_font)
    draw.text(((PAGE_W - hw) / 2, 150), head, font=head_font, fill=150)
    pw = draw.textlength(str(page_no), font=head_font)
    draw.text(((PAGE_W - pw) / 2, PAGE_H - 150), str(page_no), font=head_font, fill=150)

    paragraphs = [p.strip() for p in passage["text"].split("\n") if p.strip()]
    hl_ranges = [] if filler_mode else _find_highlight_ranges(paragraphs, passage.get("highlight", ""))
    text_w = PAGE_W - MARGIN_X * 2
    line_h = int(body_font.size * 1.85)
    indent = body_font.getlength("가")

    laid = [(_wrap_paragraph(p, body_font, text_w, indent), pi) for pi, p in enumerate(paragraphs)]
    if filler_mode:
        y = MARGIN_TOP
    else:
        total_lines = sum(len(l) for l, _ in laid)
        block_h = total_lines * line_h + (len(laid) - 1) * line_h * 0.35
        avail_h = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
        y = MARGIN_TOP + max(0, (avail_h - block_h) * 0.38)

    boxes = []
    for lines, pi in laid:
        for words, is_last, line_indent in lines:
            if y > PAGE_H - MARGIN_BOTTOM - line_h:
                break
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
                    # 인쇄 농도가 글자마다 미세하게 다름
                    draw.text((x, y), ch, font=body_font, fill=int(rng.uniform(222, 255)))
                    if any(hpi == pi and hs <= start + ci < he for hpi, hs, he in hl_ranges):
                        boxes.append((x, x + cw, y))
                    x += cw + tracking
                x += space - tracking
            y += line_h
        y += line_h * 0.35

    # 형광펜: 같은 줄의 박스를 이어 붙이고 손으로 그은 듯 흔들리게
    hl = Image.new("L", (PAGE_W, PAGE_H), 0)
    hl_draw = ImageDraw.Draw(hl)
    by_line = {}
    for x0, x1, ly in boxes:
        by_line.setdefault(ly, []).append((x0, x1))
    for ly, spans in by_line.items():
        x0 = min(s for s, _ in spans) - rng.uniform(4, 14)
        x1 = max(e for _, e in spans) + rng.uniform(4, 14)
        top = ly + body_font.size * 0.14 + rng.uniform(-4, 4)
        bot = ly + body_font.size * 1.16 + rng.uniform(-4, 4)
        tilt = rng.uniform(-5, 5)
        hl_draw.polygon([(x0, top), (x1, top + tilt), (x1 + 3, bot + tilt), (x0 - 2, bot)], fill=255)
    if boxes:
        hl = hl.filter(ImageFilter.GaussianBlur(2.0))
        streak = _smooth_noise(PAGE_H, PAGE_W, (PAGE_H // 3, PAGE_W // 10), rng) * 0.35 + 0.6
        hl = Image.fromarray((np.asarray(hl, dtype=np.float32) * streak).astype(np.uint8))

    ink = ink.filter(ImageFilter.GaussianBlur(0.7))     # 잉크 번짐
    return ink, hl


def render_page(passage, rng, tone, page_no, back_ink=None, filler_mode=False):
    """평평한 페이지 텍스처(float32 RGB)와 그 페이지의 잉크 마스크를 반환합니다."""
    paper = _paper_texture(PAGE_W, PAGE_H, tone, rng)
    ink, hl = _typeset(passage, rng, page_no, filler_mode)

    # 뒷면 글씨가 살짝 비침 (좌우 반전)
    if back_ink is not None:
        show = np.asarray(back_ink.transpose(Image.FLIP_LEFT_RIGHT), dtype=np.float32) / 255
        paper *= (1 - 0.055 * show)[..., None]

    # 형광펜은 곱하기 합성 → 아래 글자가 비쳐 보임
    if hl.getbbox():
        marker = MARKER_COLORS[rng.integers(len(MARKER_COLORS))]
        a = (np.asarray(hl, dtype=np.float32) / 255)[..., None] * 0.62
        paper = paper * (1 - a) + paper * (np.array(marker) / 255) * a

    ink_tone = np.array([34, 31, 30], dtype=np.float32)
    grain = _smooth_noise(PAGE_H, PAGE_W, (PAGE_H // 3, PAGE_W // 3), rng) * 0.2 + 0.8
    a = (np.asarray(ink, dtype=np.float32) / 255 * grain)[..., None]
    page = paper * (1 - a) + ink_tone * a
    return np.clip(page, 0, 255).astype(np.float32), ink


# ---------------------------------------------------------------------------
# 2. 3D 장면: 펼친 책 + 책상
# ---------------------------------------------------------------------------
def _sample(tex, u, v):
    """텍스처 bilinear 샘플링 (u=가로, v=세로 픽셀 좌표, 범위 밖은 가장자리 값)."""
    h, w = tex.shape[:2]
    u = np.clip(u, 0, w - 1.001)
    v = np.clip(v, 0, h - 1.001)
    x0, y0 = u.astype(np.int32), v.astype(np.int32)
    fx, fy = (u - x0)[..., None], (v - y0)[..., None]
    a, b = tex[y0, x0], tex[y0, x0 + 1]
    c, d = tex[y0 + 1, x0], tex[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


class Book:
    """책상(z=0) 위에 놓인 펼친 책. x=0이 제본선, y는 위(0)→아래(PAGE_H), z는 높이."""

    def __init__(self, rng):
        self.cover_t = rng.uniform(6, 14)              # 표지 두께
        self.cover_m = rng.uniform(14, 26)             # 표지가 종이보다 튀어나온 여백
        self.stack = rng.uniform(110, 230)             # 한쪽 페이지 묶음 높이
        self.k = rng.uniform(170, 280)                 # 제본선 곡률 폭
        self.dip = rng.uniform(0.72, 0.85)             # 제본선에서 얼마나 깊이 내려가는지
        self.droop = rng.uniform(15, 40)               # 바깥 가장자리 처짐
        # 페이지의 가로 실제 길이(호의 길이)가 PAGE_W가 되도록 바깥 끝 X를 찾음
        xs = np.linspace(0, PAGE_W * 1.05, 6000)
        self._xs = xs
        X = PAGE_W
        for _ in range(4):
            dz = np.gradient(self._raw(xs, X), xs)
            arc = np.concatenate([[0], np.cumsum(np.sqrt(1 + dz[1:] ** 2) * np.diff(xs))])
            X = float(np.interp(PAGE_W, arc, xs))
        self.X = X
        self._arc = arc
        self.top = self.cover_t + self.stack + 5

    def _raw(self, ax, X):
        t = np.clip(ax / X, 0, 1)
        return self.cover_t + self.stack * (1 - self.dip * np.exp(-ax / self.k)) - self.droop * t ** 6

    def height(self, x):
        return self._raw(np.abs(x), self.X)

    def slope(self, x):
        ax = np.abs(x)
        t = np.clip(ax / self.X, 0, 1)
        d = self.stack * self.dip / self.k * np.exp(-ax / self.k) - 6 * self.droop * t ** 5 / self.X
        return d * np.sign(x)

    def arclen(self, x):
        return np.interp(np.abs(x), self._xs, self._arc)

    def solid(self, x, y, z):
        """점이 책(페이지 묶음 또는 표지) 안에 있는지."""
        in_pages = (np.abs(x) <= self.X) & (y >= 0) & (y <= PAGE_H) & (z <= self.height(x)) & (z >= 0)
        m = self.cover_m
        in_cover = (np.abs(x) <= self.X + m) & (y >= -m) & (y <= PAGE_H + m) & (z <= self.cover_t) & (z >= 0)
        return in_pages | in_cover


def _wood_or_fabric(u, v, rng):
    """책상 표면 색 (u, v: 책상 좌표). 초점 밖이라 저주파 위주로 충분합니다."""
    kind = rng.integers(3)
    if kind == 0:   # 밝은 원목
        base = np.array([176, 136, 98]) * rng.uniform(0.7, 1.1)
        ring = np.sin((u * 0.004 + np.sin(v * 0.0007 + rng.uniform(0, 6)) * 2.2) * 6.0)
        streak = np.sin(u * 0.03 + np.sin(v * 0.002) * 3)
        lum = 1 + 0.07 * ring + 0.03 * streak
    elif kind == 1:  # 리넨 / 침구
        base = np.array([222, 216, 204]) * rng.uniform(0.85, 1.02)
        # 천의 주름: 방향이 다른 몇 개의 큰 물결을 겹침
        ph = rng.uniform(0, 6, 3)
        folds = (np.sin(u * 0.0021 + v * 0.0009 + ph[0]) * np.sin(v * 0.0013 - u * 0.0004 + ph[1])
                 + 0.6 * np.sin(u * 0.0047 - v * 0.0031 + ph[2]))
        lum = 1 + 0.02 * np.sin(u * 0.9) * np.sin(v * 0.9) + 0.09 * folds
    else:            # 짙은 원목
        base = np.array([92, 62, 42]) * rng.uniform(0.8, 1.2)
        ring = np.sin((u * 0.003 + np.sin(v * 0.0005 + rng.uniform(0, 6)) * 1.6) * 7.0)
        lum = 1 + 0.10 * ring + 0.03 * np.sin(u * 0.05)
    return base[None, :] * lum[..., None]


# ---------------------------------------------------------------------------
# 3. 촬영
# ---------------------------------------------------------------------------
def _camera_rays(rng, book, W, H):
    """스마트폰 카메라 위치와 픽셀별 광선 방향."""
    # 오른쪽 페이지 본문 근처를 겨냥, 폰을 살짝 기울여 아래쪽에서 비스듬히 내려다봄
    target = np.array([book.X * rng.uniform(0.47, 0.55), PAGE_H * rng.uniform(0.47, 0.53), book.top])
    tilt = math.radians(rng.uniform(10, 22))           # 수직에서 기운 각도
    yaw = math.radians(rng.uniform(-10, 10))
    fov_v = math.radians(62)                           # 폰 메인 카메라 세로 화각 근사
    dist = PAGE_H * rng.uniform(0.98, 1.06) / (2 * math.tan(fov_v / 2))
    back = np.array([math.sin(yaw) * math.sin(tilt), math.cos(yaw) * math.sin(tilt), math.cos(tilt)])
    cam = target + back * dist

    fwd = (target - cam) / np.linalg.norm(target - cam)
    up_hint = np.array([0.0, -1.0, 0.0])               # 화면 위쪽 = 페이지 위쪽
    right = np.cross(up_hint, fwd); right /= np.linalg.norm(right)
    up = np.cross(fwd, right)
    roll = math.radians(rng.uniform(-2.5, 2.5))
    right, up = right * math.cos(roll) + up * math.sin(roll), up * math.cos(roll) - right * math.sin(roll)

    th = math.tan(fov_v / 2)
    tw = th * W / H
    py, px = np.mgrid[0:H, 0:W].astype(np.float32)
    sx = ((px + 0.5) / W * 2 - 1) * tw
    sy = (1 - (py + 0.5) / H * 2) * th
    d = fwd[None, None, :] + sx[..., None] * right + sy[..., None] * up
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    return cam, d.astype(np.float32), dist


def _march(book, cam, d):
    """광선이 책과 처음 만나는 지점의 t (없으면 책상 z=0)."""
    dz = d[..., 2]
    t_top = (book.top - cam[2]) / dz
    t_floor = (0 - cam[2]) / dz
    steps = 48
    hit = np.zeros(dz.shape, bool)
    lo = t_top.copy()
    hi = t_floor.copy()
    prev = t_top
    for i in range(1, steps + 1):
        t = t_top + (t_floor - t_top) * (i / steps)
        p = cam + d * t[..., None]
        inside = book.solid(p[..., 0], p[..., 1], p[..., 2]) & ~hit
        lo = np.where(inside, prev, lo)
        hi = np.where(inside, t, hi)
        hit |= inside
        prev = t
    for _ in range(14):
        mid = (lo + hi) / 2
        p = cam + d * mid[..., None]
        inside = book.solid(p[..., 0], p[..., 1], p[..., 2])
        hi = np.where(hit & inside, mid, hi)
        lo = np.where(hit & ~inside, mid, lo)
    t = np.where(hit, hi, t_floor)
    return t, hit


def _shade_scene(book, cam, d, t, hit, right_tex, left_tex, rng, light):
    p = cam + d * t[..., None]
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    H_, W_ = t.shape
    color = np.zeros((H_, W_, 3), np.float32)
    normal = np.zeros((H_, W_, 3), np.float32)
    normal[..., 2] = 1

    eps = 2.5
    in_x = np.abs(x) <= book.X + 0.5
    in_y = (y >= -0.5) & (y <= PAGE_H + 0.5)
    on_top = hit & in_x & in_y & (z >= book.height(x) - eps)
    on_pages_side = hit & ~on_top & (z > book.cover_t + 0.5) & in_x & in_y
    on_cover = hit & ~on_top & ~on_pages_side
    table = ~hit

    # 페이지 윗면
    s = book.arclen(x)
    u_r = s
    u_l = PAGE_W - s
    tex = np.where((x >= 0)[..., None], _sample(right_tex, u_r, y), _sample(left_tex, u_l, y))
    color[on_top] = tex[on_top]
    sl = book.slope(x)
    n = np.stack([-sl, np.zeros_like(sl), np.ones_like(sl)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    normal[on_top] = n[on_top]
    # 제본선 깊은 곳의 차폐광(AO)
    ao = 1 - 0.45 * np.exp(-np.abs(x) / 70) - 0.12 * np.exp(-np.abs(x) / 300)

    # 페이지 단면: 얇은 종이층 줄무늬
    layer = 0.93 + 0.05 * np.sin(z * 2.7 + np.sin(x * 0.01 + y * 0.01) * 2) + 0.02 * np.sin(z * 9.1)
    edge_col = np.array([236, 228, 212], np.float32)[None, :] * layer[..., None]
    color[on_pages_side] = edge_col[on_pages_side]
    side_n = np.zeros_like(normal)
    near_x = np.abs(np.abs(x) - book.X) < np.minimum(np.abs(y - PAGE_H), np.abs(y))
    side_n[..., 0] = np.where(near_x, np.sign(x), 0)
    side_n[..., 1] = np.where(near_x, 0, np.where(y > PAGE_H / 2, 1, -1))
    normal[on_pages_side] = side_n[on_pages_side]

    # 표지
    cover_col = np.array(COVER_COLORS[rng.integers(len(COVER_COLORS))], np.float32)
    cv = cover_col * (0.96 + 0.04 * _smooth_noise(H_, W_, (H_ // 20, W_ // 20), rng))[..., None]
    color[on_cover] = cv[on_cover]

    # 책상
    color[table] = _wood_or_fabric(x[table], y[table], rng)

    # --- 조명 ---
    L = light / np.linalg.norm(light)
    lambert = np.clip((normal * L).sum(-1), 0, 1)
    shade = 0.42 + 0.68 * lambert
    shade = np.where(on_top, shade * ao, shade)

    # 책이 책상에 드리우는 그림자 (빛 방향으로 광선을 쏴서 책에 막히는지)
    shadow = np.zeros(t.shape, np.float32)
    pt = p[table]
    blocked = np.zeros(len(pt), bool)
    for k in range(1, 13):
        q = pt + L * (book.top / L[2] * (k / 12))
        blocked |= book.solid(q[:, 0], q[:, 1], q[:, 2])
    shadow[table] = blocked
    sh_img = Image.fromarray((shadow * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(W_ / 90))
    shadow = np.asarray(sh_img, np.float32) / 255
    # 책 바로 옆 접촉 그림자
    contact = Image.fromarray((hit * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(W_ / 160))
    contact = np.asarray(contact, np.float32) / 255
    shade = np.where(table, shade * (1 - 0.45 * shadow) * (1 - 0.35 * contact), shade)

    # 빛이 넓게 퍼지는 실내광: 화면에서 한쪽이 더 밝음
    lx, ly = rng.uniform(-0.3, 1.3), rng.uniform(-0.3, 0.4)
    gy, gx = np.mgrid[0:H_, 0:W_].astype(np.float32)
    falloff = 1.08 - 0.30 * np.sqrt((gx / W_ - lx) ** 2 + (gy / H_ - ly) ** 2)
    shade *= falloff

    # 폰이나 손이 드리운 아주 부드러운 그림자 (가끔)
    if rng.random() < 0.55:
        cx, cy = rng.uniform(-0.1, 1.1) * W_, rng.uniform(0.75, 1.25) * H_
        r = rng.uniform(0.35, 0.6) * W_
        blob = np.exp(-(((gx - cx) / r) ** 2 + ((gy - cy) / (r * 0.8)) ** 2) * 1.5)
        shade *= 1 - rng.uniform(0.12, 0.25) * blob

    # 창문으로 들어오는 햇빛 (창살 그림자가 책과 책상에 부드럽게 걸침)
    if rng.random() < 0.45:
        xw = x - z * L[0] / L[2]
        yw = y - z * L[1] / L[2]
        ang = rng.uniform(-0.6, 0.6)
        a_ = xw * math.cos(ang) + yw * math.sin(ang)
        b_ = -xw * math.sin(ang) + yw * math.cos(ang)
        pane = rng.uniform(700, 1300)
        bar = rng.uniform(0.06, 0.12)
        fa = np.abs(((a_ + rng.uniform(0, pane)) / pane) % 1 - 0.5) * 2
        fb = np.abs(((b_ + rng.uniform(0, pane)) / (pane * 1.4)) % 1 - 0.5) * 2
        soft = 0.12
        win = np.clip((1 - bar - fa) / soft, 0, 1) * np.clip((1 - bar - fb) / soft, 0, 1)
        # 창문 밖으로 벗어난 영역은 그늘
        cx_, cy_ = rng.uniform(0.2, 0.8) * book.X, rng.uniform(0.2, 0.8) * PAGE_H
        reach = rng.uniform(1300, 2200)
        win *= np.clip(1.6 - np.hypot(xw - cx_, yw - cy_) / reach, 0, 1)
        shade *= 0.8 + 0.32 * win
        warm = np.stack([1 + 0.06 * win, 1 + 0.02 * win, 1 - 0.05 * win], -1)
    else:
        warm = 1.0

    # 종이가 미세하게 울어서 생기는 명암 변화
    wav = _smooth_noise(H_, W_, (H_ // 160, W_ // 160), rng)
    shade = np.where(on_top, shade * (0.97 + 0.06 * wav), shade)

    light_col = np.array([1.0, 0.97, 0.92]) if rng.random() < 0.6 else np.array([0.97, 0.98, 1.0])
    img = color * shade[..., None] * light_col * warm
    return img, t


def _depth_of_field(img, t, focus_t, strength):
    """거리(t)에 따라 흐림 정도를 다르게 (여러 단계 블러를 섞음)."""
    coc = np.abs(1 / t - 1 / focus_t) * focus_t * strength
    levels = [0, 1.2, 2.5, 4.5, 8.0]
    src = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    stack = [img] + [np.asarray(src.filter(ImageFilter.GaussianBlur(r)), np.float32) for r in levels[1:]]
    out = np.zeros_like(img)
    wsum = np.zeros(t.shape, np.float32)
    for i, r in enumerate(levels):
        lo = levels[i - 1] if i > 0 else r - 1
        hi = levels[i + 1] if i < len(levels) - 1 else r + 100
        w = np.where(coc <= r, np.clip((coc - lo) / max(r - lo, 1e-3), 0, 1),
                     np.clip((hi - coc) / max(hi - r, 1e-3), 0, 1))
        if i == 0:
            w = np.where(coc <= 0, 1, w)
        out += stack[i] * w[..., None]
        wsum += w
    return out / np.maximum(wsum, 1e-3)[..., None]


def _phone_postprocess(img, rng):
    h, w = img.shape[:2]
    # 화이트밸런스 & 노출
    wb = np.array([rng.uniform(1.0, 1.05), 1.0, rng.uniform(0.88, 0.97)], np.float32)
    img = img * wb * rng.uniform(1.0, 1.1)
    # 렌즈 비네팅
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((gx - w / 2) / (w / 2)) ** 2 + ((gy - h / 2) / (h / 2)) ** 2
    img *= (1 - 0.13 * r2)[..., None]
    # 톤커브 (폰 특유의 부드러운 S커브, 하이라이트 압축)
    x = np.clip(img / 255, 0, 1.2)
    x = x / (1 + 0.18 * x)
    x = x / (1 / 1.18)
    x = np.clip(x, 0, 1)
    x = x + 0.06 * np.sin(2 * math.pi * x) * (1 - x) * 0.8
    img = np.clip(x, 0, 1) * 255
    # 색수차: 가장자리에서 R/B 채널이 살짝 어긋남
    pil = Image.fromarray(img.astype(np.uint8))
    r, g, b = pil.split()
    s = 1.0015
    r = r.resize((int(w * s), int(h * s)), Image.BICUBIC).crop(
        ((int(w * s) - w) // 2, (int(h * s) - h) // 2, (int(w * s) - w) // 2 + w, (int(h * s) - h) // 2 + h))
    pil = Image.merge("RGB", (r, g, b))
    # 축소 + 폰 샤프닝
    pil = pil.resize((OUT_W, OUT_H), Image.LANCZOS)
    pil = pil.filter(ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=2))
    # 센서 노이즈 (어두운 곳일수록 많게) + 노이즈 제거로 뭉개진 질감
    arr = np.asarray(pil, np.float32)
    lum = arr.mean(-1, keepdims=True) / 255
    sigma = 1.6 + 3.0 * (1 - lum)
    noise = rng.normal(0, 1, (OUT_H, OUT_W, 1)) * sigma + rng.normal(0, 0.8, (OUT_H, OUT_W, 3))
    noise_img = Image.fromarray(np.clip(noise * 8 + 128, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    noise = (np.asarray(noise_img, np.float32) - 128) / 8
    arr = np.clip(arr + noise, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def render_photo(passage, out_path, seed=None, filler_text=None):
    """passage(dict) → 책 사진 JPEG 파일 생성. 경로를 반환합니다.

    filler_text: 왼쪽 페이지에 깔 글 (없으면 본문을 재사용)
    """
    ensure_fonts()
    if seed is None:
        seed = int(hashlib.md5(passage["id"].encode()).hexdigest()[:8], 16) + random.randint(0, 10_000)
    rng = np.random.default_rng(seed)

    tone = PAPER_TONES[rng.integers(len(PAPER_TONES))]
    page_no = int(rng.integers(17, 289)) | 1          # 오른쪽 페이지는 홀수
    filler = {"book": passage["book"], "author": passage["author"],
              "text": ((filler_text or passage["text"]).replace("\n", " ") + " ") * 4}
    _, back_ink = _typeset(filler, rng, page_no + 1, filler_mode=True)
    right_tex, right_ink = render_page(passage, rng, tone, page_no, back_ink=back_ink)
    left_tex, _ = render_page(filler, rng, tone, page_no - 1, back_ink=right_ink, filler_mode=True)

    W, H = int(OUT_W * SS), int(OUT_H * SS)
    book = Book(rng)
    cam, d, dist = _camera_rays(rng, book, W, H)
    t, hit = _march(book, cam, d)
    light = np.array([rng.uniform(-0.6, 0.6), rng.uniform(-0.7, -0.1), 1.0])
    img, t = _shade_scene(book, cam, d, t, hit, right_tex, left_tex, rng, light)

    focus_t = float(np.median(t[H // 2 - 20: H // 2 + 20, W // 2 - 20: W // 2 + 20]))
    img = _depth_of_field(img, t, focus_t, strength=rng.uniform(7, 13) * SS)
    photo = _phone_postprocess(img, rng)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    photo.save(out_path, "JPEG", quality=int(rng.integers(84, 92)))
    return out_path
