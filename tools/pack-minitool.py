#!/usr/bin/env python3
"""把 dist/ 打成可上传的小工具 zip。

平台要求：条目名不能含 ".."、不能以 "/" 开头、不能用 "\" 分隔，
且所有文件放在 zip 根目录（不建子目录）。dist/ 本身已是平铺结构，
这里只按文件名写入，并逐条校验后再压缩。
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(ROOT, "nunu-pattern-tool.zip")

ALLOWED_EXT = {".html", ".css", ".js", ".png", ".jpg", ".jpeg",
               ".gif", ".webp", ".svg", ".woff", ".woff2", ".json"}

if not os.path.isdir(DIST):
    sys.exit("dist/ 不存在，先运行 node tools/build-minitool.js")

entries = []
for name in sorted(os.listdir(DIST)):
    p = os.path.join(DIST, name)
    if not os.path.isfile(p):
        continue
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        print("  跳过（不支持的类型）:", name)
        continue
    # 平台路径校验
    assert ".." not in name, "含 ..: " + name
    assert not name.startswith("/"), "以 / 开头: " + name
    assert "\\" not in name and "/" not in name, "含分隔符: " + name
    entries.append((p, name))

if not os.path.exists(os.path.join(DIST, "index.html")):
    sys.exit("缺少 index.html")

if os.path.exists(OUT):
    os.remove(OUT)

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p, name in entries:
        z.write(p, name)

size = os.path.getsize(OUT)
print("打包完成:", OUT)
print("  条目数:", len(entries), "| 大小: %.2f MB" % (size / 1048576))
print("  根目录文件:", ", ".join(n for _, n in entries if not n.endswith(".jpg")))
print("  照片: %d 张" % sum(1 for _, n in entries if n.endswith(".jpg")))
if size > 10 * 1048576:
    sys.exit("ERROR: 超过 10MB 上传上限")
if size > 2 * 1048576:
    print("  WARN: 超过建议的 2MB")
