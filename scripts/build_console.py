# -*- coding: utf-8 -*-
"""模板 + 配置 → 单文件界面。

两个用法：

  ① 起草配置（从 openapi 快照推一个起点，人和 AI 再改）
     python scripts/build_console.py --draft-conf --template console-wizard \
            --from-schema data/openapi.snapshot.json --out conf.js

  ② 生成界面（把配置拼进模板）
     python scripts/build_console.py --template console-wizard \
            --config conf.js --out console.html

为什么要有这一步：**模板是通用的，配置才是每次业务相关的那一小块。**
分开之后，模板可以随 skill 更新，配置留在项目里，两边互不污染。

只依赖标准库。若本机有 node，会顺手做一次 JS 语法检查（没有就跳过）。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TPL_DIR = HERE.parent / "templates" / "console"

TEMPLATES = {
    "console-workspace": "工作台双栏（管一批任务的人）",
    "console-wizard": "向导分步（就想跑一次的人）",
}

# CONF 的基线键（手册 02 第三节）。实际要求的是下面 required_keys() 从模板里推出来的那份，
# 这个列表只是"连模板都读不动"时的兜底。
REQUIRED_KEYS = ["title", "form", "api", "states", "terminal", "read", "pollMs"]

CONF_START = "const CONF = {"
CONF_END_MARK = "/* ======================= 配置区结束"


# ====================================================================== 生成
def splice(template_text: str, conf_text: str, title: str | None) -> str:
    """把配置块拼进模板。"""
    start = template_text.find(CONF_START)
    if start < 0:
        raise SystemExit("[X] 模板里找不到 `const CONF = {` —— 模板被动过了？")
    end = template_text.find(CONF_END_MARK, start)
    if end < 0:
        raise SystemExit("[X] 模板里找不到配置区结束标记 —— 模板被动过了？")

    conf_text = conf_text.strip()
    if not conf_text.endswith(";"):
        conf_text += ";"
    out = template_text[:start] + conf_text + "\n\n" + template_text[end:]

    if title:
        out = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", out, count=1)
    return out


def required_keys(template_text: str) -> list[str]:
    """从**模板代码里**推它需要哪些 CONF 键。

    为什么不手写清单：手写的会跟模板漂移。
    实测教训：向导模板漏配 `read.summary` 时，手写清单查不到 —— 生成成功、语法通过、
    界面却在"以前的记录"那一行悄悄空着。改成从模板里抠，就再也不会漂移。
    """
    body = template_text.split(CONF_END_MARK, 1)[-1]      # 只看配置区之后的部分
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)    # 剥掉注释，免被示例文字干扰
    top = sorted(set(re.findall(r"\bCONF\.([A-Za-z_]\w*)", body)) - {"read"})
    rd = sorted(set(re.findall(r"\bCONF\.read\.([A-Za-z_]\w*)", body)))
    if not top and not rd:                # 模板读不动就退回基线
        return list(REQUIRED_KEYS)
    return top + [f"read.{k}" for k in rd]


def check_conf(conf_text: str, template_text: str) -> list[str]:
    """检查模板要用到的键在不在。漏了不会报错、只是界面悄悄空一块，所以在这里挡一道。"""
    keys = required_keys(template_text)
    missing = []
    for k in keys:
        leaf = k.split(".")[-1]
        if not re.search(rf"\b{re.escape(leaf)}\s*:", conf_text):
            missing.append(k)
    return missing


def js_syntax_check(html: str) -> str | None:
    """有 node 就顺手检查一下 JS 语法。没有就返回 None。"""
    node = shutil.which("node")
    if not node:
        return None
    clean = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    blocks = re.findall(r"<script>(.*?)</script>", clean, flags=re.S)
    if not blocks:
        return None
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "check.js"
        f.write_text(blocks[-1], encoding="utf-8")
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    return None if r.returncode == 0 else (r.stdout + r.stderr).strip()


# ====================================================================== 起草
def _first(paths: dict, method: str, pred) -> str | None:
    for p, item in paths.items():
        if method in item and pred(p, item[method]):
            return p
    return None


def _js_path(p: str, param: str = "id") -> str:
    """'/api/tasks/{task_id}/log'  ->  '"/api/tasks/" + id + "/log"' """
    parts = re.split(r"\{[^}]+\}", p)
    if len(parts) == 1:
        return json.dumps(p)
    out = json.dumps(parts[0])
    for seg in parts[1:]:
        out += f" + {param} + {json.dumps(seg)}"
    return out


def _guess_state_enum(spec: dict) -> list[str] | None:
    """在 components.schemas 里找像"任务状态"的枚举。"""
    for _name, sch in (spec.get("components", {}).get("schemas") or {}).items():
        for _prop, pdef in (sch.get("properties") or {}).items():
            vals = pdef.get("enum")
            if not vals and isinstance(pdef.get("anyOf"), list):
                for alt in pdef["anyOf"]:
                    if alt.get("enum"):
                        vals = alt["enum"]
                        break
            if vals and any(v in ("running", "queued", "pending", "processing")
                            for v in vals):
                return [str(v) for v in vals]
    return None


# 状态值 -> [人话, 色调]。色调只认 run / ok / warn / bad / wait
_TONE = {
    "queued": "wait", "pending": "wait", "waiting": "wait", "created": "wait",
    "running": "run", "processing": "run", "started": "run", "in_progress": "run",
    "done": "ok", "success": "ok", "succeeded": "ok", "completed": "ok", "finished": "ok",
    "partial_failed": "warn", "partial": "warn", "partial_success": "warn",
    "failed": "bad", "error": "bad", "invalid": "bad", "interrupted": "bad",
    "cancelled": "wait", "canceled": "wait", "stopped": "wait",
}
# schema 里认不出状态枚举时的兜底（很常见）。terminal 不能为空，否则界面不停轮询。
DEFAULT_STATES = ["queued", "running", "done", "partial_failed", "failed",
                  "invalid", "cancelled", "interrupted"]
DEFAULT_TERMINAL = ["done", "partial_failed", "failed", "invalid",
                    "cancelled", "interrupted"]

_LABEL = {
    "queued": "排队中", "pending": "等待中", "waiting": "等待中", "created": "已提交",
    "running": "处理中", "processing": "处理中", "started": "处理中", "in_progress": "处理中",
    "done": "已完成", "success": "已完成", "succeeded": "已完成",
    "completed": "已完成", "finished": "已完成",
    "partial_failed": "部分完成", "partial": "部分完成", "partial_success": "部分完成",
    "failed": "失败", "error": "出错", "invalid": "无效", "interrupted": "中断",
    "cancelled": "已取消", "canceled": "已取消", "stopped": "已停止",
}


def draft_conf(spec: dict, template: str) -> str:
    """从 openapi 快照推一份起点配置。**这是草稿，不是成品。**"""
    paths = spec.get("paths", {})
    title = spec.get("info", {}).get("title", "未命名服务")

    create = _first(paths, "post", lambda p, o: "requestBody" in o)
    task = _first(paths, "get", lambda p, o: "{" in p)
    plain = [p for p, i in paths.items() if "get" in i and "{" not in p]
    liste = plain[0] if plain else None
    log = _first(paths, "get", lambda p, o: "log" in p.lower())
    dl = _first(paths, "get", lambda p, o: "download" in p.lower() and "{" in p)
    # 单文件下载通常比打包下载多一层路径（…/download/file）
    dl_file = _first(paths, "get", lambda p, o: (
        "download" in p.lower() and "{" in p
        and p.count("/") > ((dl or "").count("/"))))
    states = _guess_state_enum(spec) or []

    L: list[str] = []
    add = L.append

    add("const CONF = {")
    add("  title: " + json.dumps(title, ensure_ascii=False) + ",")

    if template == "console-wizard":
        add("  lede: '一句话说清终端用户能得到什么。',   /* TODO */")
        add("  recentSummary: '查看以前的记录',")
        add("  stepLabels: ['选数据', '确认', '处理中', '取结果'],")
    else:
        add("  tagline: '一句话说明 · 任务进度 · 结果下载',   /* TODO */")
        add("  listHint: '历史任务',")
    add("")

    # ---- 表单 ----
    add("  form: {")
    if template == "console-wizard":
        add("    label: '要处理哪个数据？',   /* TODO */")
        add("    placeholder: '填一个路径或选择文件',")
        add("    howto: '告诉终端用户该怎么填、最容易填错什么。',   /* TODO 可以带 HTML */")
    else:
        add("    heading: '这一步要做什么',   /* TODO */")
        add("    desc: '一句话说清这一步。',   /* TODO */")
        add("    label: '要处理的数据',   /* TODO */")
        add("    placeholder: '填一个路径或选择文件',")
        add("    tip: '告诉终端用户该怎么填、最容易填错什么。',   /* TODO 可以带 HTML */")
    add("    prefill: m => (m.defaults && m.defaults.input_path) || '',")
    add("    body: v => ({ input_path: v })   /* TODO 按后端请求模型改 */")
    add("  },")
    add("")

    # ---- 接口路径 ----
    add("  api: {")
    add("    meta:     '/api/meta',   /* TODO 确认路径 */")
    add("    create:   " + (_js_path(create) if create else "'/api/xxx'") + ",   /* POST */")
    add("    list:     " + (_js_path(liste) if liste else "'/api/xxx'") + ",   /* GET */")
    add("    task:     id => " + (_js_path(task) if task else "'/api/xxx/' + id") + ",")
    add("    log:      (id, n) => "
        + (_js_path(log) if log else "'/api/xxx/' + id + '/log'") + " + '?tail=' + n,")
    add("    download: id => "
        + (_js_path(dl) if dl else "'/api/xxx/' + id + '/download'") + ",")
    if dl_file:
        add("    file:     (id, rel) => " + _js_path(dl_file)
            + " + '?rel=' + encodeURIComponent(rel),   /* TODO 确认查询参数名 */")
    else:
        add("    file:     (id, rel) => '/api/xxx/' + id + '/download/file?rel='"
            " + encodeURIComponent(rel)   /* TODO 没猜出单文件下载接口 */")
    add("  },")
    add("")

    # ---- 状态 ----
    add("  /* 把后端的状态值映射成 [人话, 色调]。色调只认 run / ok / warn / bad / wait */")
    add("  states: {")
    if states:
        for v in states:
            add(f"    {v}: ['{_LABEL.get(v, v)}', '{_TONE.get(v, 'wait')}'],")
        add("  },")
        add("  terminal: " + json.dumps(states) + ",")
    else:
        # schema 里认不出来（很常见：响应是空壳）。这里必须给一份能用的默认值 ——
        # terminal 为空会让界面永远不停轮询、永远走不到结果页。
        add("    /* 没能从 schema 里认出状态枚举（响应是空壳的常见后果）。")
        add("       下面是常见的任务状态取值，**按后端实际值改**。 */")
        for v in DEFAULT_STATES:
            add(f"    {v}: ['{_LABEL.get(v, v)}', '{_TONE.get(v, 'wait')}'],")
        add("  },")
        add("  terminal: " + json.dumps(DEFAULT_TERMINAL) + ",")
    add("")

    # ---- 字段映射 ----
    add("  /* ★ 决定界面显示什么，最需要按服务改 */")
    add("  read: {")
    add("    id:        t => t.id,")
    add("    summary:   t => t.input_path,   /* TODO 列表里显示的那一行 */")
    add("    outputDir: t => t.output_dir || '',")
    add("    progress:  t => Math.round(t.progress || 0),   /* TODO 进度从哪个字段来 */")
    add("    now:       t => t.current_item ? ('正在处理 ' + t.current_item) : '',   /* TODO */")
    add("    counts:    t => [['已完成', t.ok_count], ['跳过', t.skipped_count],"
        " ['失败', t.fail_count]],   /* TODO */")
    add("    error:     t => t.error || '',")
    add("    artifacts: t => (t.artifacts || []).map(a => ({ label: a.label || '',"
        " path: a.rel_path || a.path || '', size: a.size }))"
        + ("" if template == "console-wizard" else ","))
    if template != "console-wizard":
        add("    fileUrl:   (id, a) => CONF.api.file(id, a.path)")
    add("  },")
    add("")

    # ---- 模板特有的文案 ----
    if template == "console-wizard":
        add("  text: {")
        add("    step1Title: '开始一次任务',")
        add("    step2Title: '确认一下',")
        add("    step2Sub: '确认后就会开始。过程中可以随时停止。',")
        add("    step3Title: '正在处理…',")
        add("    step3Sub: '可以关掉这个页面，服务会在后台继续跑。',")
        add("    step4Ok: '处理完成',")
        add("    step4OkSub: '结果已经存到固定位置。',   /* TODO 说清结果在哪、怎么拿 */")
        add("    step4Bad: '没能完成',")
        add("    step4BadSub: '这次没有产出结果。',")
        add("    resultLabel: '结果目录'")
        add("  },")
        add("  confirmNote: '要跑多久、能不能关页面。',   /* TODO */")
    else:
        add("  msg: {")
        add("    partial: '部分完成：有部分内容没处理成功。',   /* TODO */")
        add("    done:    '任务完成。'")
        add("  },")
    add("")
    add("  pollMs: " + ("3000" if template == "console-wizard" else "4000"))
    add("};")

    return "\n".join(L)


# ====================================================================== 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", choices=sorted(TEMPLATES), required=True,
                    help="用哪个界面模板")
    ap.add_argument("--config", help="配置文件（含 const CONF = {...};）")
    ap.add_argument("--out", required=True, help="输出路径")
    ap.add_argument("--title", help="浏览器标签页标题（覆盖 CONF.title）")
    ap.add_argument("--draft-conf", action="store_true",
                    help="起草配置：从 --from-schema 推一个起点")
    ap.add_argument("--from-schema", help="openapi 快照路径（配合 --draft-conf）")
    args = ap.parse_args()

    tpl_path = TPL_DIR / f"{args.template}.html"
    if not tpl_path.is_file():
        print(f"[X] 模板不存在：{tpl_path}")
        return 1
    template = tpl_path.read_text(encoding="utf-8")
    out = Path(args.out)

    # ---- 起草模式 ----
    if args.draft_conf:
        if not args.from_schema:
            print("[X] --draft-conf 需要 --from-schema")
            return 1
        spec = json.loads(Path(args.from_schema).read_text(encoding="utf-8"))
        conf = draft_conf(spec, args.template)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(conf + "\n", encoding="utf-8")
        print(f"起草完成：{out}")
        print()
        print("这只是**起点**，不是成品。接下来必须按业务改：")
        print("  · 所有标了 TODO 的地方")
        print("  · states 的人话与色调")
        print("  · read.* 那几个取值函数（决定界面显示什么）")
        print("  · form.body（提交时怎么组装请求体）")
        print()
        print(f"改完跑：python scripts/build_console.py --template {args.template} "
              f"--config {out} --out console.html")
        return 0

    # ---- 生成模式 ----
    if not args.config:
        print("[X] 生成界面需要 --config；只想起草就加 --draft-conf")
        return 1
    conf_path = Path(args.config)
    if not conf_path.is_file():
        print(f"[X] 配置不存在：{conf_path}")
        return 1
    conf_text = conf_path.read_text(encoding="utf-8")

    missing = check_conf(conf_text, template)
    if missing:
        print(f"[X] 配置里缺这些键（模板要用，缺了界面会悄悄空一块）：")
        for k in missing:
            print(f"      · {k}")
        print("    对照手册 02 第三节的表格补齐。")
        return 1

    html = splice(template, conf_text, args.title)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    print(f"生成完成：{out}  ({len(html):,} 字符)")
    print(f"  模板：{args.template} —— {TEMPLATES[args.template]}")
    print(f"  配置：{conf_path}")

    err = js_syntax_check(html)
    if err is None:
        node = shutil.which("node")
        print("  JS 语法：✅ 通过" if node else "  JS 语法：跳过（本机没有 node）")
    else:
        print("  JS 语法：❌ 没过")
        print(err)
        return 1

    print()
    print("下一步：把这个单文件丢进目标服务的静态目录，用一条路由发出去")
    print("        （和 /api/* 同源，这样没有跨域问题）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())