# -*- coding: utf-8 -*-
"""拉取目标服务的 openapi.json，存快照，并做两件事：

  1. **体检** —— 列出 /docs 里缺什么：哪些接口没说明、哪些参数没说明、哪些响应是空壳
  2. **diff** —— 和上次快照比，后端改了什么

只依赖标准库，不装任何东西。

用法::

    python scripts/fetch_schema.py --url http://127.0.0.1:80xx
    python scripts/fetch_schema.py --file ./openapi.json          # 从本地文件读
    python scripts/fetch_schema.py --url ... --out data/openapi.snapshot.json
    python scripts/fetch_schema.py --url ... --check-only         # 只体检，不写快照

为什么需要它：换渲染器解决不了"说明缺失"，那是内容问题。这个脚本让内容问题
一眼可见 —— 这是手册 01「内容补全流程」的第 ① 步。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "data" / "openapi.snapshot.json"

METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


# ------------------------------------------------------------------ 读取
def load_from_url(url: str) -> dict:
    url = url.rstrip("/")
    if not url.endswith("/openapi.json"):
        url += "/openapi.json"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load_from_file(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 体检
def check(spec: dict) -> dict:
    """把 /docs 里"看得见什么"统计出来。"""
    paths = spec.get("paths", {})
    report = {
        "ops": 0, "no_summary": [], "no_desc": [],
        "params": 0, "params_no_desc": [],
        "ok_resp_empty": [],
        "no_tags": [],
        "title": spec.get("info", {}).get("title", "(无标题)"),
    }
    for path, item in paths.items():
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            report["ops"] += 1
            key = f"{method.upper()} {path}"

            if not op.get("summary"):
                report["no_summary"].append(key)
            if not op.get("description"):
                report["no_desc"].append(key)
            if not op.get("tags"):
                report["no_tags"].append(key)

            for p in op.get("parameters", []) or []:
                report["params"] += 1
                if not p.get("description"):
                    report["params_no_desc"].append(
                        f"{p.get('name')} ({p.get('in')}) @ {key}")

            # 成功响应有没有声明结构
            for code, resp in (op.get("responses") or {}).items():
                if not str(code).startswith("2"):
                    continue
                content = resp.get("content") or {}
                if not content:
                    report["ok_resp_empty"].append(f"{key} -> {code}")
                    break
                # ★ 不能只看 application/json —— zip 下载和纯文本日志永远没有它，
                #   只看 JSON 会把它们误报成"空壳"，再按清单去"补"，就会
                #   **给一个 zip 端点编一个假 JSON schema**（那比空着更糟）。
                #   只要**任意一种** content-type 声明了 schema，就算有结构。
                declared = False
                for _ctype, cdef in content.items():
                    sch = (cdef or {}).get("schema") or {}
                    if (sch.get("$ref") or sch.get("type")
                            or sch.get("properties") or sch.get("items")):
                        declared = True
                        break
                if not declared:
                    kinds = "、".join(content.keys()) or "无"
                    report["ok_resp_empty"].append(f"{key} -> {code}（已声明 content：{kinds}）")
                break   # 只看第一个 2xx
    return report


def print_report(rep: dict) -> None:
    print("=" * 70)
    print(f"体检报告 · {rep['title']}")
    print("=" * 70)
    n = rep["ops"]
    print(f"接口总数：{n}")
    _line("无 summary", rep["no_summary"], n)
    _line("无 description", rep["no_desc"], n)
    _line("无 tags（没分组）", rep["no_tags"], n)
    _line(f"成功响应没声明结构（共 {len(rep['ok_resp_empty'])} 处）",
          rep["ok_resp_empty"], n, limit=8)
    print(f"参数总数：{rep['params']}")
    _line("参数无说明", rep["params_no_desc"], rep["params"], limit=12)

    gaps = (len(rep["no_desc"]) + len(rep["params_no_desc"])
            + len(rep["ok_resp_empty"]))
    print("-" * 70)
    if gaps == 0:
        print("✅ 没有明显缺口。")
    else:
        print(f"⚠️  共 {gaps} 处缺口。这说明 /docs 换皮解决不了问题 ——")
        print("    按《手册 01》第四节的流程补，补在 docstring / description / response_model 上。")
    print()


def _line(label: str, items: list, total: int, limit: int = 10) -> None:
    if not items:
        print(f"  ✅ {label}：0")
        return
    print(f"  ⚠️  {label}：{len(items)} / {total}")
    for it in items[:limit]:
        print(f"       - {it}")
    if len(items) > limit:
        print(f"       …… 还有 {len(items) - limit} 处")


# ------------------------------------------------------------------ diff
def flatten(spec: dict) -> dict:
    """把 spec 拍成 {路径: 该接口的 JSON 文本}，用于比较。"""
    out = {}
    for path, item in (spec.get("paths") or {}).items():
        for method in METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                out[f"{method.upper()} {path}"] = json.dumps(op, sort_keys=True,
                                                             ensure_ascii=False)
    for name, sch in (spec.get("components", {}).get("schemas") or {}).items():
        out[f"schema:{name}"] = json.dumps(sch, sort_keys=True, ensure_ascii=False)
    return out


def print_diff(old: dict, new: dict) -> None:
    a, b = flatten(old), flatten(new)
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])

    print("=" * 70)
    print("与上次快照的差异")
    print("=" * 70)
    if not (added or removed or changed):
        print("  没有变化。")
        print()
        return
    for label, items, mark in (("新增", added, "+"), ("删除", removed, "-"),
                               ("有变化", changed, "~")):
        if not items:
            continue
        print(f"  {mark} {label} {len(items)} 项：")
        for it in items:
            print(f"       {it}")
    print()
    print("  提醒：删除和签名变化属于破坏性变更，按《优秀接口原则》第 4 条")
    print("        得有过渡期或走新路径。")
    print()


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="服务地址，例如 http://127.0.0.1:80xx")
    src.add_argument("--file", help="本地 openapi.json 路径")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="快照写到哪")
    ap.add_argument("--check-only", action="store_true", help="只体检，不写快照")
    ap.add_argument("--quiet-diff", action="store_true", help="不打 diff")
    args = ap.parse_args()

    try:
        spec = load_from_url(args.url) if args.url else load_from_file(args.file)
    except Exception as exc:  # noqa: BLE001
        print(f"[X] 读取失败：{exc}")
        if args.url:
            print("    服务没起？地址不对？还是 /openapi.json 被关了？")
        return 1

    print_report(check(spec))

    out = Path(args.out)
    if args.check_only:
        print(f"（--check-only，未写快照；本应写到 {out}）")
        return 0

    old = None
    if out.is_file():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            print(f"（旧快照读不动，跳过 diff：{out}）")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"快照已写入：{out}")

    if old is not None and not args.quiet_diff:
        print()
        print_diff(old, spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())