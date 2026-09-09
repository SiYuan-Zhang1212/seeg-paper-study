#!/usr/bin/env python3
"""Inspect an author code repository without choking on GBK-encoded MATLAB files.

Usage
-----
python3 repo_scan.py REPO                        # 结构树 + 文件大小/行数/编码
python3 repo_scan.py REPO --readme               # 打印所有 README
python3 repo_scan.py REPO --grep "baseline"      # 全仓搜索（自动解码 GBK/UTF-8）
python3 repo_scan.py REPO --show Code/TF/TF_2_prac.m
python3 repo_scan.py REPO --ext .m,.py --grep "zscore|z-score" -i
python3 repo_scan.py REPO --git                  # remote + commit + 最近提交

Why: 作者共享的 MATLAB 脚本常常是 GBK/GB2312，直接 grep 会静默返回空结果。
本脚本按 utf-8 -> gbk -> latin-1 顺序解码，并标出实际编码。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".ipynb_checkpoints",
    ".idea",
    ".vscode",
    ".DS_Store",
}
TEXT_EXT = {
    ".m", ".py", ".r", ".rmd", ".ipynb", ".md", ".txt", ".csv", ".tsv", ".json",
    ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh", ".c", ".cpp", ".h", ".java",
    ".js", ".ts", ".html", ".xml", ".rst", ".tex", ".asv", ".mlx", ".mex",
}


def decode_bytes(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def walk(root: str, exts: set[str] | None = None):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name == ".DS_Store":
                continue
            path = os.path.join(dirpath, name)
            if exts and os.path.splitext(name)[1].lower() not in exts:
                continue
            yield path


def rel(root: str, path: str) -> str:
    return os.path.relpath(path, root)


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return "%d%s" % (n, unit) if unit == "B" else "%.0f%s" % (n, unit)
        n /= 1024.0
    return str(n)


def count_lines(path: str) -> tuple[int | None, str]:
    try:
        raw = open(path, "rb").read()
    except OSError:
        return None, "?"
    text, enc = decode_bytes(raw)
    return text.count("\n") + (0 if text.endswith("\n") else 1), enc


def cmd_tree(root: str, exts: set[str] | None) -> None:
    print("=== 文件清单 (root=%s) ===" % root)
    n = 0
    for path in walk(root, exts):
        size = os.path.getsize(path)
        if os.path.splitext(path)[1].lower() in TEXT_EXT:
            lines, enc = count_lines(path)
            enc_tag = "" if enc == "utf-8" else "  [%s]" % enc
            print("  %-72s %6s %6s行%s" % (rel(root, path), human(size), lines, enc_tag))
        else:
            print("  %-72s %6s" % (rel(root, path), human(size)))
        n += 1
    print("共 %d 个文件" % n)


def cmd_readme(root: str) -> None:
    found = False
    for path in walk(root):
        base = os.path.basename(path).lower()
        if base.startswith("readme") or base.startswith("acknowledg"):
            found = True
            raw = open(path, "rb").read()
            text, enc = decode_bytes(raw)
            print("\n===== %s  [%s] =====" % (rel(root, path), enc))
            print(text[:12000])
    if not found:
        print("(没有 README / ACKNOWLEDGMENT)")


def cmd_grep(root: str, pattern: str, ignore_case: bool, exts: set[str] | None, context: int) -> None:
    flags = re.IGNORECASE if ignore_case else 0
    rx = re.compile(pattern, flags)
    hits = 0
    for path in walk(root, exts):
        if os.path.splitext(path)[1].lower() not in TEXT_EXT:
            continue
        try:
            raw = open(path, "rb").read()
        except OSError:
            continue
        text, enc = decode_bytes(raw)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if rx.search(line):
                hits += 1
                print("%s:%d  %s" % (rel(root, path), i + 1, line.strip()[:240]))
                if context:
                    for j in range(max(0, i - context), min(len(lines), i + context + 1)):
                        if j != i:
                            print("    %s" % lines[j].strip()[:240])
    print("\n命中 %d 行" % hits)
    if hits == 0:
        print("提示：换更短的关键词；MATLAB 变量名常是缩写（如 bl、base、zsc）。")


def cmd_show(root: str, target: str, head: int | None) -> None:
    path = target if os.path.isabs(target) else os.path.join(root, target)
    if not os.path.exists(path):
        print("找不到文件: %s" % path, file=sys.stderr)
        return
    text, enc = decode_bytes(open(path, "rb").read())
    lines = text.splitlines()
    print("===== %s  [%s] %d 行 =====" % (target, enc, len(lines)))
    for i, line in enumerate(lines[: head or len(lines)], 1):
        print("%5d  %s" % (i, line))


def cmd_git(root: str) -> None:
    def run(*cmd: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", root, *cmd], capture_output=True, text=True, timeout=20
            ).stdout.strip()
        except Exception as exc:  # noqa: BLE001
            return "(失败: %s)" % exc

    remote = run("remote", "-v")
    print("=== git 信息 ===")
    print(remote or "(不是 git 仓库：说明代码可能是下载的压缩包，不是 clone)")
    print("commit :", run("rev-parse", "HEAD"))
    print("分支   :", run("rev-parse", "--abbrev-ref", "HEAD"))
    print("最近提交:")
    print(run("log", "-3", "--date=short", "--format=%h %ad %s"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo")
    parser.add_argument("--readme", action="store_true", help="打印 README")
    parser.add_argument("--grep", default=None, help="正则搜索文件内容")
    parser.add_argument("-i", "--ignore-case", action="store_true")
    parser.add_argument("--context", type=int, default=0, help="grep 上下文行数")
    parser.add_argument("--show", default=None, help="打印某个文件（相对 repo 路径）")
    parser.add_argument("--ext", default=None, help="只看这些扩展名，如 .m,.py")
    parser.add_argument("--git", action="store_true", help="打印 git remote / commit")
    args = parser.parse_args()

    root = os.path.abspath(args.repo)
    if not os.path.isdir(root):
        print("不是目录: %s" % root, file=sys.stderr)
        return 2
    exts = (
        {e if e.startswith(".") else "." + e for e in re.split(r"[,\s]+", args.ext.strip())}
        if args.ext
        else None
    )

    did = False
    if args.git:
        cmd_git(root)
        did = True
    if args.readme:
        cmd_readme(root)
        did = True
    if args.grep:
        cmd_grep(root, args.grep, args.ignore_case, exts, args.context)
        did = True
    if args.show:
        cmd_show(root, args.show, None)
        did = True
    if not did:
        cmd_tree(root, exts)
        print("\n下一步：--readme 看说明，--grep 找参数，--show 精读某个文件，--git 记录版本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
