# -*- coding: utf-8 -*-
"""
鑫鸿布业色卡提取：网格拟合 + 格内中位色 + 白平衡 + 种子文件生成
用法：
  python tools/extract-xh.py fit     # 网格拟合，输出验证图到 tmp_xh/
  python tools/extract-xh.py build   # 生成 data/palette3.json 与 assets/palette-seed3.js
"""
import os, sys, json
import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'source-photos', 'xh')
TMP = os.path.join(ROOT, 'tmp_xh')
os.makedirs(TMP, exist_ok=True)

ROWS = 6
# 拟合得到的格线（像素坐标，原始 1920 宽照片）
GRID = {
    # 照片: (行边界 7 条, 左页 4 条, 右页 4 条)
    'xh-1': ([15, 216, 417, 618, 819, 1020, 1221],
             [36, 359, 682, 1005], [997, 1297.5, 1598, 1898.5]),
    'xh-2': ([9, 217, 425, 633, 841, 1049, 1257],
             [3, 311.5, 620, 928.5], [992, 1295.5, 1599, 1902.5]),
    'xh-3': ([14, 217, 420, 623, 826, 1029, 1232],
             [26, 327, 628, 929], [997, 1304.5, 1612, 1919.5]),
}
# 照片 -> (page 序号, 左页起始色号, 右页起始色号)
PAGE_OF = {'xh-1': (1, 1, 19), 'xh-2': (2, 37, 55), 'xh-3': (3, 73, 91)}

# 第 4 张是手贴色块，无印刷格线，按实测边界标定（行按色块边缘取平均）
XH4_ROWS = [(0, 475), (660, 1006)]
XH4_COLS = [
    [20, 438, 819, 1227, 1588, 1911],   # 第一行 5 块
    [10, 388, 765, 1177, 1554, 1900],   # 第二行 5 块
]
XH4_CODES = [[109, 113, 118, 121, 140], [151, 152, 158, 160, 162]]


def load(name):
    a = np.array(Image.open(os.path.join(SRC, name + '.jpg')).convert('RGB')).astype(np.float32)
    return a


def smooth(p, k=5):
    if k <= 1:
        return p
    return np.convolve(p, np.ones(k) / k, mode='same')


def edge_profiles(a):
    ev = np.abs(np.diff(a, axis=1)).mean(axis=2)
    eh = np.abs(np.diff(a, axis=0)).mean(axis=2)
    return smooth(np.percentile(ev, 75, axis=0)), smooth(np.percentile(eh, 75, axis=1))


def best_lattice(prof, start_rng, step_rng, n_cells, edge_margin=3, n_lines=None):
    if n_lines is None:
        n_lines = n_cells + 1
    best = None
    for st in start_rng:
        for sp in step_rng:
            s, ok = 0.0, True
            for k in range(n_lines):
                x = int(round(st + k * sp))
                if x < edge_margin or x >= len(prof) - edge_margin:
                    ok = False
                    break
                s += prof[x]
            if ok and (best is None or s > best[0]):
                best = (s, float(st), float(sp))
    return best


def fit_photo(name):
    a = load(name)
    h, w, _ = a.shape
    pv, ph = edge_profiles(a)
    rows = best_lattice(ph, np.arange(0, 80, 1.0), np.arange(180, 230, 0.5), ROWS)
    cols_l = best_lattice(pv, np.arange(0, 90, 1.0), np.arange(290, 331, 0.5), 3, n_lines=3)
    cols_r = best_lattice(pv, np.arange(w / 2 - 60, w / 2 + 90, 1.0), np.arange(290, 331, 0.5), 3, n_lines=3)
    return rows, cols_l, cols_r


def lattice(best, n):
    _, st, sp = best
    return [st + k * sp for k in range(n + 1)]


# ---------------- 取色 ----------------
def srgb2lab_arr(rgb):
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
    """纸白参考：高亮度、低饱和像素的中位色"""
    px = a.reshape(-1, 3)
    gray = px.mean(axis=1)
    sat = px.max(axis=1) - px.min(axis=1)
    sel = (gray > np.percentile(gray, 80)) & (sat < 14)
    if sel.sum() < 500:
        sel = gray > np.percentile(gray, 95)
    return np.median(px[sel], axis=0)


def white_balance(a, target=242.0):
    w = paper_white(a)
    # 单通道对角缩放，把纸白拉到统一基准；限制单通道增益防过冲
    gain = np.clip(target / np.maximum(w, 1.0), 0.7, 1.8)
    return np.clip(a * gain, 0, 255), w, gain


def median_color(img, x0, y0, x1, y1):
    x0, x1 = int(max(0, x0)), int(min(img.shape[1], x1))
    y0, y1 = int(max(0, y0)), int(min(img.shape[0], y1))
    patch = img[y0:y1, x0:x1].reshape(-1, 3)
    # 每通道取中位，抗标签/缝线/暗角
    return np.median(patch, axis=0)


