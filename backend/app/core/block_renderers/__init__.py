"""E1 Block Renderers

E1 最小闭环：header_status / summary_card / rich_text / divider / spacer

每个渲染器签名：renderer(props: dict, payload: dict) -> str
输出 email-safe table-based HTML。
"""
import html as _html
import re as _re
from ..variable_registry import resolve_variable, substitute_variables
from ..html_sanitizer import sanitize_html

# 富文本里的"变量 pill"节点：把 <span data-var="任务标题">...</span>
# 还原为 {任务标题}，后续 substitute_variables 再替换为真实值。
_VAR_PILL_RE = _re.compile(
    r'<span\b[^>]*\bdata-var\s*=\s*"([^"]+)"[^>]*>.*?</span>',
    _re.IGNORECASE | _re.DOTALL,
)

_SEVERITY_BG = {
    "success": "#1f8f4e",
    "danger":  "#d93025",
    "warning": "#d97706",
    "info":    "#0071e3",
}


def _esc(v: str) -> str:
    return _html.escape(str(v or ""))


def _resolve(key: str, payload: dict, fallback: str = "") -> str:
    return resolve_variable(key, payload, fallback)


# ---------------------------------------------------------------------------
# header_status
# ---------------------------------------------------------------------------
def render_header_status(props: dict, payload: dict) -> str:
    title    = _resolve(props.get("titleKey",    "任务标题"), payload, "任务通知")
    summary  = _resolve(props.get("summaryKey",  "摘要"),     payload, "")
    severity = _resolve(props.get("severityKey", "严重程度"), payload, "info")
    bg = _SEVERITY_BG.get(severity, _SEVERITY_BG["info"])
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:0;">'
        f'<tr><td style="background:{bg};padding:28px 36px;border-radius:12px 12px 0 0;">'
        f'<p style="margin:0 0 6px 0;font-size:20px;font-weight:600;color:#fff;">{title}</p>'
        f'<p style="margin:0;font-size:13px;color:rgba(255,255,255,0.88);line-height:1.5;">{summary}</p>'
        f'</td></tr></table>\n'
    )


# ---------------------------------------------------------------------------
# summary_card
# ---------------------------------------------------------------------------
def render_summary_card(props: dict, payload: dict) -> str:
    label = _esc(props.get("label", "摘要"))
    value = _resolve(props.get("valueKey", "摘要"), payload, "")
    accent = _esc(props.get("accentColor", "#0071e3"))
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;">'
        f'<tr><td style="padding:14px 16px;background:#f5f5f7;border-radius:10px;'
        f'border-left:3px solid {accent};">'
        f'<p style="margin:0 0 4px 0;font-size:11px;font-weight:600;color:#8e8e93;'
        f'text-transform:uppercase;letter-spacing:0.06em;">{label}</p>'
        f'<p style="margin:0;font-size:14px;color:#1d1d1f;font-weight:500;">{value}</p>'
        f'</td></tr></table>\n'
    )


# ---------------------------------------------------------------------------
# rich_text
# ---------------------------------------------------------------------------
def render_rich_text(props: dict, payload: dict) -> str:
    """富文本渲染：sanitize → 还原变量 pill → 替换 {var} 占位。

    清洗顺序：先 sanitize 再 substitute，避免恶意 HTML 借变量名逃过清洗。
    pill 还原步骤把 <span data-var="任务标题">任务标题</span> 转为 {任务标题}，
    让后续 substitute_variables 统一处理。
    """
    html_cache = props.get("htmlCache") or ""
    cleaned = sanitize_html(html_cache)
    # 还原变量 pill 为占位符
    unwrapped = _VAR_PILL_RE.sub(lambda m: '{' + m.group(1) + '}', cleaned)
    rendered = substitute_variables(unwrapped, payload, escape=True)
    return (
        f'<div style="padding:4px 0;font-size:14px;color:#1d1d1f;line-height:1.6;">'
        f'{rendered}'
        f'</div>\n'
    )


# ---------------------------------------------------------------------------
# divider
# ---------------------------------------------------------------------------
def render_divider(props: dict, payload: dict) -> str:
    color  = _esc(props.get("color",  "#e5e5ea"))
    margin = max(0, min(64, int(props.get("margin", 16) or 16)))
    return f'<hr style="border:none;border-top:1px solid {color};margin:{margin}px 0;" />\n'


