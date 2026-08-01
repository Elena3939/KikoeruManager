# 通知模板系统 · 后续路线图

> 本文档列出通知模板编辑器（积木 / 富文本 / HTML 模式）下一阶段待办的 4 个工作项。
> 每项给出范围、工作量、风险评估，便于排期和拆批确认。
>
> 当前已交付：
> - 5 个基础块（header_status / summary_card / rich_text / divider / spacer）
> - 4 个业务数据块（stats_grid / file_tree / diff_view / task_log）
> - 中文变量名 + 英文别名兼容
> - BlockNote 风格变量 pill
> - 大号 Tiptap 富文本（含 table 扩展）
> - 默认精美邮件模板
> - 弹窗扩大到 1480px

---

## #1 task_engine payload 注入（让业务块吃到真数据）

### 背景

当前 4 个业务数据块（stats_grid / file_tree / diff_view / task_log）在画布预览能渲染示例数据，但真实邮件中这些块的 `payload[sourceKey]` 为空，会显示「（无数据）」占位。

需要在各业务任务完成 / 失败时，把对应数据填入通知 payload。

### 单一注入点

所有通知 payload 都汇入 `backend/app/core/task_notification_service.py::_write_sync()`（约第 318-329 行），写到 `NotificationOutbox.payload`。

最稳的策略：在 `_write_sync` 加通用通道，从 `task.task_metadata['notification_extra']` 读数据合并进 payload；各业务只需在执行完成前往 metadata 塞数据。

### 推进力度选项

| 方案 | 范围 | 工作量 | 风险 |
|---|---|---|---|
| **1.A 只送通道 + 接解压导入** ✅ 推荐 | 改 `_write_sync` 加合并通道；解压导入完成点填入 `file_tree` / `stats` / `recent_logs`。其他 4 个 domain 待验证后再接 | ~250 行 | 低 |
| **1.B 全接 5 个 domain** | 解压导入 / 下载 / 上传 / 社团补全 / 字幕补配 一次改完 | ~800-1000 行 | 高（多业务核心路径动刀） |
| **1.C 只送通道不接业务** | 仅加通用通道 + helper API + 文档，业务接入由用户自己来 | ~50 行 | 极低 |

### 数据来源 key 约定

| 业务 | 应填字段 |
|---|---|
| 解压 / 导入 | `file_tree`（含 status: kept/filtered） + `stats` + `recent_logs` |
| 下载 | `download_files` + `stats` |
| 上传 | `upload_files` + `stats` |
| 社团补全 | `circle_diff`（label/old/new） + `recent_logs` |
| 字幕补配 | `subtitle_diff` |
| 任意失败 | `error_logs` + `summary` |

### Helper API（设计）

```python
# backend/app/core/notification_helper.py
def set_notification_extra(task, **kwargs) -> None:
    """把额外数据塞进任务的 metadata，供通知 payload 读取。

    Example:
        set_notification_extra(task,
            file_tree=[...],
            stats={"total_files": 12},
            recent_logs=[...]
        )
    """
    meta = dict(task.task_metadata or {})
    extra = dict(meta.get('notification_extra') or {})
    extra.update(kwargs)
    meta['notification_extra'] = extra
    task.task_metadata = meta
```

### `_write_sync` 改造（设计）

在第 318 行 outbox.payload 构造时合并：

```python
extra = (task.task_metadata or {}).get('notification_extra') or {}
payload={
    'event_type': event_type,
    'title': info['title'],
    # ... 现有字段 ...
    **extra,  # 业务自定义字段（file_tree / stats / 等）
},
```

---

## #2 Slash menu

### 背景

用户期望 Notion / BlockNote 风格：在富文本里输入 `/` 触发命令面板，快速插入标题 / 列表 / 引用 / 分割线 / 表格 / 变量。

### 实现思路

- 自定义 Tiptap Extension 监听 `/` keydown 位置
- 浮层组件（参考已有 `BlockTypePicker.vue`）：
  - 搜索框 + 上下键导航 + Enter 提交 + Esc 关闭
  - 智能定位（视口翻转）
- 命令注册：`{ name: '一级标题', icon, action: editor => editor.chain().focus().setHeading({level:1}).run() }`
- 同时挂到大号 RichTextEditor（HTML 模式）+ 内嵌富文本块

### 命令清单（设计）

