/* ============================================================================
 * 进度机制 · 日志 tail
 * ============================================================================
 * 用途：后端**没有**进度接口，只往日志里写。用它替换界面模板里的 startWatching。
 *
 * 思路：把服务端那套日志解析搬到前端 —— 边拉日志边用正则算进度。
 *       （服务端如果已经有解析好的进度接口，用轮询就好，别用这个。）
 *
 * ★ 必须按目标服务改的地方：PATTERNS。每个服务的日志格式都不一样。
 * ========================================================================== */

/* ── ★ 按目标服务改这一段 ──────────────────────────────────────────────────
 * 每条：{ re: 正则, apply: (匹配结果, 状态对象) => 就地更新状态 }
 * 正则的来源要写进注释（对应上游脚本的哪一行）—— 上游脚本一改，你能立刻定位。
 * 下面是示例服务的真实例子（对应 vendors 脚本的 stdout 格式）。
 * ────────────────────────────────────────────────────────────────────────── */
const PATTERNS = [
  // 「处理开始：发现 3 个具备两个文件的区域，1 个目录因缺少必需文件而跳过。」
  { re: /处理开始：发现 (\d+) 个/,      apply: (m, s) => { s.phase = 'region'; } },
  // 「处理进度：3/9」  ← 区域轴
  { re: /处理进度：(\d+)\/(\d+)/,       apply: (m, s) => { s.current_no = +m[1]; s.total_count = +m[2]; } },
  // 「开始子项：示例市 / 示例县」
  { re: /开始子项：(.+?) \/ (.+?)$/,     apply: (m, s) => { s.current_item = m[1] + ' / ' + m[2]; } },
  // 「[4/6]」  ← 脚本内部步骤
  { re: /\[(\d)\/6\]/,                  apply: (m, s) => { s.step = +m[1]; } },
  // 「子项结果：/path/to/xxx.xlsx」  ← 一条成功
  { re: /子项结果：(.+)$/,               apply: (m, s) => { s.ok_count = (s.ok_count || 0) + 0; } },
  // 「[跳过] 示例市 / 示例县：原因」
  { re: /\[跳过\] /,                     apply: (m, s) => { s.skipped_count = (s.skipped_count || 0) + 1; } },
  // 「[失败] 示例市 / 示例县：原因」
  { re: /\[失败\] /,                     apply: (m, s) => { s.fail_count = (s.fail_count || 0) + 1; } },
  // 「处理结束」
  { re: /处理结束/,                  apply: (m, s) => { s.phase = 'finish'; s.progress = 100; } }
];

function startWatching(taskId, onUpdate){
  // 一眼能看出进度的那几个字段先摆好，别让界面读到 undefined
  const st = {
    id: taskId, state: 'running', phase: 'scan', progress: 0,
    current_item: '', current_no: 0, total_count: 0,
    ok_count: 0, skipped_count: 0, fail_count: 0,
    output_dir: '', error: '', artifacts: []
  };

  let stopped = false;

  const tick = async () => {
    if (stopped) return;
    try {
      // tail 给大一点：每轮都是**全量重扫**，给少了会漏掉中间的行
      const text = await fetch(CONF.api.log(taskId, 800)).then(r => r.text());
      if (!text || text.startsWith('(')) return;    // 「(任务尚未开始，暂无输出)」

      // ★ 每轮先归零再重扫：日志是累计的，不是增量的。
      //   如果累加，重复扫同一段会越算越多。
      st.ok_count = 0; st.skipped_count = 0; st.fail_count = 0;
      for (const line of text.split('\n')) {
        for (const p of PATTERNS) {
          const m = line.match(p.re);
          if (m) p.apply(m, st);
        }
      }

      // 进度：从已完成的单元数推。**必须单调** ——
      // 正则误配时宁可不动也不能回跳（服务端 progress.py 里也是这么守的）
      if (st.phase !== 'finish' && st.total_count > 0) {
        const done = Math.max(0, (st.current_no - 1)) + (st.step || 0) / 6;
        const pct = Math.round(done / st.total_count * 100);
        if (pct > st.progress) st.progress = pct;
      }

      onUpdate(st);
    } catch(e){ /* 单次失败不打断 */ }
  };

  tick();
  const timer = setInterval(tick, CONF.pollMs);
  return () => { stopped = true; clearInterval(timer); };
}

/* ── 这个方案的三个坑（手册 03 第三节）───────────────────────────────────────
 * 1. 进度要单调：正则误配时宁可不动也不能回跳
 * 2. 日志是累计的：每轮归零重扫，不要累加
 * 3. 正则来源行号写进注释：上游脚本改了你能立刻定位
 *
 * 另一条路：如果后端能加接口，让服务端把解析好的进度吐出来（示例服务的
 * progress.py 就是这么干的），前端只要轮询就行 —— 那比在前端解析日志稳得多。
 * ────────────────────────────────────────────────────────────────────────── */