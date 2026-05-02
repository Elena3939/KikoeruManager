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
    maxItems: 保留参数但不再截断，有多少显示多少（设极大值或不传均可）
    顶层目录（根节点）默认收缩，子目录/文件默认展开。
    """
    source_key = props.get("sourceKey") or "file_tree"
    title = _esc(props.get("title") or "文件清单")
    # upload_files 场景：file_tree 不存在时 fallback 到 upload_files
    if source_key == "file_tree" and not payload.get("file_tree") and payload.get("upload_files"):
        source_key = "upload_files"
    if source_key == "file_tree" and not payload.get("file_tree") and payload.get("circle_batch_summary"):
        source_key = "circle_batch_summary"
        title = "批量社团补全汇总"
    if source_key == "circle_batch_summary":
        return _render_circle_batch_summary_table(title, payload.get("circle_batch_summary") or [])
    if source_key == "rj_work_cards":
        return _render_download_work_cards(title, payload.get("rj_work_cards") or [], 9999)
    items = payload.get(source_key) or []
    card_html = ""
    if source_key == "download_files" and payload.get("download_work_cards"):
        card_html = _render_download_work_cards(title, payload.get("download_work_cards") or [], 9999)
    if not items:
        return (
            f'<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;'
            f'border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">'
            f'{title}：（无数据）</div>\n'
        )

    # 状态色 + 文本样式（filtered/removed 加 line-through 与任务详情面板对齐）
    status_styles = {
        "kept":     {"color": "#1f8f4e", "marker": "✓", "label_extra": "color:#1d1d1f;"},
        "filtered": {"color": "#d97706", "marker": "✕", "label_extra": "color:rgba(29,29,31,0.45);text-decoration:line-through;text-decoration-thickness:1.5px;text-decoration-color:rgba(29,29,31,0.5);"},
        "new":      {"color": "#0071e3", "marker": "+", "label_extra": "color:#1d1d1f;"},
        "removed":  {"color": "#d93025", "marker": "−", "label_extra": "color:rgba(29,29,31,0.45);text-decoration:line-through;text-decoration-thickness:1.5px;text-decoration-color:rgba(29,29,31,0.5);"},
    }

    # badge 样式（与活动详情页 .entry-inline-badge 视觉对齐）
    BADGE_STYLE_MAP = {
        "已上传":   "background:#dcfce7;color:#166534;border:1px solid #86efac;",
        "下载失败": "background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;",
    }
    DEFAULT_BADGE_STYLE = "background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;"

    def _render_badges(badges):
        if not badges:
            return ""
        chunks = []
        for b in badges:
            text = str(b or "").strip()
            if not text:
                continue
            extra = BADGE_STYLE_MAP.get(text, DEFAULT_BADGE_STYLE)
            chunks.append(
                f'<span style="display:inline-block;margin-left:6px;padding:1px 6px;'
                f'border-radius:5px;font-size:10.5px;font-weight:600;line-height:1.5;'
                f'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;'
                f'{extra}">{_esc(text)}</span>'
            )
        return "".join(chunks)

    # 邮件端尽量复刻任务中心 TaskDetailPane 的文件树：
    # 白底卡片、行式树、左侧 20px expander 占位、图标 + 名称 + 右侧大小。
    # 邮件客户端不可靠支持交互，所以全部展开；过滤/删除只做灰色删除线。
    row_base_style = (
        "min-height:32px;margin:0 0 7px 0;padding:6px 10px 6px 8px;"
        "border:1px solid transparent;border-radius:6px;color:#1e293b;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;"
        "font-size:14px;font-weight:500;line-height:1.25;"
    )
    tree_name_base = (
        "display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;"
        "white-space:nowrap;vertical-align:middle;color:currentColor;"
    )

    def _file_row_html(node):
        label = str(node.get("path") or node.get("name") or "")
        status = str(node.get("status") or "kept")
        is_muted = status in {"filtered", "removed"}
        row_color = "#94a3b8" if is_muted else "#1e293b"
        label_extra = (
            "color:#94a3b8;text-decoration:line-through;"
            "text-decoration-color:rgba(148,163,184,.86);text-decoration-thickness:1.5px;"
            if is_muted else "color:#1e293b;"
        )
        icon_color = "#94a3b8" if is_muted else (
            "#2563eb" if label.lower().endswith((".flac", ".wav")) else
            "#7c3aed" if label.lower().endswith((".mp3", ".m4a", ".ogg", ".aac", ".wma")) else
            "#64748b" if label.lower().endswith((".txt", ".lrc", ".srt", ".vtt", ".ass", ".ssa", ".cue", ".json", ".md")) else
            "#94a3b8"
        )
        icon_html = (
            f'<span style="display:inline-block;width:20px;text-align:center;color:{icon_color};font-size:17px;line-height:1;vertical-align:middle;">'
            f'{"♫" if label.lower().endswith((".flac", ".wav", ".mp3", ".m4a", ".ogg", ".aac", ".wma")) else "□"}'
            f'</span>'
        )
        size_text = str(node.get("size_text") or "")
        size_html = (
            f'<td style="width:86px;padding-left:16px;color:#94a3b8;font-size:12px;'
            f'font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap;">{_esc(size_text)}</td>'
            if size_text else ""
        )
        badge_html = _render_badges(node.get("badges") or [])
        return (
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;{row_base_style}color:{row_color};">'
            f'<tr>'
            f'<td style="width:20px;color:#38bdf8;font-size:14px;text-align:center;vertical-align:middle;">&nbsp;</td>'
            f'<td style="vertical-align:middle;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f'{icon_html}'
            f'<span style="{tree_name_base}{label_extra}">{_esc(label)}</span>'
            f'{badge_html}'
            f'</td>'
            f'{size_html}'
            f'</tr>'
            f'</table>'
        )

    def _dir_html(node, depth):
        label = str(node.get("name") or node.get("path") or "")
        dir_status = str(node.get("status") or "kept")
        is_muted = dir_status in {"filtered", "removed"}
        dir_color = "#94a3b8" if is_muted else "#1e293b"
        dir_label_extra = (
            "color:#94a3b8;text-decoration:line-through;"
            "text-decoration-color:rgba(148,163,184,.86);text-decoration-thickness:1.5px;"
            if is_muted else "color:#1e293b;"
        )
        folder_icon = (
            f'<span style="display:inline-block;width:20px;text-align:center;color:{"#94a3b8" if is_muted else "#f6b73c"};'
            f'font-size:16px;line-height:1;vertical-align:middle;">▰</span>'
        )
        size_text = str(node.get("size_text") or "")
        size_html = (
            f'<td style="width:86px;padding-left:16px;color:#94a3b8;font-size:12px;'
            f'font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap;">{_esc(size_text)}</td>'
            if size_text else ""
        )
        badge_html = _render_badges(node.get("badges") or [])
        children = node.get("children") or []
        children_html_chunks = [
            _dir_html(child, depth + 1) if isinstance(child, dict) and "children" in child
            else _file_row_html(child if isinstance(child, dict) else {"path": str(child)})
            for child in children
        ]
        indent = max(0, depth) * 18
        row_html = (
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;{row_base_style}color:{dir_color};">'
            f'<tr>'
            f'<td style="width:20px;color:#38bdf8;font-size:14px;text-align:center;vertical-align:middle;">›</td>'
            f'<td style="vertical-align:middle;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f'{folder_icon}'
            f'<span style="{tree_name_base}{dir_label_extra}">{_esc(label)}</span>'
            f'{badge_html}'
            f'</td>'
            f'{size_html}'
            f'</tr>'
            f'</table>'
        )
        children_wrapper = (
            f'<div style="padding-left:18px;border-left:1px dashed #dbe5f0;margin-left:22px;background:#fff;">'
            f'{"".join(children_html_chunks)}'
            f'</div>'
            if children_html_chunks else ""
        )
        return (
            f'<div style="margin-left:{indent}px;">'
            f'{row_html}'
            f'{children_wrapper}'
            f'</div>'
        )

    body_chunks = []
    for n in items:
        if isinstance(n, dict) and "children" in n:
            body_chunks.append(_dir_html(n, 0))
        else:
            body_chunks.append(_file_row_html(n if isinstance(n, dict) else {"path": str(n)}))

    tree_html = (
        f'<div style="margin:10px 0;">'
        f'<div style="font-size:11px;font-weight:600;color:#64748b;'
        f'letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;'
        f'padding:0 4px;">{title}</div>'
        f'<div style="background:linear-gradient(180deg,#ffffff 0%,#fbfdff 100%);border:1px solid #dde6f0;border-radius:12px;'
        f'overflow:hidden;box-shadow:0 8px 24px rgba(15,23,42,0.06);">'
        f'{"".join(body_chunks)}'
        f'</div></div>\n'
    )
    return card_html + tree_html


def _render_circle_batch_summary_table(title: str, items: list) -> str:
    rows = []
    for item in items[:80]:
        if not isinstance(item, dict):
            continue
        success = bool(item.get("success", True))
        status_text = "完成" if success else "失败"
        status_color = "#16a34a" if success else "#dc2626"
        circle_name = _esc(item.get("circle_name") or item.get("circle_query") or item.get("circle_id") or "未知社团")
        rows.append(
            f'<tr>'
            f'<td style="padding:11px 12px;border-bottom:1px solid #edf0f4;color:#20242b;font-size:13px;font-weight:650;line-height:1.45;">{circle_name}</td>'
            f'<td style="padding:11px 10px;border-bottom:1px solid #edf0f4;color:#475569;font-size:12px;text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(item.get("kikoeru_owned_count") or 0)}</td>'
            f'<td style="padding:11px 10px;border-bottom:1px solid #edf0f4;color:#475569;font-size:12px;text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(item.get("dl_count") or 0)}</td>'
            f'<td style="padding:11px 10px;border-bottom:1px solid #edf0f4;color:#475569;font-size:12px;text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(item.get("downloadable_count") or 0)}</td>'
            f'<td style="padding:11px 10px;border-bottom:1px solid #edf0f4;color:#475569;font-size:12px;text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(item.get("missing_count") or 0)}</td>'
            f'<td style="padding:11px 12px;border-bottom:1px solid #edf0f4;text-align:center;"><span style="display:inline-block;padding:3px 8px;border-radius:999px;background:{status_color}14;color:{status_color};font-size:11px;font-weight:700;">{_esc(status_text)}</span></td>'
            f'</tr>'
        )
    if not rows:
        return (
            f'<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;'
            f'border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">'
            f'{title}：（无数据）</div>\n'
        )
    more = ""
    if len(items) > 80:
        more = (
            f'<tr><td colspan="6" style="padding:10px 14px;color:#8b95a5;font-size:12px;text-align:center;">'
            f'还有 {len(items) - 80} 个社团未展示，可在桌面端查看完整记录'
            f'</td></tr>'
        )
    return (
        f'<div style="margin:10px 0;">'
        f'<div style="font-size:11px;font-weight:600;color:#8e8e93;letter-spacing:0.06em;'
        f'text-transform:uppercase;margin-bottom:8px;padding:0 4px;">{_esc(title)}</div>'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border:1px solid #e7eaf0;border-radius:12px;border-collapse:separate;overflow:hidden;">'
        f'<tr>'
        f'<th align="left" style="padding:10px 12px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">社团</th>'
        f'<th style="padding:10px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">KIKOERU</th>'
        f'<th style="padding:10px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">DLSITE</th>'
        f'<th style="padding:10px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">可下载</th>'
        f'<th style="padding:10px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">缺失</th>'
        f'<th style="padding:10px 12px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">状态</th>'
        f'</tr>'
        f'{"".join(rows)}{more}'
        f'</table></div>\n'
    )


def _render_download_work_cards(title: str, items: list, max_items: int) -> str:
    """下载列表专用图文卡片。"""
    rows = []
    shown = 0
    for item in items:
        if shown >= max_items:
            break
        if not isinstance(item, dict):
            continue
        shown += 1
        cover_url = _esc(item.get("cover_url") or "")
        rjcode = _esc(item.get("rjcode") or "RJ")
        work_title = _esc(item.get("title") or rjcode or "下载作品")
        circle_name = _esc(item.get("circle_name") or "")
        size_text = _esc(item.get("size_text") or "")
        file_count = int(item.get("file_count") or 0)
        file_text = _esc(item.get("count_label") or (f"{file_count} 个文件" if file_count else ""))
        meta_chunks = [text for text in [circle_name, size_text, file_text] if text]
        meta_html = " · ".join(meta_chunks) if meta_chunks else "下载完成"
        changes = [str(change or "").strip() for change in (item.get("changes") or []) if str(change or "").strip()]
        changes_html = ""
        if changes:
            changes_html = (
                f'<div style="margin-top:10px;padding:8px 10px;background:#f8fafc;border:1px solid #e2e8f0;'
                f'border-radius:8px;color:#334155;font-size:12px;line-height:1.6;">'
                + "".join(f'<div>{_esc(change)}</div>' for change in changes[:6])
                + f'</div>'
            )
        image_html = (
            f'<img src="{cover_url}" alt="{work_title}" width="180" height="180" '
            f'style="display:block;width:180px;height:180px;object-fit:cover;border:0;">'
            if cover_url else
            f'<div style="width:180px;height:180px;background:#f5f5f7;color:#8e8e93;'
            f'font-size:12px;line-height:180px;text-align:center;">无封面</div>'
        )
        rows.append(
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="margin:0 0 14px;border-collapse:collapse;">'
            f'<tr>'
            f'<td width="180" valign="top" style="padding:0 16px 0 0;">'
            f'<table width="180" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
            f'<tr><td>{image_html}</td></tr>'
            f'<tr><td style="background:#fff3cf;color:#c2410c;font-size:12px;line-height:20px;'
            f'text-align:center;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">{rjcode}</td></tr>'
            f'</table>'
            f'</td>'
            f'<td valign="top" style="padding:2px 0 0 0;">'
            f'<div style="font-size:18px;line-height:1.35;font-weight:700;color:#0f172a;'
            f'margin:0 0 8px 0;">{work_title}</div>'
            f'<div style="font-size:13px;line-height:1.6;color:#475569;margin:0 0 10px 0;">{meta_html}</div>'
            f'<div style="font-size:20px;line-height:1.2;font-weight:700;color:#111827;">{size_text or "大小未知"}</div>'
            f'{changes_html}'
            f'</td>'
            f'</tr>'
            f'</table>'
        )
    if not rows:
        return (
            f'<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;'
            f'border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">'
            f'{title}：（无数据）</div>\n'
        )
    more = max(0, len(items) - shown)
    more_html = (
        f'<div style="padding:8px 14px;font-size:11px;color:#8e8e93;text-align:center;'
        f'font-style:italic;border-top:1px solid #f5f5f7;">... 还有 {more} 项未显示</div>'
        if more else ""
    )
    return (
        f'<div style="margin:10px 0;">'
        f'<div style="font-size:11px;font-weight:600;color:#8e8e93;letter-spacing:0.06em;'
        f'text-transform:uppercase;margin-bottom:8px;padding:0 4px;">{title}</div>'
        f'<div style="background:#fff;border:1px solid #ececef;border-radius:10px;'
        f'padding:14px 14px 0;overflow:hidden;">{"".join(rows)}{more_html}</div>'
        f'</div>\n'
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
    max_lines = max(1, int(props.get("maxLines", 30) or 30))
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
                 {"value": "rj_work_cards",  "label": "RJ 作品卡片"},
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
            "maxLines":  30,
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
            {"key": "maxLines",  "label": "最多行数",   "type": "number", "min": 3, "max": 50, "default": 30},
        ],
    },
]
