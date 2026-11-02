# -*- coding: utf-8 -*-
"""义乌思博尔色卡提取（第二版原图）：格线拟合 + 格内中位色 + 白平衡
用法：
  python tools/extract-pal.py fit     # 网格拟合，输出验证图到 tmp_pal/
  python tools/extract-pal.py build   # 生成 data/palette.json 与 assets/palette-seed.js
"""
import os, sys, json
import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'source-photos', 'pal-v2')
TMP = os.path.join(ROOT, 'tmp_pal')
os.makedirs(TMP, exist_ok=True)

PHOTOS = ['pal-%d' % i for i in range(1, 6)]
ROWS = 7          # 每页 7 行
COLS = 3          # 每页 3 列
PER_PAGE = ROWS * COLS          # 21
PER_PHOTO = PER_PAGE * 2        # 42

# 每页色号按「先列后行」排：第 1 列 1-7，第 2 列 8-14，第 3 列 15-21
def code_of(photo_idx, right, col, row):
    base = (photo_idx - 1) * PER_PHOTO + 1
    return base + (PER_PAGE if right else 0) + col * ROWS + row


def load(name):
    return np.array(Image.open(os.path.join(SRC, name + '.jpg')).convert('RGB')).astype(np.float32)


def smooth(p, k=7):
    return np.convolve(p, np.ones(k) / k, mode='same')


def paper_profiles(a):
    """纸面比例轮廓：格子缝、编号条、页边都是纸，布片不是。"""
    gray = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    p90 = float(np.percentile(gray, 90))
    m = ((gray > p90 - 32) & (sat < 26)).astype(np.float32)
    return smooth(m.mean(axis=0)), smooth(m.mean(axis=1))


def fit_lines(prof, start_rng, step_rng, n_lines):
    """在给定范围内搜 (起点, 步距)，使 n_lines 条格线处的纸面比例之和最大"""
    best = None
    for st in start_rng:
        for sp in step_rng:
            xs = [int(round(st + k * sp)) for k in range(n_lines)]
            if xs[0] < 2 or xs[-1] >= len(prof) - 2:
                continue
            s = float(sum(prof[x] for x in xs))
            if best is None or s > best[0]:
                best = (s, float(st), float(sp))
    if best is None:
        raise RuntimeError('lattice not found')
    return [best[1] + k * best[2] for k in range(n_lines)]


def fit_photo(name):
    a = load(name)
    h, w, _ = a.shape
    px, py = paper_profiles(a)
    ys = fit_lines(py, np.arange(50, 170, 1.0), np.arange(140, 185, 0.5), ROWS + 1)
    xs_l = fit_lines(px, np.arange(0, 120, 1.0), np.arange(270, 330, 0.5), COLS + 1)
    xs_r = fit_lines(px, np.arange(w * 0.47, w * 0.56, 1.0), np.arange(270, 330, 0.5), COLS + 1)
    return ys, xs_l, xs_r


