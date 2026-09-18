# -*- coding: utf-8 -*-
"""示例：一个接口的说明"补全后"长什么样。

**这不是可直接运行的服务** —— handler 全部留空。它是《手册 01》第四节的
参考物：补什么、补在哪、补成什么样。

用法：拿它当对照，把你项目里 `models.py` 和 `api_routes.py` 按这个形状改。
      **handler 一律用你原来的实现，只搬签名和模型。**

案例：一个异步任务制的分析服务。

补全前后的差距（实测）：

    项目                      补全前   补全后
    有 description 的接口      1/10     9/9
    有说明的参数              0/12     12/12
    成功响应有结构            0/10     9/9
    响应模型                  3        12
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, Path, Query
from pydantic import BaseModel, Field

# ============================================================================
# 一、数据模型 —— 搬进你的 models.py
# ============================================================================
# 这是"响应长什么样"的来源。你原来的接口返回的是直接组装的 dict，所以
# openapi 里每个 response 都是空的 {} —— 调用方不知道会收到什么。

TaskState = Literal["queued", "running", "done", "partial_failed",
                    "failed", "invalid", "cancelled", "interrupted"]

STATE_DOC = (
    "任务状态。取值：\n"
    "- `queued` 排队中（非终态）\n"
    "- `running` 运行中（非终态）\n"
    "- `done` 完成 ✅ 判成功\n"
    "- `partial_failed` 部分失败：有区域失败或被跳过，但产出了结果 ✅ 判成功\n"
    "- `failed` 失败：没有任何区域成功（`error` 里有原因）\n"
    "- `invalid` 无效：输入目录里没有可识别的区域，未处理任何数据\n"
    "- `cancelled` 已被停止\n"
    "- `interrupted` 服务重启中断"
)


class TaskCreate(BaseModel):
    """一次示例分析任务 = 跑一次脚本。

    提交后**立即返回**，不会等分析跑完（异步任务，进度靠轮询）。
    """

    input_path: str = Field(
        ...,
        title="输入目录",
        description=(
            "共享盘上的数据目录。两种填法都支持，服务按"
            "「第一层目录里是否直接放着必需文件」自动识别：\n\n"
            "- **单城市**：直接填汇总层目录\n"
            "- **批量**：填汇总层目录的上一级\n\n"
            "目录里要有 `表A_数据文件一.xlsx` 和 `表B_数据文件二.xlsx`。"
        ),
    )
    output_root: str = Field(
        "",
        title="输出目录（通常不要传）",
        description=(
            "**不对使用者开放**。结果统一写到服务端固定的输出根，在其下按"
            "`{输入目录名}_{日期}` 自动建子目录。\n\n"
            "此字段仅为兼容脚本化调用保留，留空即用服务端配置。"
        ),
    )


class TaskCreateResponse(BaseModel):
    task_id: str = Field(..., description="任务唯一标识，后续查询 / 停止 / 重跑 / 下载都用它")
    state: TaskState = Field("queued", description="刚提交时固定为 `queued`")
    queue_position: int = Field(..., description="队列位置，`1` = 下一个跑")
    effective_root: str = Field(..., description="本次结果将写入的目录")
    overwrite_warning: str = Field("", description="非空表示会覆盖已有结果；空串表示新目录")


class Artifact(BaseModel):
    label: str = Field("", description="业务层级：`区域级` / `汇总级` / `运行汇总`")
    path: str = Field(..., description="绝对路径（在共享盘上）")
    rel_path: str = Field("", description="相对运行目录的路径，下载单个产物时当 `rel` 用")
    size: int = Field(0, description="文件大小（字节）")


class TaskSummary(BaseModel):
    """任务级字段（列表与详情共用）。字段说明只写一遍，两边都能看到。"""

    id: str = Field(..., description="任务唯一标识")
    state: TaskState = Field(..., description=STATE_DOC)
    phase: str = Field("", description="脚本内部阶段：`scan` / `region` / `city` / `finish`")
    input_path: str = Field(..., description="提交时填的输入目录")
    run_dir: str = Field("", description="本次运行占用的子目录名")
    progress: float = Field(0, description="进度百分比 0–100，可直接画进度条")
    current_item: str = Field("", description="当前正在处理的单元，例如 `示例市 / 示例县`")
    current_no: int = Field(0, description="当前第几个")
    total_count: int = Field(0, description="共几个")
    ok_count: int = Field(0, description="成功计数")
    skipped_count: int = Field(0, description="跳过计数")
    fail_count: int = Field(0, description="失败计数")
    error: str = Field("", description="终态时的说明：失败原因、计数汇总、覆盖提示等")
    created_at: str = Field("", description="提交时间（ISO）")
    finished_at: str = Field("", description="结束时间（ISO）")


class TaskDetail(TaskSummary):
    """任务详情。比列表多出产物清单和结果目录。"""

    artifacts: list[Artifact] = Field(default_factory=list,
                                      description="产物清单，只包含磁盘上仍然存在的文件")
    queue_position: int | None = Field(None, description="仍在排队时，前面还有几个")
    output_dir: str = Field("", description="**结果实际落在哪个目录**，可直接去共享盘取")
    script_sha256: str | None = Field(None, description="本次运行所用脚本的哈希")


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary] = Field(..., description="任务列表，按提交时间倒序")


class TaskActionResponse(BaseModel):
    task_id: str = Field(..., description="任务唯一标识")
    state: TaskState = Field(..., description=STATE_DOC)
    queue_position: int | None = Field(None, description="重跑后重新排队的位置")
    run_dir: str | None = Field(None, description="重跑后的运行目录名")


class MetaResponse(BaseModel):
    defaults: dict = Field(..., description="默认输入目录、固定输出根。页面可用于预填")
    concurrency: dict = Field(..., description="并发数。固定为 1 时说明服务同时只跑一个任务")
    vendors_script: str = Field(..., description="实际执行的分析脚本文件名")


# ============================================================================
# 二、应用级说明 —— 搬进 main.py 的 FastAPI(...)
# ============================================================================
# 这段会显示在 /docs 的最顶部，是"整体图景"。用 Markdown，渲染器会排版。

APP_DESC = """
把本地集成的**示例分析脚本**封装成接口，给不走网页的对接方直接调用。

