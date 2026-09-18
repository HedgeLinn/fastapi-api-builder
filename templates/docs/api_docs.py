# -*- coding: utf-8 -*-
"""把 FastAPI 的 /docs 换成 Scalar（自托管，内网可用）。

模板，复制到目标服务目录即可。已验证：Scalar v1.69.0。

前置：
  1. ``static/scalar.js`` 必须存在（用 ``scripts/fetch_scalar.py`` 下载，约 3.6 MB）
  2. main.py 三处改动::

       from api_docs import make_docs_router

       app = FastAPI(title="XXX服务", docs_url="/docs-swagger")  # 原生挪走，腾出 /docs
       app.include_router(make_router(...))                      # 你原来的
       app.include_router(make_docs_router(page_title="XXX服务 · 接口文档"))

为什么必须自托管：内网机器出不去外网，脚本走 CDN 会白屏。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

HERE = Path(__file__).resolve().parent
_STATIC = HERE / "static"

# 用 __TITLE__ 占位而不是 str.format —— 下面这段 JS 里全是花括号
_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
</head>
<body>
<script id="api-reference" data-url="/openapi.json"></script>
<script>
document.getElementById('api-reference').dataset.configuration = JSON.stringify({
  theme: 'default',
  layout: 'modern',
  darkMode: false,
  hideModels: false,
  defaultHttpClient: { targetKey: 'shell', clientKey: 'curl' },
  searchHotKey: 'k'
});
</script>
<script src="/static/scalar.js"></script>
</body>
</html>"""


def make_docs_router(page_title: str = "接口文档") -> APIRouter:
    """挂到 app 上即可占住 /docs。page_title 只影响浏览器标签页标题。"""
    router = APIRouter()

    @router.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def docs():
        return HTMLResponse(_HTML.replace("__TITLE__", page_title))

    @router.get("/static/{name}", include_in_schema=False)
    def static_file(name: str):
        # 只取文件名，挡掉 ../ 路径穿越
        p = _STATIC / Path(name).name
        if not p.is_file():
            raise HTTPException(404, "静态文件不存在")
        media = "application/javascript" if p.suffix == ".js" else "application/octet-stream"
        return FileResponse(p, media_type=media)

    return router