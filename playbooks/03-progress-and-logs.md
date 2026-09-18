# 手册 03 · 进度与日志

> 任务跑起来了，界面上"现在到哪了"这句话从哪来？——**由后端能力决定，但界面侧契约固定**。
> 这一节讲怎么选机制、怎么写适配器。
> 状态：轮询机制已跑通；SSE / 日志 tail 为模板代码，未在真实后端上验证。

---

## 一、固定契约（本 skill 的核心约束）

**界面代码只认一个函数签名：**

```js
const stop = startWatching(taskId, onUpdate);
// onUpdate(taskObject)  —— 有新进展时调用，可以调很多次
// stop()                —— 任务结束或离开页面时调用，断开监听
```

- `taskObject` 的字段由 `CONF.read.*` 解释（见手册 02），**适配器不负责改字段名**
- 界面**不关心**数据是轮询来的、推来的、还是从日志里算出来的

**为什么这么定**：同一个界面要服务很多种后端。如果界面直接写死"每 3 秒 fetch 一次"，遇到 SSE 后端就得改界面——那就是每次重做。

**变化被关在 `templates/adapters/` 一个目录里。**

---

## 二、机制选型

| 机制 | 后端要求 | 延迟 | 复杂度 | 什么时候用 |
|---|---|---|---|---|
| **轮询** | 有"查任务状态"接口 | 中（受间隔限制） | ★ | **默认首选**，绝大多数服务 |
| **日志 tail** | 只有日志（文件或接口） | 中 | ★★ | 后端没有进度接口，但日志里能解析出来 |
| **SSE** | 有事件流接口 | 实时 | ★★★ | 进度要秒级、日志要连续滚 |
| **WebSocket** | 有 ws 接口 | 实时双向 | ★★★★ | 罕见，只在需要**双向**控制时值当 |
| 无 | —— | —— | —— | 接口是同步秒回的，用不上这一套 |

### 选择顺序

```
① 后端已经有"查任务状态"接口？         → 轮询（最省事，别为了实时去改后端）
② 后端只写日志？                        → 日志 tail
③ 后端已经在推流（或愿意加）？           → SSE
④ 需要双向？                            → WebSocket（先想清楚是不是真需要）
```

**不要为了"实时"去改后端。** 一个 10 分钟的任务，5 秒轮询完全够用；为它加一套 SSE 是纯粹的复杂度浪费。

---

## 三、三种适配器的写法

### ① 轮询（默认，两个界面模板里已内置）

```js
function startWatching(taskId, onUpdate){
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    try { onUpdate(await api(CONF.api.task(taskId))); } catch(e){ /* 单次失败不打断 */ }
  };
  tick();
  const t = setInterval(tick, CONF.pollMs);
  return () => { stopped = true; clearInterval(t); };
}
```

要点：
- **单次失败不打断**：网络抖一下就停掉监听，用户会觉得"卡死了"
- `pollMs` 放 `CONF` 里（手册 02）。任务越长，间隔可以越大
- 页面切到后台时浏览器会降频，这是正常的

### ② SSE（后端推"变了"，界面仍去查一次）

```js
function startWatching(taskId, onUpdate){
  // 推的事件只带"有新进展"，完整状态还是查一次 ——
  // 避免"事件体"和"查询体"两套结构不一致（那是长期维护的地狱）
  const es = new EventSource(CONF.api.stream(taskId));
  es.onmessage = async () => {
    try { onUpdate(await api(CONF.api.task(taskId))); } catch(e){}
  };
  es.onerror = () => { /* EventSource 自己会重连，这里不用管 */ };
  return () => es.close();
}
```

`CONF.api` 里加一项：`stream: id => '/api/tasks/' + id + '/events'`

**如果后端推的事件里就带完整任务对象**（少见但更好），直接 `onUpdate(JSON.parse(ev.data))`，省掉那次查询。

### ③ 日志 tail（后端没做进度，从日志里算）