# ---------------------------------------------------------------------------
# spacer
# ---------------------------------------------------------------------------
def render_spacer(props: dict, payload: dict) -> str:
    height = max(0, min(120, int(props.get("height", 16) or 16)))
    return f'<div style="height:{height}px;line-height:{height}px;font-size:1px;">&nbsp;</div>\n'


# ---------------------------------------------------------------------------
# stats_grid —— 多列数字统计网格
# ---------------------------------------------------------------------------
def render_stats_grid(props: dict, payload: dict) -> str:
    """从 payload['stats'] 读取 dict，按 props['items'] 配置渲染网格。

    items 每项：{"key": "total_files", "label": "总文件数", "icon": "📁"}
    columns 控制每行列数（2 或 3 或 4）。
    """
    items = props.get("items") or []
    if not items:
        return ""
    columns = max(1, min(4, int(props.get("columns", 3) or 3)))
    stats = payload.get("stats") or {}

    cell_w = 100 / columns
    cells_html = []
    for it in items:
        key = it.get("key") or ""
        label = _esc(it.get("label") or key)
        icon = _esc(it.get("icon") or "")
        # stats 里嵌套点号（如 "duration.seconds"）
        val = stats
        for part in str(key).split("."):
            if isinstance(val, dict):
                val = val.get(part)
            else:
                val = None
                break
        val_str = _esc("" if val is None else str(val))
        icon_html = (
            f'<span style="font-size:14px;margin-right:6px;">{icon}</span>'
            if icon else ""
        )
        cells_html.append(
            f'<td width="{cell_w:.2f}%" valign="top" style="padding:14px 16px;'
            f'border-right:1px solid #ececef;">'
            f'<div style="font-size:10px;font-weight:600;color:#8e8e93;'
            f'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">'
            f'{icon_html}{label}</div>'
            f'<div style="font-size:18px;color:#1d1d1f;font-weight:600;">{val_str or "—"}</div>'
            f'</td>'
        )

    # 按列数分行
    rows_html = []
    for i in range(0, len(cells_html), columns):
        row_cells = cells_html[i:i + columns]
        # 不足一行时填空 cell 占位
        while len(row_cells) < columns:
            row_cells.append(f'<td width="{cell_w:.2f}%"></td>')
        rows_html.append(f'<tr>{"".join(row_cells)}</tr>')

    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:8px 0 12px;background:#fafafa;border:1px solid #ececef;'
        f'border-radius:10px;border-collapse:separate;overflow:hidden;">'
        f'{"".join(rows_html)}'
        f'</table>\n'
    )


# ---------------------------------------------------------------------------
# file_tree —— 文件 / 目录树
# ---------------------------------------------------------------------------
def render_file_tree(props: dict, payload: dict) -> str:
    """从 payload[sourceKey] 读取扁平或嵌套文件列表，渲染缩进树。

    支持两种数据格式：
    - 扁平：[{"path": "a/b.zip", "size_text": "12 MB", "status": "kept"}, ...]
    - 嵌套：[{"name": "a", "children": [...]}, ...]

    status: kept / filtered / new / removed —— 影响行颜色
    title: 顶部标题
    maxItems: 最多显示行数，超出折叠为"...还有 N 项"
    """
    source_key = props.get("sourceKey") or "file_tree"
    title = _esc(props.get("title") or "文件清单")
    max_items = max(0, int(props.get("maxItems", 30) or 30))
    items = payload.get(source_key) or []
    if not items:
        return (
            f'<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;'
            f'border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">'
            f'{title}：（无数据）</div>\n'
        )

    # 状态色
    status_colors = {
        "kept":     ("#1f8f4e", "✓"),
        "filtered": ("#d97706", "✕"),
        "new":      ("#0071e3", "+"),
        "removed":  ("#d93025", "−"),
    }

    # 扁平化（嵌套 → 扁平 + indent）
    flat = []
    def _walk(nodes, depth=0):
        for n in nodes:
            if isinstance(n, dict) and "children" in n:
                flat.append({
                    "label": n.get("name") or n.get("path") or "",
                    "size":  n.get("size_text") or "",
                    "status": n.get("status") or "kept",
                    "depth": depth,
                    "is_dir": True,
                })
                _walk(n.get("children") or [], depth + 1)
            else:
                flat.append({
                    "label": (n.get("path") or n.get("name") or "") if isinstance(n, dict) else str(n),
                    "size":  (n.get("size_text") or "") if isinstance(n, dict) else "",
                    "status": (n.get("status") or "kept") if isinstance(n, dict) else "kept",
                    "depth": depth,
                    "is_dir": False,
                })
    _walk(items)

    truncated = False
    if len(flat) > max_items:
        flat = flat[:max_items]
        truncated = True

    rows = []
    for it in flat:
        color, marker = status_colors.get(it["status"], ("#48484a", "·"))
        indent_px = 16 + it["depth"] * 18
        weight = "600" if it["is_dir"] else "400"
        rows.append(
            f'<tr><td style="padding:5px 12px 5px {indent_px}px;font-size:12.5px;'
            f'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#1d1d1f;'
            f'border-bottom:1px solid #f5f5f7;font-weight:{weight};">'
            f'<span style="color:{color};display:inline-block;width:14px;'
            f'font-weight:600;">{marker}</span>'
            f'{_esc(it["label"])}'
            f'</td>'
            f'<td align="right" style="padding:5px 12px;font-size:11px;'
            f'color:#8e8e93;border-bottom:1px solid #f5f5f7;'
            f'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">'
            f'{_esc(it["size"])}</td></tr>'
        )

    if truncated:
        rows.append(
            f'<tr><td colspan="2" style="padding:8px 14px;font-size:11px;'
            f'color:#8e8e93;text-align:center;font-style:italic;">'
            f'... 还有 {len(payload.get(source_key) or []) - max_items} 项未显示'
            f'</td></tr>'
        )

    return (
        f'<div style="margin:10px 0;">'
        f'<div style="font-size:11px;font-weight:600;color:#8e8e93;'
        f'letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;'
        f'padding:0 4px;">{title}</div>'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#fff;border:1px solid #ececef;border-radius:10px;'
        f'overflow:hidden;border-collapse:separate;">'
        f'{"".join(rows)}'
        f'</table></div>\n'
    )