## 调用流程（三步）

```
① POST /api/tasks                 提交任务（只填输入目录）→ 拿到 task_id
② GET  /api/tasks/{task_id}       轮询，直到 state 进入终态（建议 3–5 秒一次）
③ GET  /api/tasks/{task_id}/download   下载结果（zip）
```

**是异步任务**：提交后立即返回，服务端没有回调 / webhook，进度只能轮询。

## 判成功

**认 `done` 和 `partial_failed`**。`invalid` 表示"这个目录里没东西可分析"，不是成功。

## 注意事项

1. **必须轮询** —— 没有推送；`progress` 可直接用于展示。
2. **同时只跑一个任务** —— 多个任务会排队，`queue_position` 可查位次。
3. **同一结果目录互斥** —— 相同输入 + 同一天再提交会被 `409` 拦下。
4. **原始数据只读** —— 服务不会修改输入目录里的任何文件。
"""

OPENAPI_TAGS = [
    {"name": "任务", "description": "提交、查询、停止、重跑。**轮询用「查询任务」**。"},
    {"name": "结果", "description": "产物下载。结果同时也直接落在共享盘上。"},
    {"name": "服务", "description": "服务元信息，页面预填 / 对接方读取固定输出根用。"},
]


# ============================================================================
# 三、路由 —— 搬进你的 api_routes.py
# ============================================================================
# ★★ 关键：只改装饰器那一行和参数写法，**函数体一个字不动**。

app = APIRouter()

# 错误响应：让 /docs 里也能看到出错时返回什么。放进你的 api_routes.py 顶部。
ERR_400 = {400: {"description": "参数不合法：目录不存在 / 路径里还留着 `{}` 占位符 / 目录为空",
                 "content": {"application/json": {
                     "example": {"detail": "输入根目录不存在或不可访问：…"}}}}}
ERR_404 = {404: {"description": "任务不存在，或产物文件已被移动/删除",
                 "content": {"application/json": {"example": {"detail": "任务不存在"}}}}}
ERR_409 = {409: {"description": "资源冲突：同一结果目录已有任务在跑，或任务状态不支持该操作",
                 "content": {"application/json": {
                     "example": {"detail": "该结果目录已有任务在运行"}}}}}


# ── 补全前 ──────────────────────────────────────────────────────────────────
# @app.post("/api/tasks")
# def create_task(req: TaskCreate):
#     ...

# ── 补全后 ──────────────────────────────────────────────────────────────────
@app.post("/api/tasks", tags=["任务"], response_model=TaskCreateResponse,
          summary="提交任务", responses={**ERR_400, **ERR_409},
          description=("提交一次示例分析任务（= 跑一次脚本），**立即返回 task_id**，"
                       "不会等分析跑完。\n\n接下来用 `GET /api/tasks/{task_id}` 轮询进度。"))
def create_task(req: TaskCreate):
    ...          # ← 你原来的实现，一个字没改


@app.get("/api/tasks", tags=["任务"], response_model=TaskListResponse,
         summary="任务列表",
         description="列出历史任务，按提交时间倒序。**不含产物清单**，要产物请查详情。")
def list_tasks(
    state: TaskState | None = Query(None, description="只列出该状态的任务；不填则全部"),
    limit: int = Query(100, ge=1, le=500, description="返回条数上限（最大 500）"),
    offset: int = Query(0, ge=0, description="跳过前 N 条，用于翻页"),
):
    ...          # ← 你原来的实现


@app.get("/api/tasks/{task_id}", tags=["任务"], response_model=TaskDetail,
         summary="查询任务（轮询用这个）", responses={**ERR_404},
         description=("查任务的完整状态：进度、当前处理单元、成功/跳过/失败计数、"
                      "产物清单、结果目录。\n\n**轮询就调它**，建议 3–5 秒一次，"
                      "直到 `state` 进入终态。"))
def get_task(task_id: str = Path(..., description="任务唯一标识，提交任务时返回")):
    ...          # ← 你原来的实现


@app.post("/api/tasks/{task_id}/stop", tags=["任务"], response_model=TaskActionResponse,
          summary="停止任务", responses={**ERR_404, **ERR_409},
          description=("把任务置为 `cancelled`。\n\n"
                       "注意：脚本内部**没有取消钩子**，正在处理的那个区域要等它跑完"
                       "（最长约 5 秒），未开始的区域立即取消。已结束的任务返回 `409`。"))
def stop_task(task_id: str = Path(..., description="任务唯一标识")):
    ...          # ← 你原来的实现


@app.post("/api/tasks/{task_id}/retry", tags=["任务"], response_model=TaskActionResponse,
          summary="重跑任务", responses={**ERR_404, **ERR_409},
          description=("把终态任务重新排队。**脚本没有断点续跑能力，"
                       "重跑在任何情况下都是从零完整重算**，不会更快。\n\n"
                       "仅终态任务可重跑，否则 `409`。"))
def retry_task(
    task_id: str = Path(..., description="任务唯一标识"),
    new_dir: bool = Query(False, description=(
        "`false`（默认）= 复用原结果目录，覆盖已有成果；"
        "`true` = 另起一个目录（同一天自动加 `_2`、`_3`），保留上次结果供对比")),
):
    ...          # ← 你原来的实现


@app.get("/api/tasks/{task_id}/download", tags=["结果"],
         summary="下载结果（打包）", responses={**ERR_404},
         description=("产物只有 1 个时**直传该文件**；多个时返回 zip。\n\n"
                      "zip 内保留目录结构，自带运行目录名。全量多城市一轮约 300MB，"
                      "首次打包需要时间。"))
def download_zip(task_id: str = Path(..., description="任务唯一标识")):
    ...          # ← 你原来的实现


@app.get("/api/tasks/{task_id}/download/file", tags=["结果"],
         summary="下载单个产物", responses={**ERR_404},
         description=("下载清单里的某一个文件。\n\n"
                      "`rel` 必须取自本任务 `artifacts[].rel_path`（**需 URL 编码**，"
                      "含中文与斜杠）。服务只认自己记过的路径，不在清单里的 `rel` 返回 `404`。"))
def download_file(
    task_id: str = Path(..., description="任务唯一标识"),
    rel: str = Query(..., description="产物相对路径，取自 `artifacts[].rel_path`，需 URL 编码"),
):
    ...          # ← 你原来的实现


@app.get("/api/tasks/{task_id}/log", tags=["服务"], response_class=None,
         summary="运行日志", responses={**ERR_404},
         description=("纯文本，返回脚本完整 stdout 的尾部。**排障时看这个** —— "
                      "里面有每个区域的处理明细与失败原因。"))
def task_log(
    task_id: str = Path(..., description="任务唯一标识"),
    tail: int = Query(2000, ge=0, description="只返回最后 N 行；填 `0` 返回全量"),
):
    ...          # ← 你原来的实现（记得 response_class=PlainTextResponse）


@app.get("/api/meta", tags=["服务"], response_model=MetaResponse,
         summary="服务元信息",
         description=("返回默认输入目录、**固定输出根**、并发数、脚本名。"
                      "页面可用它预填，对接方可读取固定输出根。"))
def meta():
    ...          # ← 你原来的实现


# ============================================================================
# 四、还有两件顺手的事
# ============================================================================
# 1. 返回 HTML 的页面不是 API，别让它出现在 /docs 里：
#      @router.get("/", include_in_schema=False)
#
# 2. 全部补完后跑一遍体检，确认没有漏：
#      python scripts/fetch_schema.py --url http://127.0.0.1:<端口>
#    对照《手册 01》第六节的检查清单。