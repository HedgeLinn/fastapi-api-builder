# 手册 04 · 终端用户面：输入控件

> **终端用户**要填的"输入数据"，前端能做成什么控件，**完全由后端签名决定**。这一节讲怎么判断、怎么做。
> 状态：判断流程已在示例服务上核对；**②③ 的上传接口契约已实测通过**
> （`scripts/selftest_upload_contract.py`，4 个用例全过：单文件 / 多文件+相对路径 / 中文文件名 / 空目录）。

---

## 一、铁律：先看签名，再定控件

**前端没有自由度。** 需求说"要支持三种输入来源"，但如果后端签名里没有对应参数，前端就做不出来——这不是设计问题，是物理限制。

| 后端签名长这样 | 前端**只能**给 | 终端用户看到什么 |
|---|---|---|
| `x: str` | 文本框 | 粘贴一个路径 / URL |
| `f: UploadFile` | 选单个文件 | 「选择文件」按钮 |
| `fs: list[UploadFile]` | 选多个文件 | 同上，可多选 |
| `fs: list[UploadFile]` + 相对路径参数 | 选文件夹 | 「选择文件夹」按钮 |

### 决策流程

```
① 打开目标服务的 /openapi.json，看请求模型
② 签名里有什么 → 前端就做什么（不要多，多了是假的）
③ 需求要的签名里没有 → 三选一，且必须让**服务开发人员**知道：
     a. 改后端（加参数）        ← 能改就改，最干净
     b. 用别的来源替代           ← 比如上传改共用共享盘
     c. 明确不做，写进文档       ← 最诚实，别假装支持
```

**绝不允许**：前端做了个"上传文件"的按钮，但后端签名里没有 `UploadFile`——点下去必然报错。这是最容易犯的错。

### ★ 如果后端是你新建的，这一节要**倒过来读**

上面那条铁律的前提是**签名已经存在**。当任务是"把一个本地脚本封成接口"时，情形相反：
**你就是后端的作者，签名由你定**。这时链路是正向的：

```
业务需求（要支持哪些输入来源）
   ↓  问服务开发人员：哪些是必须的？哪些是"有更好"？
定后端签名（input_path: str / file: UploadFile / files + rel_paths …）
   ↓  手册 04 §二 给了四种签名的写法与坑
定前端控件（签名里有哪种，就做哪种）
```

**"要不要做上传"因此变成一个纯业务决策，不是技术限制** —— 别把"签名里没有"当成理由，
你自己就能加。反过来也成立：**需求单上写了三种来源，不等于必须三种都做**，
问清"哪些真的会用到"再定（源脚本吃一整个目录、要凑齐两个 xlsx 才跑得动，
那"上传单个文件"就是白做）。

> 新增参数会让请求体从 JSON 变 `multipart/form-data` —— 属破坏性变更，
> 按《优秀接口原则》第 4 条得有过渡期或走新路径（如 `/api/tasks/v2`）。

---

## 二、四种输入的实现方式

### ① 共享文件夹地址 —— 最常见，也最省事

**后端签名**：`input_path: str`

**前端**：一个文本框，仅此而已。要点：

- **不要在前端校验路径存不存在**——前端看不见服务器的磁盘。让后端报错，把后端的错误原文显示出来（后端通常带原因）
- **从 `/api/meta` 之类拿默认值预填**，终端用户少一次复制粘贴
- **把"怎么填"说清楚**：同一类服务经常有多种填法（填自己 / 填上一级），这是最高频的出错点。示例服务就是典型——填错整批会被判 `failed`
- UNC 路径里的反斜杠不用前端操心（JSON 序列化自动处理），**但不要自己拼接路径**

### ② 上传文件

**后端签名**：`file: UploadFile = File(...)`

**前端**：
```html
<input type="file" id="f-file">
```
```js
const fd = new FormData();
fd.append('file', $('f-file').files[0], $('f-file').files[0].name);
fetch('/api/xxx', {method: 'POST', body: fd});   // ← 不要设 Content-Type
```

要点：

- **千万不要手动设 `Content-Type: multipart/form-data`** —— boundary 由浏览器生成，手写会导致后端解析失败
- **大文件要显示上传进度**：`fetch` 拿不到上传进度，用 `XMLHttpRequest`
- 上传和业务提交可以**一次请求搞定**（同一个 multipart 里既带文件又带参数）

### ③ 上传文件夹

**后端签名**：`files: list[UploadFile]`（**外加一个相对路径参数，见下**）

**前端**：
```html
<input type="file" id="f-dir" webkitdirectory multiple>
```
```js
const fs = $('f-dir').files;              // FileList，已按文件夹内容拍平
const fd = new FormData();
for (const f of fs) fd.append('files', f, f.name);
// ★ 目录结构在这里，必须一起传，否则后端收到一堆同名文件
fd.append('rel_paths', JSON.stringify(
  [...fs].map(f => f.webkitRelativePath || f.name)));
```

**这一条最容易踩坑**：

- 浏览器**只给扁平的文件列表**，目录结构藏在 `file.webkitRelativePath` 里
- **后端只接 `list[UploadFile]` 是不够的**——它拿不到目录层级。要么额外传一个 `rel_paths`（如上），要么用带 filename 的 multipart part 让后端自己解析路径
- **空文件夹传不了**（浏览器不传目录本身）
- **空文件名会让后端返回 422**（实测：`Expected UploadFile, received: <class 'str'>`）。
  浏览器正常选文件夹不会产生空文件名，但**前端仍要挡一道**（`files.length === 0` 就别发）
- **文件多时注意**：几百个文件 = 几百个 multipart part，某些代理/服务器会卡或超限，最好在后端设个数量上限