def patch_std(img, x0, y0, x1, y1):
    x0, x1 = int(max(0, x0)), int(min(img.shape[1], x1))
    y0, y1 = int(max(0, y0)), int(min(img.shape[0], y1))
    patch = img[y0:y1, x0:x1].reshape(-1, 3)
    return float(patch.std(axis=0).mean())


def tex_energy(gray):
    """3x3 局部标准差均值：布料有毛绒纹理，纸面平整，用它区分空位"""
    k = gray.astype(np.float32)
    acc = np.zeros_like(k)
    acc2 = np.zeros_like(k)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            s = np.roll(np.roll(k, dy, 0), dx, 1)
            acc += s
            acc2 += s * s
    mu = acc / 9
    var = np.maximum(acc2 / 9 - mu * mu, 0)
    return float(np.sqrt(var).mean())


def is_paper_col(raw, x, y0, y1):
    """判断某一列是不是纸（编号条/白缝）：低饱和 + 偏亮"""
    seg = raw[y0:y1, max(0, x - 1):x + 2].reshape(-1, 3)
    med = np.median(seg, axis=0)
    sat = float(med.max() - med.min())
    gray = float(med.mean())
    return sat < 24 and gray > 145


def build_rect(raw, gx0, gy0, gx1, gy1, page):
    """显示用 rect：左右各自向内找到布料边沿（印刷编号条有的在布片左侧、有的在右侧，
    统一靠「纸面判定」跳过）。浅色布片会被判成纸、两侧都找不到时，退回固定内缩。"""
    h, w, _ = raw.shape
    gx0, gx1 = max(0, int(gx0)), min(w, int(gx1))
    gy0, gy1 = max(0, int(gy0)), min(h, int(gy1))
    bw, bh = gx1 - gx0, gy1 - gy0
    if page == 4:                       # 手贴色块，本身就是布片边界
        return gx0, gy0, gx1, gy1
    top = int(gy0 + bh * 0.03)
    bottom = int(gy1 - bh * 0.03)
    yy0, yy1 = int(gy0 + bh * 0.20), int(gy1 - bh * 0.20)

    def find(seq):
        run = 0
        for xx in seq:
            if is_paper_col(raw, xx, yy0, yy1):
                run = 0
            else:
                run += 1
                if run >= 40:      # 阈值要高于印刷数字的宽度（约 30px），又远小于布片宽度
                    return xx
        return None

    first = find(range(gx0, int(gx0 + bw * 0.45)))
    last = find(range(gx1 - 1, int(gx1 - bw * 0.45), -1))
    if first is None or last is None:
        return int(gx0 + bw * 0.05), top, int(gx1 - bw * 0.03), bottom
    left = max(gx0, first - 39)
    right = min(gx1, last + 39)
    if right - left < bw * 0.55:
        return int(gx0 + bw * 0.05), top, int(gx1 - bw * 0.03), bottom
    return left, top, right, bottom


def build():
    items = []
    photos = []
    white_ref = {}
    cache = {}
    page_idx = 0
    for name in ['xh-1', 'xh-2', 'xh-3', 'xh-4']:
        page_idx += 1
        photos.append('assets/xh-%d.jpg' % page_idx)
        raw = load(name)
        img, wref, gain = white_balance(raw)
        white_ref[name] = dict(white=wref.round(1).tolist(), gain=gain.round(3).tolist())
        cache[page_idx] = (raw, img)
        h, wpx, _ = raw.shape

        if name in GRID:
            ys, xl, xr = GRID[name]
            _, base_l, base_r = PAGE_OF[name]
            for xs, base in ((xl, base_l), (xr, base_r)):
                for c in range(len(xs) - 1):
                    for r in range(ROWS):
                        x0, x1 = xs[c], xs[c + 1]
                        y0, y1 = ys[r], ys[r + 1]
                        items.append(dict(code=base + c * ROWS + r, page=page_idx, box=(x0, y0, x1, y1)))
        else:
            for row_i, ((y0, y1), xs) in enumerate(zip(XH4_ROWS, XH4_COLS)):
                for c in range(len(xs) - 1):
                    items.append(dict(code=XH4_CODES[row_i][c], page=page_idx, box=(xs[c], y0, xs[c + 1], y1)))

    out = []
    skipped = []
    for it in items:
        raw, img = cache[it['page']]
        gx0, gy0, gx1, gy1 = it['box']
        # 取色区域固定取格子中央：避开左侧印刷编号条和边缘串色，与 rect 精修无关
        bw, bh = gx1 - gx0, gy1 - gy0
        lo, hi = (0.15, 0.85) if it['page'] == 4 else (0.28, 0.72)
        vlo, vhi = (0.15, 0.85) if it['page'] == 4 else (0.24, 0.76)
        cx0, cx1 = gx0 + bw * lo, gx0 + bw * hi
        cy0, cy1 = gy0 + bh * vlo, gy0 + bh * vhi
        col = median_color(img, cx0, cy0, cx1, cy1)
        d = float(np.linalg.norm(srgb2lab_arr(col) - srgb2lab_arr(paper_white(raw))))
        te = tex_energy(raw.mean(axis=2)[int(cy0):int(cy1), int(cx0):int(cx1)])
        if te < 0.75 and d < 30:      # 纸面平整且接近纸白 = 该格没贴布片
            skipped.append((it['code'], it['page'], round(d, 1), round(te, 2)))
            continue
        # 显示用 rect：切掉左侧印刷编号条，统一内缩，跨页不串格
        x0, y0, x1, y1 = build_rect(raw, gx0, gy0, gx1, gy1, it['page'])
        h, wpx, _ = raw.shape
        it['rect'] = [x0 / wpx, y0 / h, (x1 - x0) / wpx, (y1 - y0) / h]
        it['rgb'] = [int(round(v)) for v in col]
        it['_tex'] = round(te, 2)
        out.append(it)

    print('空位格（未录入）:', skipped)
    return out, photos, white_ref