# ---------------------------------------------------------------------------
# diff_view —— 新旧对比差异
# ---------------------------------------------------------------------------
def render_diff_view(props: dict, payload: dict) -> str:
    """从 payload[sourceKey] 读取差异列表，渲染左右对比卡片。

    数据格式：
    [
      {"label": "标题", "old": "旧值", "new": "新值", "changed": true},
      ...
    ]
    """
    source_key = props.get("sourceKey") or "diff_items"
    title = _esc(props.get("title") or "数据差异")
    items = payload.get(source_key) or []
    if not items:
        return (
            f'<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;'
            f'border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">'
            f'{title}：（无差异）</div>\n'
        )

    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        label = _esc(it.get("label") or "")
        old_v = _esc(str(it.get("old") or "")) or '<span style="color:#c7c7cc;">—</span>'
        new_v = _esc(str(it.get("new") or "")) or '<span style="color:#c7c7cc;">—</span>'
        changed = bool(it.get("changed", old_v != new_v))
        new_bg = "background:#e8f5ee;color:#1f8f4e;" if changed else "color:#1d1d1f;"
        old_bg = "background:#fef0e6;color:#d97706;text-decoration:line-through;" if changed else "color:#8e8e93;"
        rows.append(
            f'<tr>'
            f'<td valign="top" style="padding:10px 14px;width:120px;font-size:11.5px;'
            f'color:#48484a;font-weight:500;border-bottom:1px solid #f5f5f7;">{label}</td>'
            f'<td valign="top" style="padding:10px 8px;font-size:12.5px;'
            f'border-bottom:1px solid #f5f5f7;">'
            f'<span style="display:inline-block;padding:2px 7px;border-radius:4px;'
            f'{old_bg}font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{old_v}</span>'
            f'</td>'
            f'<td valign="middle" style="padding:10px 4px;font-size:14px;color:#c7c7cc;'
            f'border-bottom:1px solid #f5f5f7;width:20px;text-align:center;">→</td>'
            f'<td valign="top" style="padding:10px 14px 10px 8px;font-size:12.5px;'
            f'border-bottom:1px solid #f5f5f7;">'
            f'<span style="display:inline-block;padding:2px 7px;border-radius:4px;'
            f'{new_bg}font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:500;">{new_v}</span>'
            f'</td></tr>'
        )

    return (
        f'<div style="margin:10px 0;">'
        f'<div style="font-size:11px;font-weight:600;color:#8e8e93;'
        f'letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;'
        f'padding:0 4px;">{title}</div>'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#fff;border:1px solid #ececef;border-radius:10px;'
        f'border-collapse:separate;overflow:hidden;">'
        f'{"".join(rows)}'
        f'</table></div>\n'
    )


