import html
import logging
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_SEVERITY_COLORS = {
    'success': '#1f8f4e',
    'danger': '#d93025',
    'warning': '#d97706',
    'info': '#0071e3',
}

_EVENT_ICONS = {
    'completed': '✅',
    'failed': '❌',
    'waiting_manual': '⚠️',
}

_EVENT_LABELS = {
    'completed': '任务完成',
    'failed': '任务失败',
    'waiting_manual': '等待人工处理',
}

_DEFAULT_SUBJECT = {
    'completed': '[Prekikoeru] {任务类型}任务完成 — {任务标题}',
    'failed': '[Prekikoeru] {任务类型}任务失败 — {任务标题}',
    'waiting_manual': '[Prekikoeru] 等待人工处理 — {任务标题}',
}

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:#f5f5f7;color:#1d1d1f}}
.wrap{{max-width:600px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 24px rgba(0,0,0,.1)}}
.hd{{padding:28px 36px;background:{header_bg};color:#fff}}
.hd h1{{font-size:20px;font-weight:600;margin-bottom:6px}}
.hd p{{font-size:13px;opacity:.88;line-height:1.5}}
.bd{{padding:28px 36px}}
.row{{display:flex;gap:12px;margin-bottom:10px;align-items:flex-start}}
.lbl{{font-size:12px;color:#8e8e93;min-width:72px;padding-top:1px}}
.val{{font-size:14px;color:#1d1d1f;font-weight:500;word-break:break-all}}
.badge{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600;background:{badge_bg};color:{badge_fg}}}
.ft{{padding:16px 36px;background:#f5f5f7;font-size:11px;color:#8e8e93;text-align:center;line-height:1.5}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>{event_icon} {event_label}</h1>
    <p>{summary}</p>
  </div>
  <div class="bd">
    <div class="row"><span class="lbl">任务名称</span><span class="val">{title}</span></div>
    <div class="row"><span class="lbl">类型</span><span class="val">{domain_label}</span></div>
    {rjcode_row}
    <div class="row"><span class="lbl">状态</span><span class="val"><span class="badge">{event_label}</span></span></div>
    <div class="row"><span class="lbl">时间</span><span class="val">{created_at}</span></div>
  </div>
  <div class="ft">此邮件由 Prekikoeru 自动发出，请勿回复。</div>
</div>
</body>
</html>"""


def _esc(value) -> str:
    return html.escape(str(value or ''))


def render_builtin_email(payload: dict) -> tuple:
    """用内置模板渲染邮件，返回 (subject, html_body, text_body)"""
    event_type = payload.get('event_type', 'completed')
    title = _esc(payload.get('title', '未知任务'))
    domain_label = _esc(payload.get('domain_label', '任务'))
    summary = _esc(payload.get('summary', ''))
    rjcode = _esc(payload.get('rjcode', ''))
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    header_bg = _SEVERITY_COLORS.get({'completed': 'success', 'failed': 'danger', 'waiting_manual': 'warning'}.get(event_type, 'info'), '#0071e3')
    badge_bg = header_bg + '22'
    badge_fg = header_bg
    event_icon = _EVENT_ICONS.get(event_type, '')
    event_label = _EVENT_LABELS.get(event_type, event_type)
    rjcode_row = f'<div class="row"><span class="lbl">RJ 号</span><span class="val">{rjcode}</span></div>' if rjcode else ''
    subject_tpl = _DEFAULT_SUBJECT.get(event_type, '[Prekikoeru] 任务通知 — {title}')
    subject = subject_tpl.format(domain_label=payload.get('domain_label', ''), title=payload.get('title', ''))
    html_body = _HTML_TEMPLATE.format(
        header_bg=header_bg,
        badge_bg=badge_bg,
        badge_fg=badge_fg,
        event_icon=event_icon,
        event_label=event_label,
        summary=summary,
        title=title,
        domain_label=domain_label,
        rjcode_row=rjcode_row,
        created_at=created_at,
    )
    text_body = f"{event_icon} {event_label}\n\n任务名称：{payload.get('title','')}\n类型：{payload.get('domain_label','')}\n{('RJ 号：' + payload.get('rjcode','') + chr(10)) if payload.get('rjcode') else ''}时间：{created_at}\n\n此邮件由 Prekikoeru 自动发出。"
    return subject, html_body, text_body


def render_email_for_outbox(payload: dict) -> tuple:
    """为 outbox 条目渲染邮件内容，优先使用数据库用户模板，否则用内置

    选模板规则（按优先级）：
    1. 同时命中 event_type 与当前 domain（task_domains 包含该 domain）的"专用模板"
    2. 命中 event_type 且 task_domains 为空的"通用模板"
    3. 内置模板
    同优先级下取 is_default=True 优先，其次按 sort_order。
    """
    from ..models.database import SessionLocal, NotificationTemplate
    event_type = payload.get('event_type', 'completed')
    domain = payload.get('domain', '') or ''
    db = SessionLocal()
    try:
        candidates = (
            db.query(NotificationTemplate)
            .filter(
                NotificationTemplate.enabled == True,
                NotificationTemplate.event_types.contains([event_type]),
            )
            .order_by(NotificationTemplate.is_default.desc(), NotificationTemplate.sort_order)
            .all()
        )
        domain_specific = None
        generic = None
        for tpl in candidates:
            domains = tpl.task_domains or []
            if domain and domain in domains and domain_specific is None:
                domain_specific = tpl
            elif not domains and generic is None:
                generic = tpl
        chosen = domain_specific or generic
        if chosen:
            if chosen.editor_mode == 'blocks' and chosen.blocks:
                # 把模板自定义 subject 透传给 render_blocks_email
                payload_with_subject = dict(payload)
                if chosen.subject_template:
                    payload_with_subject['_subject_template'] = chosen.subject_template
                return render_blocks_email(chosen.blocks or [], payload_with_subject)
            elif chosen.html_template:
                return _render_user_template(chosen, payload)
    except Exception:
        logger.warning("[通知模板] 选模板失败，回退内置", exc_info=True)
    finally:
        db.close()
    return render_builtin_email(payload)


def _render_user_template(tpl, payload: dict) -> tuple:
    variables = {
        'title': payload.get('title', ''),
        'domain_label': payload.get('domain_label', ''),
        'summary': payload.get('summary', ''),
        'rjcode': payload.get('rjcode', ''),
        'event_label': _EVENT_LABELS.get(payload.get('event_type', ''), ''),
        'event_icon': _EVENT_ICONS.get(payload.get('event_type', ''), ''),
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    safe_vars = {k: _esc(v) for k, v in variables.items()}
    subject = (tpl.subject_template or '').format_map(safe_vars)
    html_body = (tpl.html_template or '').format_map(safe_vars)
    text_body = (tpl.text_template or '').format_map(safe_vars) or variables.get('summary', '')
    return subject, html_body, text_body


def list_templates() -> list:
    from ..models.database import SessionLocal, NotificationTemplate
    db = SessionLocal()
    try:
        items = db.query(NotificationTemplate).order_by(NotificationTemplate.sort_order, NotificationTemplate.created_at).all()
        return [i.to_dict() for i in items]
    finally:
        db.close()


def get_template(template_id: str) -> Optional[dict]:
    from ..models.database import SessionLocal, NotificationTemplate
    db = SessionLocal()
    try:
        item = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
        return item.to_dict() if item else None
    finally:
        db.close()


def create_template(data: dict) -> dict:
    from ..models.database import SessionLocal, NotificationTemplate
    db = SessionLocal()
    try:
        item = NotificationTemplate(
            id=str(uuid.uuid4()),
            name=data.get('name', '新模板'),
            channel=data.get('channel', 'email'),
            event_types=data.get('event_types', []),
            task_domains=data.get('task_domains', []),
            editor_mode=data.get('editor_mode', 'html'),
            blocks=data.get('blocks', []),
            subject_template=data.get('subject_template', ''),
            html_template=data.get('html_template', ''),
            text_template=data.get('text_template', ''),
            enabled=data.get('enabled', True),
            is_default=data.get('is_default', False),
            sort_order=data.get('sort_order', 0),
            description=data.get('description', ''),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.to_dict()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_template(template_id: str, data: dict) -> Optional[dict]:
    from ..models.database import SessionLocal, NotificationTemplate
    db = SessionLocal()
    try:
        item = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
        if not item:
            return None
        for field in ('name', 'channel', 'event_types', 'task_domains', 'editor_mode',
                      'blocks', 'subject_template', 'html_template', 'text_template', 'enabled',
                      'is_default', 'sort_order', 'description'):
            if field in data:
                setattr(item, field, data[field])
        db.commit()
        db.refresh(item)
        return item.to_dict()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_template(template_id: str) -> bool:
    from ..models.database import SessionLocal, NotificationTemplate
    db = SessionLocal()
    try:
        item = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
        if not item:
            return False
        db.delete(item)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def preview_template(template_id: Optional[str], payload: dict) -> dict:
    """预览模板渲染结果"""
    if template_id:
        from ..models.database import SessionLocal, NotificationTemplate
        db = SessionLocal()
        try:
            tpl = db.query(NotificationTemplate).filter(NotificationTemplate.id == template_id).first()
            if tpl:
                subject, html_body, text_body = _render_user_template(tpl, payload)
                return {'subject': subject, 'html': html_body, 'text': text_body}
        finally:
            db.close()
    subject, html_body, text_body = render_builtin_email(payload)
    return {'subject': subject, 'html': html_body, 'text': text_body}


# ---------------------------------------------------------------------------
# Block 编辑器渲染
# ---------------------------------------------------------------------------

_EMAIL_ENVELOPE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:#f5f5f7;color:#1d1d1f}}
.wrap{{max-width:600px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 24px rgba(0,0,0,.1)}}
.body-pad{{padding:28px 36px}}
.ft{{padding:16px 36px;background:#f5f5f7;font-size:11px;color:#8e8e93;text-align:center;line-height:1.5}}
</style>
</head>
<body>
<div class="wrap">
<div class="body-pad">
{content}
</div>
<div class="ft">此邮件由 Prekikoeru 自动发出，请勿回复。</div>
</div>
</body>
</html>"""


def render_blocks_email(blocks: list, payload: dict) -> tuple:
    """将 blocks 数组渲染成 (subject, html_body, text_body)。

    subject 从 payload 中提取，或使用默认模板。
    """
    from ..core.block_renderers import BLOCK_RENDERERS
    from ..core.html_sanitizer import sanitize_html

    event_type = payload.get('event_type', 'completed')

    # 拼装 payload 补充字段
    enriched = dict(payload)
    if 'event_label' not in enriched:
        enriched['event_label'] = _EVENT_LABELS.get(event_type, event_type)
    if 'event_icon' not in enriched:
        enriched['event_icon'] = _EVENT_ICONS.get(event_type, '')
    if 'severity' not in enriched:
        enriched['severity'] = {'completed': 'success', 'failed': 'danger', 'waiting_manual': 'warning'}.get(event_type, 'info')
    if 'created_at_text' not in enriched:
        enriched['created_at_text'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    html_parts = []
    for block in blocks:
        if not block.get('enabled', True):
            continue
        renderer = BLOCK_RENDERERS.get(block.get('type', ''))
        if renderer:
            html_parts.append(renderer(block.get('props', {}), enriched))

    inner_html = sanitize_html(''.join(html_parts))
    html_body = _EMAIL_ENVELOPE.format(content=inner_html)

    # 主题：优先使用模板自定义的 subject_template；否则用事件默认。
    # 主题里所有 {var} 都通过 substitute_variables 解析，未注册的占位会保留原文。
    from ..core.variable_registry import substitute_variables as _subst
    subject_template = (payload.get('_subject_template') or '').strip() or _DEFAULT_SUBJECT.get(
        event_type, '[Prekikoeru] 任务通知 — {title}'
    )
    subject = _subst(subject_template, enriched, escape=False)

    text_body = f"{enriched['event_icon']} {enriched['event_label']}\n\n" \
                f"任务名称：{payload.get('title', '')}\n" \
                f"类型：{payload.get('domain_label', '')}\n" \
                f"{('RJ 号：' + payload.get('rjcode', '') + chr(10)) if payload.get('rjcode') else ''}" \
                f"时间：{enriched['created_at_text']}\n\n此邮件由 Prekikoeru 自动发出。"
    return subject, html_body, text_body


def preview_blocks(
    blocks: list,
    event_type: str = 'completed',
    domain: str = 'import',
    subject_template: str = '',
) -> dict:
    """用 blocks + 示例 payload 渲染预览，返回 {subject, html, text}。

    subject_template 可选；若提供，则用它生成预览主题，否则使用事件默认主题。
    """
    from ..core.variable_registry import build_sample_payload
    payload = build_sample_payload(event_type=event_type, domain=domain)
    if subject_template:
        payload['_subject_template'] = subject_template
    subject, html_body, text_body = render_blocks_email(blocks, payload)
    return {'subject': subject, 'html': html_body, 'text': text_body}

