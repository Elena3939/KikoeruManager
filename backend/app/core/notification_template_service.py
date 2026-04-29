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

_EMAIL_HEADER_URL = 'https://im.gurl.eu.org/file/AgACAgEAAxkDAAEBgcVp8OfJBO4AAUxLd8WPdMwRLA8TX28AAnsMaxuveYhHvw-4JedMJTcBAAMCAAN3AAM7BA.png'

_DEFAULT_USER_TEMPLATE_NAME = '通用通知 · 极简白'
_DEFAULT_USER_SUBJECT = '[Prekikoeru] {任务类型}{事件名称} · {任务标题}'


def _default_white_template_html() -> str:
    return """<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fa;padding:34px 0;">
<tr><td align="center">
<table width="660" cellpadding="0" cellspacing="0" border="0" style="width:660px;max-width:calc(100% - 28px);background:#ffffff;border:1px solid #e8ebf0;border-radius:18px;border-collapse:separate;overflow:hidden;box-shadow:0 18px 48px rgba(20,24,31,0.08);">
<tr><td style="padding:0;background:#ffffff;"><img src="__HEADER_URL__" alt="Prekikoeru Mail" width="660" style="display:block;width:100%;max-width:660px;height:auto;border:0;outline:none;text-decoration:none;"></td></tr>
<tr><td style="padding:26px 34px 0 34px;background:#ffffff;text-align:center;">
<div style="margin:0 0 12px 0;font-size:13px;line-height:1.5;color:#7b4fb4;font-weight:800;">{事件图标} {事件名称} · {时间}</div>
<h1 style="margin:0;font-size:24px;line-height:1.36;font-weight:760;color:#151922;letter-spacing:0;">{任务标题}</h1>
<p style="margin:12px auto 0 auto;max-width:520px;font-size:14px;line-height:1.75;color:#596272;">{摘要}</p>
</td></tr>
<tr><td style="padding:26px 34px 0 34px;background:#ffffff;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #eceef3;border-radius:14px;border-collapse:separate;overflow:hidden;background:#ffffff;">
<tr>
<td style="padding:16px 18px;border-bottom:1px solid #eceef3;"><div style="font-size:11px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#98a2b3;margin-bottom:5px;">任务类型</div><div style="font-size:14px;font-weight:700;color:#20242b;">{任务类型}</div></td>
<td style="padding:16px 18px;border-bottom:1px solid #eceef3;border-left:1px solid #eceef3;"><div style="font-size:11px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#98a2b3;margin-bottom:5px;">摘要</div><div style="font-size:14px;font-weight:700;color:#20242b;line-height:1.55;">{摘要}</div></td>
</tr>
<tr><td colspan="2" style="padding:16px 18px;"><div style="font-size:11px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#98a2b3;margin-bottom:5px;">状态</div><div style="font-size:14px;font-weight:700;color:#20242b;">{事件图标} {事件名称}</div></td></tr>
</table>
</td></tr>
<tr><td style="padding:18px 34px 0 34px;background:#ffffff;">{业务数据块}</td></tr>
<tr><td style="padding:28px 34px 32px 34px;background:#ffffff;"><div style="height:1px;background:#eceef3;margin-bottom:16px;"></div><p style="margin:0;text-align:center;font-size:12px;line-height:1.7;color:#8a9099;">此邮件由 <strong style="color:#4f5661;font-weight:650;">Prekikoeru</strong> 自动生成。任务详情可在桌面端任务中心查看。</p></td></tr>
</table>
</td></tr>
</table>""".replace('__HEADER_URL__', _EMAIL_HEADER_URL)