# ---------------------------------------------------------------------------
# task_log —— 最近日志摘录
# ---------------------------------------------------------------------------
def render_task_log(props: dict, payload: dict) -> str:
    """从 payload[sourceKey] 读取日志行数组，渲染等宽字体黑底日志。

    数据：[{"level": "info|warn|error", "text": "...", "ts": "12:34:56"}, ...]
    或简单字符串数组：["...", "..."]
    """
    source_key = props.get("sourceKey") or "recent_logs"
    title = _esc(props.get("title") or "执行日志")
    max_lines = max(1, int(props.get("maxLines", 12) or 12))
    items = payload.get(source_key) or []
    if not items:
        return (
            f'<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;'
            f'border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">'
            f'{title}：（无日志）</div>\n'
        )

    visible = items[-max_lines:]
    level_colors = {
        "info":  "#a1a1a6",
        "warn":  "#d97706",
        "error": "#ff6b6b",
        "debug": "#6e6e73",
    }
    rows = []
    for it in visible:
        if isinstance(it, dict):
            level = (it.get("level") or "info").lower()
            text = _esc(it.get("text") or "")
            ts = _esc(it.get("ts") or "")
        else:
            level, text, ts = "info", _esc(str(it)), ""
        color = level_colors.get(level, "#a1a1a6")
        ts_html = f'<span style="color:#6e6e73;margin-right:8px;">{ts}</span>' if ts else ""
        rows.append(
            f'<div style="padding:2px 0;color:{color};">{ts_html}{text}</div>'
        )

    truncated_html = ""
    if len(items) > max_lines:
        truncated_html = (
            f'<div style="padding:6px 0 0 0;color:#6e6e73;font-style:italic;'
            f'font-size:10.5px;">…（仅显示最后 {max_lines} 行，共 {len(items)} 行）</div>'
        )

    return (
        f'<div style="margin:10px 0;">'
        f'<div style="font-size:11px;font-weight:600;color:#8e8e93;'
        f'letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;'
        f'padding:0 4px;">{title}</div>'
        f'<div style="background:#1d1d1f;border-radius:10px;padding:14px 16px;'
        f'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;'
        f'line-height:1.55;color:#a1a1a6;overflow:hidden;">'
        f'{"".join(rows)}'
        f'{truncated_html}'
        f'</div></div>\n'
    )


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
BLOCK_RENDERERS = {
    "header_status": render_header_status,
    "summary_card":  render_summary_card,
    "rich_text":     render_rich_text,
    "divider":       render_divider,
    "spacer":        render_spacer,
    "stats_grid":    render_stats_grid,
    "file_tree":     render_file_tree,
    "diff_view":     render_diff_view,
    "task_log":      render_task_log,
}


