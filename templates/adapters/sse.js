/* ============================================================================
 * 进度机制 · SSE（Server-Sent Events）
 * ============================================================================
 * 用途：后端有事件流接口时，用它**整个替换**界面模板里的 startWatching 函数。
 *       其余代码一行都不用动。
 *
 * 前提：
 *   1. 后端有 SSE 端点（如 GET /api/tasks/{id}/events）
 *   2. CONF.api 里加一项：stream: id => '/api/tasks/' + id + '/events'
 *
 * 设计取舍：推来的事件只当"有新进展"的信号，完整状态仍然查一次。
 *   为什么：事件体很容易和查询接口的返回体长成两套结构，长期维护是地狱。
 *   例外：如果后端推的就是完整任务对象，直接 onUpdate(JSON.parse(ev.data))，省掉那次查询。
 * ========================================================================== */

function startWatching(taskId, onUpdate){
  let stopped = false;

  const refresh = async () => {
    if (stopped) return;
    try { onUpdate(await api(CONF.api.task(taskId))); } catch(e){ /* 单次失败不打断 */ }
  };

  const es = new EventSource(CONF.api.stream(taskId));

  es.onmessage = refresh;
  // 后端也可以推具名事件；有就一起接住
  ['progress', 'log', 'state'].forEach(name => es.addEventListener(name, refresh));

  es.onerror = () => {
    // EventSource 自己会重连，这里什么都不用做。
    // 真要观测，就在这里打个日志；**不要**在这里 close()，那等于关掉了自动重连。
  };

  refresh();   // 先拿一次当前状态，避免等第一个事件时界面空着

  return () => { stopped = true; es.close(); };
}

/* ── 装进模板 ────────────────────────────────────────────────────────────────
 * 1. 在 CONF.api 里加：  stream: id => '/api/tasks/' + id + '/events',
 * 2. 把模板里 `function startWatching(...)` 那一段整块换成上面这个
 * 3. 确认 CONF.read.* 仍然对得上（适配器产出的是任务对象，字段名不能变）
 * ────────────────────────────────────────────────────────────────────────── */