def ensure_default_email_templates() -> None:
    """保证默认通用邮件模板存在，并包含业务数据块。"""
    from ..models.database import SessionLocal, NotificationTemplate
    db = SessionLocal()
    try:
        html_template = _default_white_template_html()
        item = (
            db.query(NotificationTemplate)
            .filter(NotificationTemplate.name == _DEFAULT_USER_TEMPLATE_NAME)
            .order_by(NotificationTemplate.created_at.desc())
            .first()
        )
        if item is None:
            item = NotificationTemplate(
                id=str(uuid.uuid4()),
                name=_DEFAULT_USER_TEMPLATE_NAME,
                channel='email',
                event_types=['completed', 'failed', 'waiting_manual'],
                task_domains=[],
                editor_mode='html',
                blocks=[],
                subject_template=_DEFAULT_USER_SUBJECT,
                html_template=html_template,
                text_template='{事件名称}\n{任务标题}\n{摘要}',
                enabled=True,
                is_default=True,
                sort_order=0,
                description='一个模板覆盖所有任务，业务组件由任务详情自动渲染。',
            )
            db.add(item)
        else:
            item.channel = 'email'
            item.event_types = ['completed', 'failed', 'waiting_manual']
            item.task_domains = []
            item.editor_mode = 'html'
            item.subject_template = item.subject_template or _DEFAULT_USER_SUBJECT
            item.text_template = item.text_template or '{事件名称}\n{任务标题}\n{摘要}'
            item.enabled = True
            item.is_default = True
            item.sort_order = 0
            item.description = item.description or '一个模板覆盖所有任务，业务组件由任务详情自动渲染。'
            item.html_template = html_template
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("[通知模板] 默认邮件模板自愈失败", exc_info=True)
    finally:
        db.close()

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


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return '{' + str(key) + '}'


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
    subject_vars = _SafeFormatDict({
        'title': payload.get('title', ''),
        'domain_label': payload.get('domain_label', ''),
        'summary': payload.get('summary', ''),
        'rjcode': payload.get('rjcode', ''),
        'event_label': event_label,
        'event_icon': event_icon,
        'created_at': created_at,
        'severity': payload.get('severity', ''),
        '任务标题': payload.get('title', ''),
        '任务类型': payload.get('domain_label', ''),
        '摘要': payload.get('summary', ''),
        'RJ号': payload.get('rjcode', ''),
        '事件名称': event_label,
        '事件图标': event_icon,
        '时间': created_at,
        '严重程度': payload.get('severity', ''),
    })
    subject = subject_tpl.format_map(subject_vars)
    payload_for_sections = {
        **payload,
        'event_label': event_label,
        'event_icon': event_icon,
        'created_at_text': created_at,
    }
    sections = _render_payload_sections(payload_for_sections)
    html_body = f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f7f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#1f2329;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fa;padding:32px 0;">
<tr><td align="center">
<table width="660" cellpadding="0" cellspacing="0" border="0" style="width:660px;max-width:calc(100% - 28px);background:#fff;border:1px solid #e8ebf0;border-radius:18px;border-collapse:separate;overflow:hidden;box-shadow:0 18px 48px rgba(20,24,31,.08);">
<tr><td><img src="{_EMAIL_HEADER_URL}" alt="Prekikoeru Mail" width="660" style="display:block;width:100%;max-width:660px;height:auto;border:0;"></td></tr>
<tr><td style="padding:26px 34px 0 34px;text-align:center;background:#fff;">
<div style="font-size:13px;line-height:1.5;color:#7b4fb4;font-weight:800;margin-bottom:12px;">{_esc(event_icon)} {_esc(event_label)} · {_esc(created_at)}</div>
<h1 style="margin:0;color:#151922;font-size:24px;line-height:1.36;font-weight:760;">{title}</h1>
<p style="margin:12px auto 0 auto;max-width:520px;color:#596272;font-size:14px;line-height:1.75;">{summary}</p>
</td></tr>
<tr><td style="padding:26px 34px 0 34px;background:#fff;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #eceef3;border-radius:14px;border-collapse:separate;overflow:hidden;background:#fff;">
<tr>
<td style="padding:16px 18px;border-bottom:1px solid #eceef3;"><div style="font-size:11px;font-weight:800;color:#98a2b3;letter-spacing:.08em;margin-bottom:5px;">任务类型</div><div style="font-size:14px;font-weight:700;color:#20242b;">{domain_label}</div></td>
<td style="padding:16px 18px;border-bottom:1px solid #eceef3;border-left:1px solid #eceef3;"><div style="font-size:11px;font-weight:800;color:#98a2b3;letter-spacing:.08em;margin-bottom:5px;">摘要</div><div style="font-size:14px;font-weight:700;color:#20242b;line-height:1.55;">{summary or '—'}</div></td>
</tr>
<tr><td colspan="2" style="padding:16px 18px;"><div style="font-size:11px;font-weight:800;color:#98a2b3;letter-spacing:.08em;margin-bottom:5px;">状态</div><div style="font-size:14px;font-weight:700;color:#20242b;">{_esc(event_icon)} {_esc(event_label)}</div></td></tr>
</table>
</td></tr>
<tr><td style="padding:18px 34px 0 34px;background:#fff;">{sections}</td></tr>
<tr><td style="padding:28px 34px 32px 34px;background:#fff;"><div style="height:1px;background:#eceef3;margin-bottom:16px;"></div><p style="margin:0;text-align:center;font-size:12px;line-height:1.7;color:#8a9099;">此邮件由 <strong style="color:#4f5661;font-weight:650;">Prekikoeru</strong> 自动生成。任务详情可在桌面端任务中心查看。</p></td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
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
            .filter(NotificationTemplate.enabled == True)
            .order_by(NotificationTemplate.is_default.desc(), NotificationTemplate.sort_order)
            .all()
        )
        domain_specific = None
        generic = None
        for tpl in candidates:
            if not _template_matches_event(tpl.event_types, event_type):
                continue
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