# ---------------------------------------------------------------------------
# 对外 Schema（供 GET /api/notifications/blocks/schema 使用）
# ---------------------------------------------------------------------------
BLOCK_SCHEMA = [
    {
        "type": "header_status",
        "label": "状态头部",
        "description": "顶部状态颜色区块，包含标题和摘要",
        "group": "layout",
        "defaultProps": {
            "titleKey":    "任务标题",
            "summaryKey":  "摘要",
            "severityKey": "严重程度",
        },
        "propSchema": [
            {"key": "titleKey",    "label": "标题变量",   "type": "variable", "default": "任务标题"},
            {"key": "summaryKey",  "label": "摘要变量",   "type": "variable", "default": "摘要"},
            {"key": "severityKey", "label": "颜色变量",   "type": "variable", "default": "严重程度"},
        ],
    },
    {
        "type": "summary_card",
        "label": "摘要卡片",
        "description": "带侧边颜色条的摘要信息卡片",
        "group": "content",
        "defaultProps": {
            "label":       "任务摘要",
            "valueKey":    "摘要",
            "accentColor": "#0071e3",
        },
        "propSchema": [
            {"key": "label",       "label": "标签文字",   "type": "text",     "default": "任务摘要"},
            {"key": "valueKey",    "label": "内容变量",   "type": "variable", "default": "摘要"},
            {"key": "accentColor", "label": "强调色",     "type": "color",    "default": "#0071e3"},
        ],
    },
    {
        "type": "rich_text",
        "label": "富文本",
        "description": "支持格式化的文本内容，可插入 {变量}",
        "group": "content",
        "defaultProps": {
            "contentJson": None,
            "htmlCache":   "",
        },
        "propSchema": [
            {"key": "contentJson", "label": "富文本内容", "type": "richtext"},
            {"key": "htmlCache",   "label": "HTML 缓存",  "type": "hidden"},
        ],
    },
    {
        "type": "divider",
        "label": "分割线",
        "description": "水平分割线",
        "group": "layout",
        "defaultProps": {
            "color":  "#e5e5ea",
            "margin": 16,
        },
        "propSchema": [
            {"key": "color",  "label": "颜色",       "type": "color",  "default": "#e5e5ea"},
            {"key": "margin", "label": "上下间距(px)","type": "number", "min": 0, "max": 64, "default": 16},
        ],
    },
    {
        "type": "spacer",
        "label": "间距块",
        "description": "空白间距占位",
        "group": "layout",
        "defaultProps": {
            "height": 16,
        },
        "propSchema": [
            {"key": "height", "label": "高度(px)", "type": "number", "min": 4, "max": 120, "default": 16},
        ],
    },
    # ─── 业务数据块 ─────────────────────────────────────────────
    {
        "type": "stats_grid",
        "label": "统计网格",
        "description": "多列数字统计（总文件数 / 总大小 / 成功率等）",
        "group": "data",
        "defaultProps": {
            "columns": 3,
            "items": [
                {"key": "total_files", "label": "总文件数", "icon": "📁"},
                {"key": "total_size",  "label": "总大小",   "icon": "💾"},
                {"key": "duration",    "label": "耗时",     "icon": "⏱"},
            ],
        },
        "propSchema": [
            {"key": "columns", "label": "每行列数", "type": "number", "min": 1, "max": 4, "default": 3},
            {"key": "items",   "label": "字段配置", "type": "stats_items"},
        ],
    },
    {
        "type": "file_tree",
        "label": "文件树",
        "description": "文件 / 目录树（上下载、解压过滤场景）",
        "group": "data",
        "defaultProps": {
            "title":     "文件清单",
            "sourceKey": "file_tree",
            "maxItems":  30,
        },
        "propSchema": [
            {"key": "title",     "label": "标题",       "type": "text",   "default": "文件清单"},
            {"key": "sourceKey", "label": "数据来源 key","type": "data_source",
             "default": "file_tree",
             "options": [
                 {"value": "file_tree",      "label": "通用文件树（file_tree）"},
                 {"value": "download_files", "label": "下载文件列表"},
                 {"value": "upload_files",   "label": "上传文件列表"},
                 {"value": "filtered_files", "label": "过滤前后对比"},
                 {"value": "extracted_files","label": "解压结果"},
             ]},
            {"key": "maxItems",  "label": "最多显示行数","type": "number", "min": 5, "max": 200, "default": 30},
        ],
    },
    {
        "type": "diff_view",
        "label": "差异对比",
        "description": "新旧值对比（社团补全 / 字幕匹配场景）",
        "group": "data",
        "defaultProps": {
            "title":     "数据差异",
            "sourceKey": "diff_items",
        },
        "propSchema": [
            {"key": "title",     "label": "标题",        "type": "text", "default": "数据差异"},
            {"key": "sourceKey", "label": "数据来源 key", "type": "data_source",
             "default": "diff_items",
             "options": [
                 {"value": "diff_items",       "label": "通用差异（diff_items）"},
                 {"value": "circle_diff",      "label": "社团补全差异"},
                 {"value": "subtitle_diff",    "label": "字幕配对差异"},
                 {"value": "metadata_diff",    "label": "元数据差异"},
             ]},
        ],
    },
    {
        "type": "task_log",
        "label": "执行日志",
        "description": "最近 N 行任务执行日志（黑底等宽字体）",
        "group": "data",
        "defaultProps": {
            "title":     "执行日志",
            "sourceKey": "recent_logs",
            "maxLines":  12,
        },
        "propSchema": [
            {"key": "title",     "label": "标题",       "type": "text",   "default": "执行日志"},
            {"key": "sourceKey", "label": "数据来源 key","type": "data_source",
             "default": "recent_logs",
             "options": [
                 {"value": "recent_logs",  "label": "通用最近日志（recent_logs）"},
                 {"value": "error_logs",   "label": "错误日志"},
                 {"value": "warning_logs", "label": "警告日志"},
             ]},
            {"key": "maxLines",  "label": "最多行数",   "type": "number", "min": 3, "max": 50, "default": 12},
        ],
    },
]