# ---------------- 取色 ----------------
def srgb2lab(rgb):
    rgb = np.asarray(rgb, dtype=np.float64) / 255.0
    m = rgb > 0.04045
    rgb = np.where(m, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    M = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = rgb @ M.T
    wp = np.array([0.95047, 1.0, 1.08883])
    u = xyz / wp
    f = np.where(u > 0.008856, u ** (1 / 3), 7.787 * u + 16 / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def paper_white(a):
    px = a.reshape(-1, 3)
    gray = px.mean(axis=1)
    sat = px.max(axis=1) - px.min(axis=1)
    sel = (gray > np.percentile(gray, 80)) & (sat < 14)
    if sel.sum() < 500:
        sel = gray > np.percentile(gray, 95)
    return np.median(px[sel], axis=0)


def white_balance(a, target=242.0):
    w = paper_white(a)
    gain = np.clip(target / np.maximum(w, 1.0), 0.7, 1.8)
    return np.clip(a * gain, 0, 255), w, gain


def median_color(img, x0, y0, x1, y1):
    x0, x1 = int(max(0, x0)), int(min(img.shape[1], x1))
    y0, y1 = int(max(0, y0)), int(min(img.shape[0], y1))
    return np.median(img[y0:y1, x0:x1].reshape(-1, 3), axis=0)


def tex_energy(gray):
    k = gray.astype(np.float32)
    acc = np.zeros_like(k); acc2 = np.zeros_like(k)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            s = np.roll(np.roll(k, dy, 0), dx, 1)
            acc += s; acc2 += s * s
    mu = acc / 9
    return float(np.sqrt(np.maximum(acc2 / 9 - mu * mu, 0)).mean())


def paper_mask(a):
    gray = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    p90 = float(np.percentile(gray, 90))
    return (gray > p90 - 32) & (sat < 26)


def cell_bbox(raw, x0, y0, x1, y1):
    """找出格子中央那块布料自身的矩形。
    布片是手贴的，相对印刷格线上下左右会偏 20-30px，所以不能直接用格线裁。
    做法：以格心颜色为基准，沿列/行看中位色与基准的 Lab 距离，取与格心同色的一段。"""
    h, w, _ = raw.shape
    bw, bh = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    px0, px1 = int(cx - bw * 0.10), int(cx + bw * 0.10)
    py0, py1 = int(cy - bh * 0.10), int(cy + bh * 0.10)
    clab = srgb2lab(np.median(raw[py0:py1, px0:px1].reshape(-1, 3), axis=0))

    wx0, wx1 = int(max(0, x0 - bw * 0.20)), int(min(w, x1 + bw * 0.20))
    wy0, wy1 = int(max(0, y0 - bh * 0.20)), int(min(h, y1 + bh * 0.20))
    by0, by1 = int(cy - bh * 0.16), int(cy + bh * 0.16)
    bx0, bx1 = int(cx - bw * 0.16), int(cx + bw * 0.16)

    med_col = np.median(raw[by0:by1, wx0:wx1], axis=0)
    med_row = np.median(raw[wy0:wy1, bx0:bx1], axis=1)
    dcol = np.linalg.norm(srgb2lab(med_col) - clab, axis=1)
    drow = np.linalg.norm(srgb2lab(med_row) - clab, axis=1)
    dcol = np.convolve(dcol, np.ones(7) / 7, mode='same')
    drow = np.convolve(drow, np.ones(7) / 7, mode='same')

    def grow(d, center, offset, lo, hi, min_frac):
        for th in (7.0, 11.0, 15.0, 20.0):
            ok = d < th
            c = min(max(center - offset, 0), len(d) - 1)
            l = c
            while l > 0 and ok[l - 1]:
                l -= 1
            r = c
            while r < len(d) - 1 and ok[r + 1]:
                r += 1
            l += offset
            r += offset
            l = max(l, lo)
            r = min(r, hi)
            if r - l >= (hi - lo) * min_frac:
                return l, r
        return None

    gc = grow(dcol, (wx0 + wx1) // 2, wx0, x0, x1, 0.5)
    gr = grow(drow, (wy0 + wy1) // 2, wy0, y0, y1, 0.5)

    fx0, fy0 = x0 + bw * 0.09, y0 + bh * 0.07
    fx1, fy1 = x1 - bw * 0.02, y1 - bh * 0.07
    left = gc[0] if gc else fx0
    right = gc[1] if gc else fx1
    top = gr[0] if gr else fy0
    bottom = gr[1] if gr else fy1
    # 保底内缩，且限制在格内
    left = min(max(left, x0 + bw * 0.02), x1)
    right = max(min(right, x1), left + 10)
    top = min(max(top, y0 + bh * 0.01), y1)
    bottom = max(min(bottom, y1), top + 10)
    if right - left < bw * 0.45 or bottom - top < bh * 0.45:
        return int(fx0), int(fy0), int(fx1), int(fy1)
    return int(left) + 2, int(top) + 2, int(right) - 2, int(bottom) - 2


def build():
    items = []
    photos = []
    info = {}
    for pi, name in enumerate(PHOTOS, 1):
        raw = load(name)
        img, wref, gain = white_balance(raw)
        h, w, _ = raw.shape
        pmask = paper_mask(raw)
        ys, xs_l, xs_r = fit_photo(name)
        info[name] = dict(rows=[round(v, 1) for v in ys],
                          left=[round(v, 1) for v in xs_l],
                          right=[round(v, 1) for v in xs_r],
                          paper=wref.round(1).tolist(), gain=gain.round(3).tolist())
        photos.append('assets/pal-%d.jpg' % pi)
        ypitch = (ys[-1] - ys[0]) / ROWS
        for right, xs, base in ((False, xs_l, None), (True, xs_r, None)):
            xpitch = (xs[-1] - xs[0]) / COLS
            for c in range(COLS):
                for r in range(ROWS):
                    x0, x1 = xs[c], xs[c + 1]
                    y0, y1 = ys[r], ys[r + 1]
                    bx0, by0, bx1, by1 = cell_bbox(raw, x0, y0, x1, y1)
                    # 取色：裁切区中央 52%
                    cw, ch = bx1 - bx0, by1 - by0
                    cx0, cx1 = bx0 + cw * 0.24, bx1 - cw * 0.24
                    cy0, cy1 = by0 + ch * 0.24, by1 - ch * 0.24
                    col = median_color(raw, cx0, cy0, cx1, cy1) * gain
                    mx = float(col.max())
                    if mx > 255:            # 高饱和色别让单通道硬截断，整体等比压回，保住色相
                        col = col * (255.0 / mx)
                    col = np.clip(col, 0, 255)
                    d_paper = float(np.linalg.norm(srgb2lab(col) - srgb2lab(wref)))
                    te = tex_energy(raw.mean(axis=2)[int(cy0):int(cy1), int(cx0):int(cx1)])
                    items.append(dict(
                        code=code_of(pi, right, c, r),
                        page=pi,
                        rect=[round(bx0 / w, 5), round(by0 / h, 5),
                              round((bx1 - bx0) / w, 5), round((by1 - by0) / h, 5)],
                        rgb=[int(round(v)) for v in col],
                        _dE=round(d_paper, 1), _tex=round(te, 2),
                        _box=[int(bx0), int(by0), int(bx1), int(by1)],
                    ))
    return items, photos, info


def contact_sheet(items, path, cell=(150, 110), cols=9):
    pages = {}
    for it in items:
        pages.setdefault(it['page'], []).append(it)
    for pg, arr in sorted(pages.items()):
        raw = load(PHOTOS[pg - 1])
        nrow = (len(arr) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * cell[0], nrow * (cell[1] + 18)), (250, 250, 250))
        d = ImageDraw.Draw(sheet)
        for i, it in enumerate(arr):
            x0, y0, x1, y1 = it['_box']
            crop = Image.fromarray(raw[y0:y1, x0:x1].astype(np.uint8)).resize(cell)
            cx, cy = (i % cols) * cell[0], (i // cols) * (cell[1] + 18)
            sheet.paste(crop, (cx, cy))
            hexv = '#%02X%02X%02X' % tuple(it['rgb'])
            d.rectangle([cx, cy + cell[1], cx + cell[0], cy + cell[1] + 18], fill=(255, 255, 255))
            d.text((cx + 4, cy + cell[1] + 4), '%s %s' % (it['code'], hexv), fill=(0, 0, 0))
        out = path.replace('.jpg', '-p%d.jpg' % pg)
        sheet.save(out, quality=86)
        print('sheet', out)


def draw_grid(name, items, path):
    raw = load(name)
    im = Image.fromarray(raw.astype(np.uint8))
    d = ImageDraw.Draw(im)
    for it in items:
        if it['page'] != PHOTOS.index(name) + 1:
            continue
        d.rectangle(it['_box'], outline=(0, 255, 0), width=3)
    im.resize((im.width // 2, im.height // 2)).save(path, quality=90)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'fit'
    if mode == 'fit':
        for name in PHOTOS:
            ys, xl, xr = fit_photo(name)
            print(name, 'rows', [round(v) for v in ys])
            print('   L', [round(v) for v in xl], ' R', [round(v) for v in xr])
        return

    items, photos, info = build()
    items.sort(key=lambda i: i['code'])
    print('items', len(items), 'codes', items[0]['code'], '-', items[-1]['code'])
    codes = [it['code'] for it in items]
    print('缺号', [c for c in range(1, 211) if c not in codes])
    print('格线', json.dumps(info, ensure_ascii=False))
    # 空位/异常检查
    sus = [it for it in items if it['_tex'] < 0.6]
    print('低纹理格', [(it['code'], it['_tex']) for it in sus])
    if mode == 'probe':
        contact_sheet(items, os.path.join(TMP, 'sheet.jpg'))
        for name in PHOTOS:
            draw_grid(name, items, os.path.join(TMP, 'grid-%s.jpg' % name))
        return

    data = dict(
        name='义乌思博尔色卡',
        brand='思博尔',
        note='实物色卡拍照提取：色块图片直接取自照片，色值取该格中位色并做了轻微白平衡校正。',
        photos=photos,
        items=[dict(code=it['code'], page=it['page'], rgb=it['rgb'], rect=it['rect']) for it in items],
    )
    with open(os.path.join(ROOT, 'data', 'palette.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    seed = '/* 由 data/palette.json 生成，供直接双击打开（无后端）时使用 */\nwindow.PALETTE_SEED=' + \
           json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
    with open(os.path.join(ROOT, 'assets', 'palette-seed.js'), 'w', encoding='utf-8') as f:
        f.write(seed)
    # 显示用图片（1100 宽，与另外两套一致）：与色值走同一套白平衡，保证「看到的」= 存的色值
    for pi, name in enumerate(PHOTOS, 1):
        raw = load(name)
        img, _, _ = white_balance(raw)
        im = Image.fromarray(img.astype(np.uint8))
        im = im.resize((1100, round(im.height * 1100 / im.width)), Image.LANCZOS)
        im.save(os.path.join(ROOT, 'assets', 'pal-%d.jpg' % pi), quality=88)
    print('written data/palette.json, assets/palette-seed.js, assets/pal-1..5.jpg')


if __name__ == '__main__':
    main()