def _template_matches_event(event_types, event_type: str) -> bool:
    if not event_types:
        return True
    if isinstance(event_types, str):
        return event_types == event_type
    try:
        return event_type in list(event_types)
    except Exception:
        return False


def _render_user_template(tpl, payload: dict) -> tuple:
    payload_sections = _render_payload_sections(payload)
    stats_grid_section = _render_payload_section(payload, 'stats_grid')
    file_tree_section = _render_payload_section(payload, 'file_tree')
    diff_section = _render_payload_section(payload, 'diff')
    task_log_section = _render_payload_section(payload, 'task_log')
    variables = {
        'title': payload.get('title', ''),
        'domain_label': payload.get('domain_label', ''),
        'summary': payload.get('summary', ''),
        'rjcode': payload.get('rjcode', ''),
        'event_label': _EVENT_LABELS.get(payload.get('event_type', ''), ''),
        'event_icon': _EVENT_ICONS.get(payload.get('event_type', ''), ''),
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'severity': payload.get('severity', ''),
        'payload_sections': payload_sections,
        'stats_grid_section': stats_grid_section,
        'file_tree_section': file_tree_section,
        'diff_section': diff_section,
        'task_log_section': task_log_section,
    }
    variables.update({
        '任务标题': variables['title'],
        '任务类型': variables['domain_label'],
        '摘要': variables['summary'],
        'RJ号': variables['rjcode'],
        '事件名称': variables['event_label'],
        '事件图标': variables['event_icon'],
        '时间': variables['created_at'],
        '严重程度': variables['severity'],
        '业务数据块': payload_sections,
        '统计网格': stats_grid_section,
        '文件树': file_tree_section,
        '差异对比': diff_section,
        '执行日志': task_log_section,
    })
    safe_vars = {k: _esc(v) for k, v in variables.items()}
    for raw_key in (
        'payload_sections', '业务数据块',
        'stats_grid_section', '统计网格',
        'file_tree_section', '文件树',
        'diff_section', '差异对比',
        'task_log_section', '执行日志',
    ):
        safe_vars[raw_key] = variables.get(raw_key, '')
    formatter = _SafeFormatDict(safe_vars)
    subject = (tpl.subject_template or '').format_map(formatter)
    html_body = (tpl.html_template or '').format_map(formatter)
    text_body = (tpl.text_template or '').format_map(formatter) or variables.get('summary', '')
    return subject, html_body, text_body


def _render_payload_sections(payload: dict) -> str:
    """HTML 模板里的 {业务数据块} 自动区：有数据才渲染。"""
    return ''.join([
        _render_payload_section(payload, 'stats_grid'),
        _render_circle_overview(payload),
        _render_payload_section(payload, 'file_tree'),
        _render_payload_section(payload, 'diff'),
        _render_payload_section(payload, 'task_log'),
    ])


def _render_payload_section(payload: dict, section: str) -> str:
    try:
        from ..core.block_renderers import (
            render_file_tree,
            render_stats_grid,
            render_task_log,
            render_diff_view,
        )
        if section == 'stats_grid' and payload.get('stats'):
            return render_stats_grid({
                'columns': 3,
                'items': _build_stats_items(payload.get('stats') or {}),
            }, payload)
        if section == 'file_tree':
            parts = []
            if payload.get('rj_work_cards'):
                parts.append(render_file_tree({'title': '本次作品', 'sourceKey': 'file_tree', 'maxItems': 40}, payload))
            if payload.get('file_tree'):
                parts.append(render_file_tree({'title': '文件清单', 'sourceKey': 'file_tree', 'maxItems': 40}, payload))
            if payload.get('download_files'):
                parts.append(render_file_tree({'title': '下载文件', 'sourceKey': 'download_files', 'maxItems': 40}, payload))
            if payload.get('upload_files'):
                parts.append(render_file_tree({'title': '上传文件', 'sourceKey': 'upload_files', 'maxItems': 40}, payload))
            return ''.join(parts)
        if section == 'diff':
            parts = []
            if payload.get('circle_diff'):
                parts.append(render_diff_view({'title': '社团补全差异', 'sourceKey': 'circle_diff'}, payload))
            if payload.get('subtitle_diff'):
                parts.append(render_diff_view({'title': '字幕配对差异', 'sourceKey': 'subtitle_diff'}, payload))
            if payload.get('diff_items'):
                parts.append(render_diff_view({'title': '数据差异', 'sourceKey': 'diff_items'}, payload))
            return ''.join(parts)
        if section == 'task_log':
            if payload.get('error_logs'):
                return render_task_log({'title': '错误日志', 'sourceKey': 'error_logs', 'maxLines': 30}, payload)
            if payload.get('recent_logs'):
                return render_task_log({'title': '执行日志', 'sourceKey': 'recent_logs', 'maxLines': 30}, payload)
            return ''
        return ''
    except Exception:
        logger.warning("[通知模板] 渲染业务组件失败 section=%s", section, exc_info=True)
        return ''


