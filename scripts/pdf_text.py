#!/usr/bin/env python3
"""Read a paper PDF: per-page text, keyword search, and page rendering for figures.

Usage
-----
python3 pdf_text.py PAPER.pdf                      # 全文文本，带页码分隔
python3 pdf_text.py PAPER.pdf --pages 1-3,7        # 只读指定页
python3 pdf_text.py PAPER.pdf --grep "baseline|z-score" -i
python3 pdf_text.py PAPER.pdf --render 1,2,5 --dpi 200 --outdir /tmp/figs
python3 pdf_text.py PAPER.pdf --info               # 元数据 + 页数

Why render: 任务时间轴、电极位置图、示意图里的信息往往只有看图才能拿到；
PDF 文字层经常丢失或乱序，关键图必须渲染成 PNG 再看。

Requires: PyMuPDF (python3 -m pip install pymupdf)
"""

from __future__ import annotations

import argparse
import os
import re
import sys


def parse_ranges(spec: str, page_count: int) -> list[int]:
    """'1-3,7' -> [0,1,2,6] (0-based, 已裁剪到合法范围)"""
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            rng = range(int(start), int(end) + 1)
        else:
            rng = range(int(part), int(part) + 1)
        for p in rng:
            idx = p - 1
            if 0 <= idx < page_count and idx not in pages:
                pages.append(idx)
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("pdf")
    parser.add_argument("--pages", default=None, help="页码，如 1-3,7（默认全部）")
    parser.add_argument("--grep", default=None, help="正则搜索，只打印命中行")
    parser.add_argument("-i", "--ignore-case", action="store_true", help="--grep 忽略大小写")
    parser.add_argument("--context", type=int, default=0, help="--grep 前后各多打印几行")
    parser.add_argument("--render", default=None, help="要渲染成 PNG 的页码，如 1,2,5")
    parser.add_argument("--dpi", type=int, default=180, help="渲染 DPI（默认 180）")
    parser.add_argument("--outdir", default="/tmp/seeg-paper-figs", help="PNG 输出目录")
    parser.add_argument("--info", action="store_true", help="只打印元数据")
    args = parser.parse_args()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("缺少 PyMuPDF。安装：python3 -m pip install pymupdf", file=sys.stderr)
        return 2

    doc = fitz.open(args.pdf)
    print("文件   : %s" % args.pdf)
    print("页数   : %d" % doc.page_count)
    meta = doc.metadata or {}
    for key in ("title", "author", "subject", "creationDate"):
        if meta.get(key):
            print("%-7s: %s" % (key, " ".join(str(meta[key]).split())[:200]))
    if args.info:
        return 0

    if args.render:
        os.makedirs(args.outdir, exist_ok=True)
        for idx in parse_ranges(args.render, doc.page_count):
            pix = doc[idx].get_pixmap(dpi=args.dpi)
            path = os.path.join(
                args.outdir, "%s-p%02d.png" % (os.path.splitext(os.path.basename(args.pdf))[0][:40], idx + 1)
            )
            pix.save(path)
            print("渲染 -> %s  (%dx%d)" % (path, pix.width, pix.height))
        if not args.grep and not args.pages:
            return 0

    pages = parse_ranges(args.pages, doc.page_count) if args.pages else list(range(doc.page_count))
    flags = re.IGNORECASE if args.ignore_case else 0
    pattern = re.compile(args.grep, flags) if args.grep else None

    total_hits = 0
    for idx in pages:
        text = doc[idx].get_text("text")
        lines = text.splitlines()
        if pattern:
            for i, line in enumerate(lines):
                if pattern.search(line):
                    total_hits += 1
                    lo = max(0, i - args.context)
                    hi = min(len(lines), i + args.context + 1)
                    print("\n--- p%d ---" % (idx + 1))
                    for j in range(lo, hi):
                        marker = ">>" if j == i else "  "
                        print("%s %s" % (marker, lines[j]))
        else:
            print("\n===== PAGE %d/%d =====" % (idx + 1, doc.page_count))
            print(text)

    if pattern:
        print("\n命中 %d 行（%d 页）" % (total_hits, len(pages)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
