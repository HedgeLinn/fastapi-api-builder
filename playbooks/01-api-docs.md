# 手册 01 · 接口调用方面：接口文档

> **这一面的风格已固定：Scalar。** 不要每次重新选渲染器、不要再做 A/B 对比。
> 适用对象：任何 FastAPI 服务。
> 状态：已跑通验证（Scalar v1.69.0，2026-09-18）。

---

## 一、固定结论

| 项 | 定论 |
|---|---|
| 渲染器 | **Scalar**（npm `@scalar/api-reference`） |
| 位置 | **占住 `/docs`** —— URL 不变，**接口调用方**的习惯不改 |
| 原生 Swagger UI | 挪到 `/docs-swagger` 留作兜底；彻底不要就 `docs_url=None` |
| 脚本 | **必须自托管**。内网机器出不去外网，走 CDN 会白屏 |
| 数据源 | `/openapi.json` —— 与任何渲染器完全一致，换皮不换内容 |
| 模板 | `templates/docs/api_docs.py`（可直接复制） |
| 下载脚本 | `scripts/fetch_scalar.py` |

### 为什么是 Scalar

- 现代、贴近大厂观感（**服务开发人员**原话："最理想和最贴近大厂"）
- 左侧导航 + **内嵌 API 客户端，能直接发请求**
- 自带多语言代码示例（curl / Python / JS）+ 搜索
- 代价：脚本 3.6 MB，自托管一次性付出

### 备选（都能挂上，但只验到 HTTP 200）

RapiDoc（轻，阅读型）、Stoplight Elements（文档站风格）、ReDoc（FastAPI 内置）、Swagger UI（就是被代替的那个）。

---

## 二、落地三步

```python
# ① 复制模板
#    templates/docs/api_docs.py  →  目标服务目录/api_docs.py
#    并把 templates/docs/static/scalar.js  →  目标服务目录/static/scalar.js

# ② main.py 加 import
from api_docs import make_docs_router

# ③ main.py 改两处
app = FastAPI(title="XXX服务", docs_url="/docs-swagger")   # 原生挪走，腾出 /docs
app.include_router(make_router(...))                       # 你原来的
app.include_router(make_docs_router(page_title="XXX服务 · 接口文档"))
```

**业务逻辑一行不动。** 只动 `main.py` 三行 + 新增一个文件。

---

## 三、好看的皮 ≠ 有内容（最容易搞错的地方）

**Scalar 只负责"皮"。** `/openapi.json` 里有没有内容，完全取决于代码里写没写。

真实案例：皮换了之后——

| | 换皮前 | 换皮后 |
|---|---|---|
| 有 `description` 的接口 | 1 / 10 | **仍然 1 / 10** |
| 有说明的参数 | 0 / 12 | **仍然 0 / 12** |
| 有结构的成功响应 | 0 / 10 | **仍然 0 / 10** |

**换渲染器解决不了"说明和参数定义缺失"。** 那是内容问题，必须回到代码里补。

---

## 四、内容补全流程（skill 的核心动作）

```
① 拉现状     GET /openapi.json —— 差在哪一目了然
② 找来源     已有的说明在哪？优先级：
               a. ★ 被封装的那个脚本自己的 docstring / 模块注释
                  —— 对"把本地脚本封成接口"这个主场景，这往往**是唯一成文的业务说明**
                  （实测：某脚本开头 26 行写了 12 条数据边界 + 两种目录结构 + 只读约束，
                   整段搬进 /docs 的顶部总览和接口 description，一个字都不用编）
                  **优先整段搬运，不要重写。**
               b. 项目里已有的文档（如《接口调用说明.md》—— 往往写得很好，只是没进代码）
               c. 代码本身（函数体读了什么字段、变量名、注释）
               d. 问服务开发人员
③ 起草       按第五节对照表，落到具体位置
④ 服务开发人员确认   ★ 不能省。AI 看着像模像样的说明可能跟业务差很远，比空着更糟
                     （确认的人 = skill 的使用者，不是接口调用方、也不是终端用户）
⑤ 落回代码   只动签名和模型，handler 一个字不改
⑥ 复核       按第六节清单逐条对
```

**第 ② 步是最容易被跳过的，也是最值钱的。** 有过一个服务，它的 `接口调用说明.md` 里调用流程、响应字段、错误码、踩坑提示全都有——**直接搬就行，一个字都不用编**。

---

## 五、要显示的东西 → 写在哪里

| 要显示的 | 写在 |
|---|---|
| 接口标题 | 路由装饰器 `summary="提交任务"` |
| 接口说明（支持 Markdown） | 函数 **docstring**，或装饰器 `description=` |
| 路径 / 查询参数说明 | `Path(..., description=)` / `Query(..., description=)` |
| 请求体字段说明 | Pydantic `Field(..., description=)` |
| **响应长什么样** | 装饰器 `response_model=` ← **收益最大的一条**，默认是空的 `{}` |
| 错误码 | 装饰器 `responses={400: {"description": ..., "content": {...}}}` |
| 分组 | `APIRouter(tags=[...])` 或装饰器 `tags=[...]` |
| 顶部整页总览 | `FastAPI(description=..., openapi_tags=[...])` |
| 枚举下拉 | 参数类型用 `Literal[...]`，Swagger/Scalar 会渲染成下拉框 |

参照物：`examples/api-docs-completed.py`（一个完整的补全后样子，handler 留空，可直接对照）。

---

## 六、检查清单

- [ ] 每个接口都有中文 `summary`（默认是 `Create Task` 这种自动英文，等于没有）
- [ ] 每个接口都有 `description`
- [ ] **每个参数**都有 `description`（枚举参数要把取值列全）
- [ ] 每个接口的 `response_model` 指向真实模型（不是空 `{}`）
- [ ] 请求体模型的**字段级**说明写了（类 docstring 不够）
- [ ] 分好组（`openapi_tags`）
- [ ] 不是 API 的路由（比如返回 HTML 的 `/`）加 `include_in_schema=False`

---

## 七、边界（别期望错位）

- **不解决跨域** —— Scalar 的 "Send Request" 是浏览器直连服务，同源才点得动。跨域要靠代理服务
- **不解决终端用户的界面** —— `/docs` 是给**接口调用方**的；**终端用户**要的是另一件事 → 见手册 02
- **不改任何业务逻辑** —— 全是签名和模型
- **自托管脚本要随服务走** —— 换机器部署时别忘了一起拷 `static/scalar.js`