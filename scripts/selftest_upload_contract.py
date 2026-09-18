# -*- coding: utf-8 -*-
"""验证手册 04 里那条断言：FastAPI 能不能在一个 multipart 里同时吃下
「多文件」和「相对路径字符串」。

手册 04 第三节推荐的方案是：

    files: list[UploadFile] = File(...)   # 文件夹里的文件（浏览器拍平后逐个 append）
    rel_paths: str = Form("[]")           # 相对路径数组（保目录结构用）

如果 FastAPI 接不住这个组合，那条建议就是错的。这个脚本就是干这个的。

跑：python scripts/selftest_upload_contract.py
不需要起服务（用 TestClient），不依赖 requests。
"""
from __future__ import annotations

import json
import sys

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.testclient import TestClient

app = FastAPI()


@app.post("/api/upload/one")
async def upload_one(file: UploadFile = File(...)):
    """对应手册 04 的「② 上传文件」。"""
    data = await file.read()
    return {"name": file.filename, "size": len(data)}


@app.post("/api/upload/dir")
async def upload_dir(files: list[UploadFile] = File(...), rel_paths: str = Form("[]")):
    """对应手册 04 的「③ 上传文件夹」。"""
    rels = json.loads(rel_paths)
    out = []
    for i, f in enumerate(files):
        data = await f.read()
        out.append({
            "name": f.filename,
            "rel": rels[i] if i < len(rels) else None,
            "size": len(data),
        })
    return {"count": len(files), "items": out}


def main() -> int:
    c = TestClient(app)
    failed = []

    # ---- ① 单个文件 ----
    print("=" * 68)
    print("用例 1：② 上传文件 —— file: UploadFile")
    r = c.post("/api/upload/one", files={"file": ("数据.xlsx", b"hello-world")})
    print(f"  HTTP {r.status_code}  {r.text}")
    if r.status_code != 200 or r.json().get("size") != 11:
        failed.append("单个文件上传")
    else:
        print("  ✓ 通过")

    # ---- ② 文件夹：多文件 + 相对路径 ----
    print("=" * 68)
    print("用例 2：③ 上传文件夹 —— files: list[UploadFile] + rel_paths: str")
    files = [
        ("files", ("表A_数据文件一.xlsx", b"A" * 100)),
        ("files", ("表B_数据文件二.xlsx", b"B" * 200)),
        ("files", ("图表.png", b"C" * 50)),
    ]
    rels = ["示例县/表A_数据文件一.xlsx",
            "示例县/表B_数据文件二.xlsx",
            "示例县/图表/图表.png"]
    r = c.post("/api/upload/dir", files=files, data={"rel_paths": json.dumps(rels, ensure_ascii=False)})
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        failed.append("文件夹上传")
        print(f"  ✗ {r.text}")
    else:
        body = r.json()
        print(f"  收到 {body['count']} 个文件：")
        for it in body["items"]:
            print(f"    - {it['name']}  rel={it['rel']}  {it['size']}B")
        got = [it["rel"] for it in body["items"]]
        if body["count"] != 3:
            failed.append("文件数不对")
        elif got != rels:
            failed.append("相对路径没对上")
            print(f"  ✗ 相对路径不匹配\n    期望 {rels}\n    实得 {got}")
        elif [it["size"] for it in body["items"]] != [100, 200, 50]:
            failed.append("文件内容不对")
        else:
            print("  ✓ 通过（多文件与相对路径在同一个 multipart 里都拿到了）")

    # ---- ③ 中文文件名 ----
    print("=" * 68)
    print("用例 3：中文文件名与中文相对路径")
    r = c.post("/api/upload/dir",
               files=[("files", ("示例市_示例分析.xlsx", b"X" * 10))],
               data={"rel_paths": json.dumps(["汇总结果/示例市/示例市_示例分析.xlsx"],
                                             ensure_ascii=False)})
    print(f"  HTTP {r.status_code}  {r.text}")
    if r.status_code == 200 and r.json()["items"][0]["name"] == "示例市_示例分析.xlsx":
        print("  ✓ 通过（中文没被破坏）")
    else:
        failed.append("中文文件名")

    # ---- ④ 空文件夹 ----
    print("=" * 68)
    print("用例 4：空文件夹（浏览器不传空目录，这里模拟『只选了空目录』）")
    r = c.post("/api/upload/dir", files=[("files", ("", b""))],
               data={"rel_paths": json.dumps([])})
    print(f"  HTTP {r.status_code}  {r.text[:160]}")
    print("  → 说明：浏览器本来就不会传空目录，这条只是确认后端不崩")

    print("=" * 68)
    if failed:
        print(f"结论：❌ {len(failed)} 项未通过 -> {'、'.join(failed)}")
        print("      手册 04 第三节推荐的签名需要修正。")
        return 1
    print("结论：✅ 全部通过。手册 04 第三节推荐的签名可用：")
    print("      files: list[UploadFile] = File(...)")
    print("      rel_paths: str = Form(\"[]\")")
    return 0


if __name__ == "__main__":
    sys.exit(main())