### ④ 填 URL 由后端去拉

**后端签名**：`url: str` —— 本质上是 ① 的变体，前端还是一个文本框。

要点：后端需要出网能力；**SSRF 风险由后端负责**（限制协议、限制内网地址），前端管不了。

---

## 三、拿一个具体服务走一遍：结论长什么样

它的签名是：

```python
class TaskCreate(BaseModel):
    input_path: str        # ← 只有一个字符串
    output_root: str = ""
```

| 需求里的来源 | 能做吗 | 结论 |
|---|---|---|
| ① 共享文件夹地址 | ✅ **能做** | 就是现在的 `input_path`，两个模板已经在用 |
| ② 上传文件 | ❌ 做不了 | 签名里没有 `UploadFile`。要支持得改后端 |
| ③ 上传文件夹 | ❌ 做不了 | 同上，还要额外加 `rel_paths` |
| ④ 填 URL 由后端去拉 | ❌ 做不了 | 签名里没有 `url` |

**要支持 ②③，后端得改成这样**（示意，不是现在就改）：

```python
@router.post("/api/tasks")
def create_task(
    input_path: str | None = Form(None),          # 来源 ①：共享盘路径
    file: UploadFile | None = File(None),         # 来源 ②：单个文件
    files: list[UploadFile] | None = File(None),  # 来源 ③：文件夹里的文件
    rel_paths: str | None = Form(None),           # 来源 ③：相对路径（保结构用）
):
    ...   # 业务逻辑不动，前面加一段"把三种来源统一落成 input_path"
```

**注意**：这样一来请求体从 JSON 变成了 `multipart/form-data`，**接口契约变了**——属于破坏性变更，按《优秀接口原则》第 4 条得有过渡期或走新路径（如 `/api/tasks/v2`）。

**这个签名已实测可用**（`scripts/selftest_upload_contract.py`）：

```
用例 1  file: UploadFile                              → 200，拿到文件名与内容
用例 2  files: list[UploadFile] + rel_paths: str      → 200，3 个文件与相对路径全部对上
用例 3  中文文件名 / 中文相对路径                        → 200，没被破坏
用例 4  空文件名                                       → 422（结构化报错，服务不崩）
```

结论：**"多文件"和"相对路径"确实能放在同一个 multipart 里**，不用拆成两个请求。

---

## 四、多个输入 / 多个来源怎么排布

**来源选择用"三选一"，不要三个同时铺开。** 同时铺开会让终端用户以为三样都要填。

```html
<div class="srcpick">
  <label><input type="radio" name="src" value="path" checked> 共享文件夹地址</label>
  <label><input type="radio" name="src" value="file"> 上传文件</label>
  <label><input type="radio" name="src" value="dir"> 上传文件夹</label>
</div>
<div id="pane-path"><input id="f-path" placeholder="共享盘上的目录"></div>
<div id="pane-file" hidden><input id="f-file" type="file"></div>
<div id="pane-dir" hidden><input id="f-dir" type="file" webkitdirectory multiple></div>
```

```js
function currentSource(){ return document.querySelector('input[name=src]:checked').value; }
function syncPanes(){
  const v = currentSource();
  $('pane-path').hidden = v !== 'path';
  $('pane-file').hidden = v !== 'file';
  $('pane-dir').hidden  = v !== 'dir';
}
document.querySelectorAll('input[name=src]').forEach(r => r.onchange = syncPanes);

async function submit(){
  const src = currentSource();
  if (src === 'path'){
    return api(CONF.api.create, {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({input_path: $('f-path').value.trim()})});
  }
  const fd = new FormData();
  if (src === 'file'){
    const f = $('f-file').files[0];
    if (!f) throw new Error('请先选择文件');
    fd.append('file', f, f.name);
  } else {
    const fs = [...$('f-dir').files];
    if (!fs.length) throw new Error('请先选择文件夹');
    for (const f of fs) fd.append('files', f, f.name);
    fd.append('rel_paths', JSON.stringify(fs.map(f => f.webkitRelativePath || f.name)));
  }
  return api(CONF.api.create, {method:'POST', body: fd});   // 不设 Content-Type
}
```

**装进模板**：改 `CONF.form` + `newTask()`（工作台）/ `step1()`（向导）里生成表单的那一小段。

---

## 五、上传进度（大文件必备）

`fetch` **拿不到上传进度**，要改用 `XMLHttpRequest`：

```js
function uploadWithProgress(url, fd, onPct){
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.upload.onprogress = e => {
      if (e.lengthComputable) onPct(Math.round(e.loaded / e.total * 100));
    };
    xhr.onload = () => {
      if (xhr.status < 400) { try { resolve(JSON.parse(xhr.responseText)); }
                              catch (e) { resolve(xhr.responseText); } }
      else reject(new Error(xhr.status + ' ' + xhr.responseText));
    };
    xhr.onerror = () => reject(new Error('网络错误'));
    xhr.send(fd);
  });
}
```

---

## 六、边界

- **前端看不见服务器文件系统** —— 路径类输入一律不前端校验，让后端报错并把原因原文显示给终端用户
- **上传文件夹必须后端配合** —— 只加 `list[UploadFile]` 拿不到目录结构，要一起传相对路径
- **前端校验只是体验，不是安全** —— 文件类型/大小前端可以挡一道，后端必须再挡
- **改输入方式 = 改接口契约** —— 从 JSON 变 multipart 是破坏性变更，要考虑兼容
- **三种来源不必都做** —— 后端支持哪种就做哪种，其余明确写进文档。假装支持比不支持更糟