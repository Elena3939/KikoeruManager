# 邮件模板积木编辑器技术设计方案

> 状态：设计阶段  
> 目标：将现有 HTML 文本模板升级为 **Block Editor**，支持拖拽排序、属性配置、富文本编辑、实时预览和服务端安全渲染。

---

## 1. 技术方案

| 模块 | 选型 | 定位 |
|---|---|---|
| 块编辑器 | 自研 Block Editor | 左侧块库 + 中间画布 + 右侧属性面板 |
| 块排序 | AG Grid Row Drag | 只做块列表排序和行级操作 |
| 富文本 | Tiptap + StarterKit + Link | 只用于 `rich_text` 块 |
| 邮件渲染 | 后端 Block Renderer | blocks 渲染成 email-safe HTML |
| 安全清洗 | `sanitize_html()` adapter | 统一清洗 HTML，底层优先 `nh3` |
| 兼容旧模板 | `editor_mode` | `html` 走旧逻辑，`blocks` 走新逻辑 |

依赖：

```bash
pnpm add ag-grid-vue3
pnpm add @tiptap/vue-3 @tiptap/starter-kit @tiptap/extension-link
```

职责边界：

```txt
AG Grid：块列表、拖拽、选中、复制、删除
Tiptap：富文本编辑
Backend：变量替换、HTML 清洗、邮件渲染
```

---

## 2. 整体架构

```txt
Frontend
├─ NotificationTemplateEditor.vue
├─ TemplateBlockLibrary.vue       # 块库
├─ TemplateBlockCanvas.vue        # AG Grid 画布
├─ TemplateBlockInspector.vue     # 属性面板
├─ TemplateBlockPreview.vue       # iframe 预览
└─ RichTextEditor.vue             # Tiptap

Backend
├─ notification_template_service
├─ block_renderers/
├─ variable_registry.py
├─ html_sanitizer.py
└─ email_safe_renderer.py
```

渲染链路：

```txt
blocks -> block_renderers -> variable resolver -> sanitize_html -> email envelope -> html
```

---

## 3. 数据模型

### 3.1 模板表新增字段

```python
blocks = Column(JSON, default=list)
editor_mode = Column(String(20), default='blocks')
```

### 3.2 Block 结构

```json
{
  "id": "blk_xxx",
  "type": "file_tree",
  "enabled": true,
  "schemaVersion": 1,
  "visibility": {
    "eventTypes": [],
    "domains": []
  },
  "props": {}
}
```

### 3.3 rich_text 存储

```json
{
  "type": "rich_text",
  "props": {
    "contentJson": {},
    "htmlCache": "<p>...</p>"
  }
}
```

说明：`contentJson` 是编辑源数据，`htmlCache` 是预览和降级缓存。

---

## 4. V1 Block 清单

| type | 用途 |
|---|---|
| `header_status` | 顶部状态区 |
| `summary_card` | 摘要卡片 |
| `meta_card` | 单字段卡片 |
| `key_value_grid` | 字段网格 |
| `key_fields_chips` | chip 字段 |
| `stats_grid` | 统计信息 |
| `file_tree` | 文件树 |
| `diff_block` | 前后对比 |
| `json_block` | JSON 展示 |
| `text_paragraph` | 普通文本 |
| `rich_text` | 富文本 |
| `divider` | 分割线 |
| `spacer` | 间距 |
| `cta_button` | 操作按钮 |

E1 先做最小闭环：

```txt
header_status / summary_card / rich_text / divider / spacer
```

---

## 5. 变量系统

不使用 `valueExpr`，统一使用 `Variable Registry`。

```python
VARIABLE_REGISTRY = {
    "title": "payload.title",
    "summary": "payload.summary",
    "domain_label": "payload.domain_label",
    "rjcode": "payload.rjcode",
    "stats.total_files": "payload.stats.total_files",
}
```

Block 使用 `valueKey`：

```json
{
  "label": "文件数量",
  "valueKey": "stats.total_files",
  "fallback": "0"
}
```

