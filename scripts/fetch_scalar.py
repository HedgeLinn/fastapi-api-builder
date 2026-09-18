# -*- coding: utf-8 -*-
"""下载 Scalar 自托管脚本，并记录版本与哈希。

为什么需要：内网机器出不去外网，Scalar 脚本必须放在本地、由服务自己发出去。

用法::

    python scripts/fetch_scalar.py                    # 下到 templates/docs/static/scalar.js
    python scripts/fetch_scalar.py --out D:/x/static  # 下到别处
    python scripts/fetch_scalar.py --version 1.69.0   # 锁定版本
    python scripts/fetch_scalar.py --check            # 只校验已有文件，不下载

只依赖标准库，不装任何东西。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "templates" / "docs" / "static"
LATEST = "https://cdn.jsdelivr.net/npm/@scalar/api-reference"


def url_for(version: str | None) -> str:
    if not version or version == "latest":
        return LATEST
    return f"https://cdn.jsdelivr.net/npm/@scalar/api-reference@{version}"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录（默认 templates/docs/static）")
    ap.add_argument("--version", default=None, help="锁定版本，例如 1.69.0；默认取最新")
    ap.add_argument("--check", action="store_true", help="只校验已有文件，不下载")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "scalar.js"
    meta_file = out_dir / "scalar.version.json"

    if args.check:
        if not target.is_file():
            print(f"[X] 不存在：{target}")
            return 1
        digest = sha256_of(target)
        size = target.stat().st_size
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
        ok = (not meta.get("sha256")) or meta["sha256"] == digest
        print(f"{'[OK]' if ok else '[X]'} {target}")
        print(f"     {size:,} 字节  SHA256 {digest}")
        if meta.get("version"):
            print(f"     记录版本 {meta['version']}"
                  + ("" if ok else f"（哈希不符，期望 {meta['sha256']}）"))
        return 0 if ok else 1

    url = url_for(args.version)
    print(f"下载 {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
    except Exception as exc:  # noqa: BLE001
        print(f"[X] 下载失败：{exc}")
        print("    这台机器可能没有外网。找一台有外网的机器下载后，把 scalar.js 拷过来即可。")
        return 1

    target.write_bytes(data)
    digest = sha256_of(target)
    meta = {
        "package": "@scalar/api-reference",
        "version": args.version or "(latest)",
        "url": url,
        "size": len(data),
        "sha256": digest,
    }
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] {target}")
    print(f"     {len(data):,} 字节  SHA256 {digest}")
    print(f"     版本记录写入 {meta_file.name}")
    print()
    print("别忘了：把 static/scalar.js 一起放到目标服务的目录下，"
          "否则内网打开 /docs 会白屏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())