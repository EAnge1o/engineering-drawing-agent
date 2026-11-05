"""按赛事命名规范打包交付 zip。

用法：
  python backend/scripts/make_package.py --team "队伍名" --contact "联系方式"
默认输出到 dist/，文件名：作品名+队伍名+版本号+联系方式.zip
"""
from __future__ import annotations

import argparse
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "outputs", "uploads", ".git", ".vite"}
EXCLUDE_FILES = {"agent.db"}


def add_tree(zf: zipfile.ZipFile, src: str, prefix: str) -> int:
    count = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f in EXCLUDE_FILES or f.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(root, f)
            rel = os.path.join(prefix, os.path.relpath(full, src))
            zf.write(full, rel)
            count += 1
    return count


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="工程图纸建模与自纠错Agent")
    ap.add_argument("--team", default="TEAM")
    ap.add_argument("--version", default="v0.1.0")
    ap.add_argument("--contact", default="contact")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    filename = f"{args.name}+{args.team}+{args.version}+{args.contact}.zip"
    path = os.path.join(args.out, filename)

    total = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder in ["ppt", "video", "codearts_proof", "readme"]:
            src = os.path.join(ROOT, folder)
            if os.path.isdir(src):
                total += add_tree(zf, src, folder)

        # project/ = 可运行 Demo
        for folder in ["backend", "frontend", "samples"]:
            src = os.path.join(ROOT, folder)
            if os.path.isdir(src):
                total += add_tree(zf, src, os.path.join("project", folder))

        for fname in ["PRD.md", "README.md", "research-log-2026-10-28.md"]:
            full = os.path.join(ROOT, fname)
            if os.path.isfile(full):
                zf.write(full, os.path.join("project", fname))
                total += 1

    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"已打包 {total} 个文件 -> {path}")
    print(f"大小 {size_mb:.1f} MB  命名：{filename}")


if __name__ == "__main__":
    main()