def _build_stats_items(stats: dict) -> list:
    label_map = {
        'works': '作品数',
        'local_owned': '本地',
        'owned': 'Kikoeru',
        'dl_count': 'DLsite',
        'asmr_one': 'asmr.one',
        'downloadable': '可下载',
        'missing': '缺失',
        'dl_only': '暂无来源',
        'total_files': '总文件数',
        'uploaded_count': '已上传',
        'downloaded': '已下载',
        'written': '已写入',
        'skipped': '已跳过',
        'filtered_count': '已过滤',
        'failed_count': '失败',
        'existing_subtitles': '现有字幕',
        'total_size': '总大小',
        'duration': '耗时',
    }
    preferred = [
        'works', 'local_owned', 'owned', 'dl_count', 'asmr_one', 'downloadable', 'missing', 'dl_only',
        'total_files', 'uploaded_count', 'downloaded', 'written', 'skipped', 'filtered_count',
        'failed_count', 'existing_subtitles', 'total_size', 'duration',
    ]
    keys = [key for key in preferred if stats.get(key) not in (None, '')]
    for key in stats.keys():
        if key not in keys and stats.get(key) not in (None, ''):
            keys.append(key)
    return [{'key': key, 'label': label_map.get(key, key), 'icon': ''} for key in keys[:9]]


def _render_circle_overview(payload: dict) -> str:
    rows = payload.get('circle_overview') or []
    if not rows:
        return ''
    title = _esc(payload.get('circle_name') or payload.get('title') or '社团概括')
    visible = rows[:28]
    body_rows = []
    for item in visible:
        if not isinstance(item, dict):
            continue
        status = str(item.get('status') or '')
        status_color = '#16a34a' if status in ('可下载', '已满足') else '#d97706'
        body_rows.append(
            '<tr>'
            f'<td style="padding:12px 14px;border-bottom:1px solid #edf0f4;color:#20242b;font-size:13px;font-weight:650;line-height:1.45;">'
            f'<div>{_esc(item.get("title") or "未命名作品")}</div>'
            f'<div style="margin-top:4px;color:#8b95a5;font-size:11px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(item.get("rjcode") or "")}</div>'
            '</td>'
            f'<td style="padding:12px 10px;border-bottom:1px solid #edf0f4;color:#647085;font-size:12px;text-align:center;">{_esc(item.get("kikoeru") or "未收录")}</td>'
            f'<td style="padding:12px 10px;border-bottom:1px solid #edf0f4;color:#647085;font-size:12px;text-align:center;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(item.get("dlsite") or "暂无来源")}</td>'
            f'<td style="padding:12px 10px;border-bottom:1px solid #edf0f4;color:#647085;font-size:12px;text-align:center;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{_esc(item.get("asmr_one") or "暂无来源")}</td>'
            f'<td style="padding:12px 14px;border-bottom:1px solid #edf0f4;text-align:center;"><span style="display:inline-block;padding:3px 8px;border-radius:999px;background:{status_color}14;color:{status_color};font-size:11px;font-weight:700;">{_esc(status or "未知")}</span></td>'
            '</tr>'
        )
    more = ''
    if len(rows) > len(visible):
        more = (
            f'<tr><td colspan="5" style="padding:10px 14px;color:#8b95a5;font-size:12px;text-align:center;">'
            f'还有 {len(rows) - len(visible)} 个作品未展示，可在桌面端社团补全详情查看'
            f'</td></tr>'
        )
    return (
        '<div style="margin:14px 0 12px 0;">'
        f'<div style="font-size:12px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#9aa3b2;margin:0 0 9px 2px;">社团概括 · {title}</div>'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border:1px solid #e7eaf0;border-radius:12px;border-collapse:separate;overflow:hidden;">'
        '<tr>'
        '<th align="left" style="padding:10px 14px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">RESOURCE METADATA</th>'
        '<th style="padding:10px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">KIKOERU</th>'
        '<th style="padding:10px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">DLSITE</th>'
        '<th style="padding:10px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">ASMR.ONE</th>'
        '<th style="padding:10px 14px;border-bottom:1px solid #e7eaf0;color:#98a2b3;font-size:11px;letter-spacing:0.08em;">状态</th>'
        '</tr>'
        f'{"".join(body_rows)}{more}'
        '</table></div>'
    )


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