Tiptap 插入 `{key}`，后端统一解析并 HTML escape。

---

## 6. 后端渲染

```python
def render_blocks(blocks, payload):
    html_parts = []
    for block in blocks:
        if not block.get("enabled", True):
            continue
        renderer = BLOCK_RENDERERS.get(block["type"])
        if renderer:
            html_parts.append(renderer(block["props"], payload))

    html = sanitize_html("".join(html_parts))
    return wrap_email_envelope(html)
```

邮件 HTML 约束：

```txt
允许：table、inline style、基础文本标签、链接、列表、按钮
禁止：script、iframe、外部 CSS、JS 交互、复杂折叠
```

`file_tree`、`json_block` 使用静态展示，不做真实折叠：

```json
{
  "renderMode": "summary | expanded | truncated",
  "maxItems": 50,
  "maxChars": 3000
}
```

---

## 7. Payload 扩展

```python
payload = {
    "event_type": str,
    "title": str,
    "summary": str,
    "severity": str,
    "domain": str,
    "domain_label": str,
    "rjcode": str,
    "created_at_text": str,
    "safe_metadata": dict,
    "file_items": list,
    "stats": dict,
    "raw_json_pretty": str,
}
```

`safe_metadata` 只暴露白名单字段，不直接暴露完整 `task_metadata`。

---

## 8. 前端关键配置

AG Grid：

```ts
{
  rowDragManaged: true,
  animateRows: true,
  pagination: false,
  suppressMovableColumns: true,
  getRowId: params => params.data.id,
  defaultColDef: {
    sortable: false,
    filter: false,
    resizable: false,
    suppressMenu: true,
  },
}
```

Tiptap：

```ts
[
  StarterKit.configure({ link: false, codeBlock: false }),
  Link.configure({
    openOnClick: false,
    autolink: true,
    linkOnPaste: true,
    protocols: ['mailto', 'tel'],
  }),
]
```

预览：

```txt
debounce 300ms + abort 上一个请求 + requestId 校验最新响应
```

---

## 9. API

```http
GET /api/notifications/blocks/schema
```

返回：Block 类型、默认 props、属性 schema、变量列表。

```http
POST /api/notifications/templates/preview-blocks
```

请求：

```json
{
  "requestId": "uuid",
  "blocks": [],
  "event_type": "completed",
  "domain": "subtitle"
}
```

响应：

```json
{
  "requestId": "uuid",
  "subject": "...",
  "html": "...",
  "text": "..."
}
```

---

## 10. 实施计划

| 阶段 | 内容 |
|---|---|
| S0 | AG Grid 拖拽原型，验证滚动、行高、选中、删除 |
| E1 | DB 字段、Block Renderer、核心块、保存、打开、预览 |
| E2 | 业务块：字段、chips、stats、file_tree、diff、json |
| E3 | Tiptap、变量插入、HTML 清洗 |
| E4 | 撤销重做、复制块、旧模板转换、内置模板 |

---

## 11. 风险处理

| 风险 | 方案 |
|---|---|
| AG Grid 拖拽手感不好 | S0 验证，不行换 SortableJS |
| 富文本性能下降 | 只在选中 `rich_text` 时实例化 Tiptap |
| metadata 泄漏 | 使用 `safe_metadata` 白名单 |
| 邮件兼容问题 | 只输出 email-safe HTML |
| 预览响应乱序 | debounce + abort + requestId |
| 旧模板迁移 | 保留 html 模式，提供转换按钮 |

---

## 12. 结论

采用：

```txt
自研 Block Editor
+ AG Grid Row Drag
+ Tiptap rich_text
+ 后端 Block Renderer
+ Variable Registry
+ safe_metadata
+ sanitize_html
```

该方案保留 Tiptap + AG Grid，但明确边界：

```txt
AG Grid 管块列表交互。
Tiptap 管富文本。
后端管渲染、安全和兼容。
```