def write_outputs(items, photos, white_ref):
    items.sort(key=lambda it: it['code'])
    data = dict(
        name='鑫鸿布业色卡',
        brand='鑫鸿布业',
        note='实物色卡拍照提取：%d 个色号，色块图直接取自照片，取格内中位色并按色卡纸白做白平衡。'
             '第 4 张为手贴零散色块，编号 109–162 仅覆盖照片上出现的色号。' % len(items),
        photos=photos,
        items=[dict(code=it['code'], page=it['page'], rgb=it['rgb'],
                    rect=[round(v, 5) for v in it['rect']]) for it in items])
    jp = os.path.join(ROOT, 'data', 'palette3.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    seed = '/* 由 data/palette3.json 生成，供直接双击打开（无后端）时使用 */\nwindow.PALETTE_SEED3=' + \
           json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
    sp = os.path.join(ROOT, 'assets', 'palette-seed3.js')
    with open(sp, 'w', encoding='utf-8') as f:
        f.write(seed)
    print('写入', jp, os.path.getsize(jp), 'bytes')
    print('写入', sp, os.path.getsize(sp), 'bytes')
    print('色号数', len(items), '范围', items[0]['code'], '-', items[-1]['code'])
    return data


def export_photos(src_name, dst_path, width=1100, quality=84):
    im = Image.open(os.path.join(SRC, src_name + '.jpg')).convert('RGB')
    if im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(dst_path, quality=quality, optimize=True, progressive=True)
    return os.path.getsize(dst_path)


def contact_sheet(items, path, cell=(150, 100)):
    """把每格裁出的图拼成一张表，用于肉眼核对 rect 有没有切歪"""
    pages = {}
    for it in items:
        pages.setdefault(it['page'], []).append(it)
    for pg in sorted(pages):
        raw = load(['xh-1', 'xh-2', 'xh-3', 'xh-4'][pg - 1])
        hgt, wpx, _ = raw.shape
        arr = pages[pg]
        cols = 7 if len(arr) > 12 else 5
        nrow = (len(arr) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * cell[0], nrow * (cell[1] + 18)), (250, 250, 250))
        d = ImageDraw.Draw(sheet)
        for i, it in enumerate(arr):
            x, y, w, hh = it['rect']
            x0, y0, x1, y1 = x * wpx, y * hgt, (x + w) * wpx, (y + hh) * hgt
            crop = Image.fromarray(raw[int(y0):int(y1), int(x0):int(x1)].astype(np.uint8))
            crop = crop.resize(cell)
            cx, cy = (i % cols) * cell[0], (i // cols) * (cell[1] + 18)
            sheet.paste(crop, (cx, cy))
            hexv = '#%02X%02X%02X' % tuple(it['rgb'])
            d.rectangle([cx, cy + cell[1], cx + cell[0], cy + cell[1] + 18], fill=(255, 255, 255))
            d.text((cx + 4, cy + cell[1] + 3), '%s %s' % (it['code'], hexv), fill=(0, 0, 0))
        out = path.replace('.jpg', '-p%d.jpg' % pg)
        sheet.save(out, quality=85)
        print('sheet', out)


def report(items):
    print('色号数', len(items))
    for it in items[:4] + items[-4:]:
        print(' ', it['code'], it['rgb'], '#%02X%02X%02X' % tuple(it['rgb']), 'tex', it['_tex'])


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'fit'
    if mode == 'fit':
        for name in GRID:
            rows, cl, cr = fit_photo(name)
            print(name, 'rows', [round(v, 1) for v in lattice(rows, ROWS)],
                  'L', [round(v, 1) for v in lattice(cl, 3)],
                  'R', [round(v, 1) for v in lattice(cr, 3)])
    else:
        items, photos, wref = build()
        report(items)
        print('white ref', wref)
        contact_sheet(items, os.path.join(TMP, 'sheet.jpg'))
        if mode == 'build':
            for i, n in enumerate(['xh-1', 'xh-2', 'xh-3', 'xh-4'], 1):
                sz = export_photos(n, os.path.join(ROOT, 'assets', 'xh-%d.jpg' % i))
                print('photo assets/xh-%d.jpg' % i, sz, 'bytes')
            write_outputs(items, photos, wref)