```js
/* 每个服务的日志格式不同，这一块必须按目标服务改 ——
   相当于把服务端那套解析搬到前端。示例服务的 progress.py 就是同一个思路。 */
const PATTERNS = [
  { re: /处理进度：(\d+)\/(\d+)/,        apply: (m, s) => { s.current_no = +m[1]; s.total_count = +m[2]; } },
  { re: /\[(\d)\/6\]/,                   apply: (m, s) => { s.step = +m[1]; } },
  { re: /处理开始：发现 (\d+) 个/,        apply: (m, s) => { s.phase = 'region'; } },
  { re: /开始子项：(.+?) \/ (.+?)$/,      apply: (m, s) => { s.current_item = m[1] + ' / ' + m[2]; } }
];

function startWatching(taskId, onUpdate){
  const st = { state: 'running', progress: 0, current_item: '',
               current_no: 0, total_count: 0, ok_count: 0, skipped_count: 0, fail_count: 0 };
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    try {
      const text = await fetch(CONF.api.log(taskId, 500)).then(r => r.text());
      for (const line of text.split('\n')) {
        for (const p of PATTERNS) {
          const m = line.match(p.re);
          if (m) p.apply(m, st);
        }
      }
      st.progress = st.total_count
        ? Math.round((st.current_no - 1) / st.total_count * 100)
        : st.progress;
      onUpdate(st);
    } catch(e){}
  };
  tick();
  const t = setInterval(tick, CONF.pollMs);
  return () => { stopped = true; clearInterval(t); };
}
```

**三个坑**：

1. **进度要单调**：正则误配时宁可不动也不能回跳
2. **日志里的数字是累计的**，不是增量的 —— **但这条只对"前端 tail"成立**，见下
3. **正则的来源行号要写进注释**，否则上游脚本一改你就傻眼

### ★ 消费模式：前端 tail vs 服务端逐行（抄错就是 bug）

| | 前端 tail（`templates/adapters/log-tail.js`） | 服务端逐行（本 skill 的推荐默认） |
|---|---|---|
| 怎么消费 | 每轮**重读整个尾部** | 每来一行**喂一次** |
| 计数 | **归零重扫**再算 | **`+= 1` 累加** |
| 进度字段 | 覆盖写 | 覆盖写 |

同一条正则，两种消费模式写法**相反**。上面第 2 条坑说的是左边那列。

### 进度百分比怎么算（这条**要问服务开发人员**，AI 别自己拍）

阶段怎么划分、各占多少区间，**是业务判断**：

- 典型划法：启动 `0~2` → 扫描 → 主体阶段 `2~85` → 汇总阶段 `85~99` → 结束 `100`
- **必须问清**：哪个阶段是主体、哪个阶段可能很慢（慢的那个区间要给宽）
- 实测教训：某服务按"逐单元处理是主体"拍了 `2~85`，结果 7 个单元的任务里**前 28 秒走到 73%、最后 4 秒从 85 直跳 100** —— 单元一多或汇总一慢，节奏就明显不对

---

## 四、日志怎么显示

日志和进度**是两条线**，不要混：

| | 进度 | 日志 |
|---|---|---|
| 更新频率 | 低频（几秒一次） | 高频（每次拉都可能有新行） |
| 界面呈现 | 进度条 + 一行"当前在干什么" | 滚动的等宽文本框 |
| 要不要全量 | 只要最新状态 | 只看尾部（`tail=200` 就够） |

现在两个模板里的做法：**进度走 `startWatching`，日志单独定时拉尾部**。这样日志格式变坏不会影响进度条。

**日志要能复制**：出问题时终端用户会把日志发给服务开发人员。现在模板里是 `<pre>` 可以直接选，如果做成虚拟滚动列表就没有这个能力了——不值得换。

---

## 五、把适配器装进模板

两个界面模板里都有一段被注释标出的 `startWatching`。**换机制 = 换这一个函数**，别的什么都不动：

```js
/* ─── 进度机制：轮询（默认）。换成 SSE / 日志 tail 见 templates/adapters/ ─── */
function startWatching(taskId, onUpdate){ ... }
```

改完必须回头确认 `CONF.read.*` 还在正常工作 —— 适配器产出的是**任务对象**，字段名得和 `CONF.read` 对得上（尤其是 `progress` / `now` / `counts`）。

---

## 六、边界

- **适配器不改字段名** —— 它只负责"把进展喂进来"，视图解释权归 `CONF.read.*`
- **不要两套结构** —— SSE 事件体和查询接口返回体尽量保持一致，否则长期维护会很痛
- **任务结束要 `stop()`** —— 否则离开页面后还在轮询/连接，服务端会看到幽灵请求
- **不做断线重连的进度补偿** —— 断线期间错过的进度不重放，重连后拿最新状态即可（任务本身在服务端跑，不受影响）