| 命令 | 描述 |
|---|---|
| 一级标题 / 二级标题 / 三级标题 | H1 / H2 / H3 |
| 项目列表 / 编号列表 | 无序 / 有序列表 |
| 引用 | blockquote |
| 代码块 | pre code |
| 分割线 | hr |
| 表格 | 插入 3x3 表格 |
| 变量：任务标题 / 摘要 / ... | 插入对应变量 pill |

### 工作量

~300 行（SlashMenu.vue + SlashMenuExtension.js + RichTextEditor 集成）

---

## #3 修 inline style 丢失

### 背景

Tiptap 默认 schema 解析 HTML 时不识别的属性会被剥离（`style` / `class` / `cellpadding` / `cellspacing` / `border` / `width` / `height` 等）。

后果：默认精美邮件模板（基于 `<table>` + 大量 inline style）编辑后再保存，会丢失部分内联样式，导致邮件视觉塌陷。

### 实现思路

- 给 Tiptap 加 `GlobalAttributes` 扩展或重写每个 node 的 `addAttributes()`
- 覆盖 paragraph / heading / table / tableRow / tableCell / tableHeader / blockquote / pre / div / span 等节点
- 每个节点的 `attributes` 加：`style` / `class` / `width` / `height` / `align` / `valign` / `bgcolor` / `colspan` / `rowspan`
- `parseHTML` 读取，`renderHTML` 输出
- 验证：默认模板加载 → 编辑（不改 attribute） → 保存 → 回灌，HTML 视觉应该完全不变

### 工作量

~200 行（PreserveAttributes 扩展模块 + RichTextEditor 注册 + 验证）

### 风险

`style` 属性来源不可信时有 XSS 风险。但本系统中 HTML 来自模板编辑器（已经走 `html_sanitizer`），且只在用户自己设备本地渲染，安全风险可控。仍要确保 sanitizer 在最终发送前过滤。

---

## #4 预设模板库

### 背景

让用户新建模板时能从一组精心设计的预设里一键套用，减少从空白搭建的工作量。

### 实现思路

新建 `frontend/src/components/settings/block-editor/presetTemplates.js`：

```js
export const PRESET_TEMPLATES = [
  {
    id: 'preset-import-completed',
    name: '导入完成 · 简约',
    description: '解压 / 字幕导入任务完成时的标准模板',
    icon: '📥',
    event_types: ['completed'],
    task_domains: ['import', 'subtitle_import'],
    editor_mode: 'html',
    subject_template: '...',
    html_template: '...',
    blocks: null,
  },
  // 其他 4 个：字幕等待人工、上传完成、社团补全、任务失败
]
```

### UI 改造

- `NotificationTemplatesPanel.vue` 的"新建"按钮改为 dropdown：
  - 从空白创建
  - 从预设：导入完成 · 简约 / 字幕等待人工 · 警示风 / 上传完成 · 报告风 / 社团补全 · 差异对比 / 任务失败 · 错误堆栈
- 选中预设 → 一键填入 `form`，进入编辑器

### 工作量

~250 行（5 个预设 HTML 设计 + 选择列表 UI + 写入逻辑）

### 依赖

强烈建议先做 #3（保留 inline style），否则用户编辑预设时样式塌陷，预设的精美设计无意义。

---

## 推荐执行顺序

按工程稳定性 + 优先级，建议：

1. **#3 修 inline style**（基础设施 / 阻塞 #4）
2. **#4 预设模板库**（用户体验 / 减少手搭）
3. **#2 Slash menu**（编辑体验 / 锦上添花）
4. **#1.A 只送通道 + 接解压导入验证**（业务深度集成 / 最后做）

或者按用户原顺序：#1 → #2 → #3 → #4，但 #1 建议选 1.A（不要 1.B 一次动 5 个业务）。

---

## 当前已交付清单（参考）

详见：

- `@/d:/Clash Verge/KikoeruTool_Elena/docs/notification-template-builder.md` 设计文档
- 后端：`backend/app/core/block_renderers/__init__.py`、`backend/app/core/variable_registry.py`、`backend/app/core/notification_template_service.py`、`backend/app/core/html_sanitizer.py`
- 前端核心：
  - `frontend/src/components/settings/NotificationTemplateEditor.vue`
  - `frontend/src/components/settings/NotificationTemplatesPanel.vue`
  - `frontend/src/components/settings/block-editor/` 整个目录
