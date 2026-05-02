"""
DLsite 邮件监听服务

通过 IMAP IDLE 长连接实时监听 DLsite 新作通知邮件，
自动触发社团补全索引（已有社团 → only_new_works；新社团 → 全量索引）。

IDLE 失败连续 3 次后自动降级为 fallback polling 模式，
待连接恢复后自动回升为 IDLE 模式。
"""

from __future__ import annotations

import asyncio
import email
import email.header
import email.message
import email.utils
import html
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

IMAP_CONNECT_TIMEOUT_SECONDS = 15
EMAIL_WATCHER_LOOKBACK_DAYS = 2


def _decode_header_value(value: str) -> str:
    """解码 RFC2047 编码的邮件头字段（Subject / From 等）。"""
    if not value:
        return ""
    parts = email.header.decode_header(value)
    result_parts = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            try:
                result_parts.append(raw.decode(charset or "utf-8", errors="replace"))
            except Exception:
                result_parts.append(raw.decode("utf-8", errors="replace"))
        else:
            result_parts.append(str(raw))
    return "".join(result_parts)


def _extract_rjcodes_from_text(text: str) -> List[str]:
    """从文本中提取所有 RJ/VJ 号（去重，保持顺序）。"""
    if not text:
        return []
    seen: Set[str] = set()
    result: List[str] = []
    for matched in re.findall(r'[RVB]J\d{6,8}', text, re.IGNORECASE):
        normalized = matched.upper()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_subject_text(value: str) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    normalized = normalized.replace("　", " ")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _subject_matches_filter(subject: str, subject_filter: str) -> bool:
    keyword = str(subject_filter or "").strip()
    if not keyword:
        return True
    return _normalize_subject_text(keyword) in _normalize_subject_text(subject)


def _normalize_mail_address(value: str) -> str:
    return str(email.utils.parseaddr(value or "")[1] or "").strip().lower()


def _decode_envelope_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return _decode_header_value(value.decode("utf-8", errors="replace"))
    return _decode_header_value(str(value))


def _header_msg_from_envelope(envelope) -> Optional["email.message.Message"]:
    if envelope is None:
        return None
    msg = email.message.Message()
    subject = _decode_envelope_text(getattr(envelope, "subject", "") or "")
    from_items = getattr(envelope, "from_", None) or []
    if subject:
        msg["Subject"] = subject
    if from_items:
        addr = from_items[0]
        mailbox = _decode_envelope_text(getattr(addr, "mailbox", "") or "")
        host = _decode_envelope_text(getattr(addr, "host", "") or "")
        name = _decode_envelope_text(getattr(addr, "name", "") or "")
        address = f"{mailbox}@{host}" if mailbox and host else mailbox or host
        msg["From"] = f"{name} <{address}>" if name and address else address or name
    message_id = _decode_envelope_text(getattr(envelope, "message_id", "") or "")
    if message_id:
        msg["Message-ID"] = message_id
    return msg if msg.keys() else None


def _sender_matches_filter(msg: "email.message.Message", sender_filter: str, subject: str = "") -> bool:
    keyword = str(sender_filter or "").strip().lower()
    if not keyword:
        return True
    raw_from = _decode_header_value(msg.get("From", ""))
    address = _normalize_mail_address(raw_from)
    display_name = str(email.utils.parseaddr(raw_from)[0] or "").strip().lower()
    haystacks = [
        raw_from.lower(),
        address,
        display_name,
    ]
    if any(keyword in value for value in haystacks if value):
        return True

    # DLsite/がるまに邮件的 From 显示名和真实地址在不同邮箱里不稳定。
    # 用户配置 dlsite.com 时，把它当作 DLsite 通知预设，结合显示名和主题兜底识别。
    if keyword in {"dlsite", "dlsite.com", "www.dlsite.com"}:
        normalized_subject = _normalize_subject_text(subject)
        if any("dlsite" in value for value in haystacks if value):
            return True
        if "dlsite" in normalized_subject:
            return True
    return False


def _is_self_generated_notification(msg: "email.message.Message", subject: str, config) -> bool:
    if str(msg.get("X-Prekikoeru-Notification") or "").strip() == "1":
        return True

    notification_cfg = getattr(config, "notification_email", None)
    if not notification_cfg:
        return False

    sender = _normalize_mail_address(msg.get("From", ""))
    own_addresses = {
        _normalize_mail_address(getattr(notification_cfg, "from_email", "")),
        _normalize_mail_address(getattr(notification_cfg, "username", "")),
    }
    own_addresses.discard("")
    if not sender or sender not in own_addresses:
        return False

    normalized_subject = _normalize_subject_text(subject)
    return "有新作品发售" in subject or "有新作品发售" in normalized_subject


def _strip_html_tags(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_html_parts(msg: "email.message.Message") -> List[str]:
    html_parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() != "text/html":
                continue
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            charset = part.get_content_charset() or "utf-8"
            html_parts.append(payload.decode(charset, errors="replace"))
        return html_parts

    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes) and msg.get_content_type() == "text/html":
        charset = msg.get_content_charset() or "utf-8"
        html_parts.append(payload.decode(charset, errors="replace"))
    return html_parts


def _slice_new_release_section(html_text: str) -> str:
    text = str(html_text or "")
    if not text:
        return ""
    start_markers = [
        "販売が開始された作品",
        "フォロー中のサークル・出版社・ブランドの新作",
    ]
    end_markers = [
        "お気に入りの割引中作品一覧",
        "配信が開始された作品",
        "配信開始された作品",
    ]
    start_index = -1
    for marker in start_markers:
        start_index = text.find(marker)
        if start_index >= 0:
            break
    if start_index < 0:
        return text
    section = text[start_index:]
    end_index = -1
    for marker in end_markers:
        marker_index = section.find(marker)
        if marker_index >= 0 and (end_index < 0 or marker_index < end_index):
            end_index = marker_index
    if end_index >= 0:
        section = section[:end_index]
    return section


def _extract_new_release_items_from_html(html_text: str) -> List[Dict[str, str]]:
    section = _slice_new_release_section(html_text)
    if not section:
        return []

    anchor_pattern = re.compile(
        r'<a\b[^>]*href=["\'](?P<href>[^"\']*?/product_id/(?P<rj>[RVB]J\d{6,8})[^"\']*)["\'][^>]*>(?P<label>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    image_pattern = re.compile(r'<img\b[^>]*src=["\'](?P<src>[^"\']+)["\']', re.IGNORECASE | re.DOTALL)
    price_pattern = re.compile(r'(?P<price>[0-9][0-9,]*)\s*円')
    items: List[Dict[str, str]] = []
    seen: Set[str] = set()
    matches = list(anchor_pattern.finditer(section))
    for index, match in enumerate(matches):
        rjcode = str(match.group("rj") or "").strip().upper()
        title = _strip_html_tags(match.group("label") or "")
        if not rjcode or not title or rjcode in seen:
            continue
        seen.add(rjcode)

        block_start = max(0, match.start() - 1400)
        block_end = matches[index + 1].start() if index + 1 < len(matches) else min(len(section), match.end() + 2200)
        block_html = section[block_start:block_end]
        tail_html = section[match.end():block_end]
        before_html = section[block_start:match.start()]

        image_match = list(image_pattern.finditer(before_html))
        image_url = image_match[-1].group("src").strip() if image_match else ""

        cleaned_lines = [
            line.strip()
            for line in re.split(r"[\r\n]+", _strip_html_tags(tail_html))
            if line and line.strip()
        ]
        circle_name = ""
        work_type = ""
        price_text = ""
        for line in cleaned_lines:
            if not price_text:
                price_match = price_pattern.search(line)
                if price_match:
                    price_text = f"{price_match.group('price')}円"
                    continue
            if not work_type and ("・" in line or "ASMR" in line.upper() or "ボイス" in line):
                work_type = line[:80]
                continue
            if not circle_name and line != title:
                circle_name = line[:120]
                if price_pattern.search(circle_name):
                    circle_name = ""

        if not price_text:
            price_match = price_pattern.search(_strip_html_tags(block_html))
            if price_match:
                price_text = f"{price_match.group('price')}円"

        items.append({
            "rjcode": rjcode,
            "title": title[:300],
            "circle_name": circle_name[:160],
            "price_text": price_text,
            "work_type": work_type[:120],
            "image_url": image_url[:1000],
            "product_url": str(match.group("href") or "").strip()[:2000],
        })
    return items


def _extract_new_release_items_from_mail(msg: "email.message.Message") -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for html_text in _extract_html_parts(msg):
        for item in _extract_new_release_items_from_html(html_text):
            rjcode = str(item.get("rjcode") or "").strip().upper()
            if not rjcode or rjcode in seen:
                continue
            seen.add(rjcode)
            items.append(item)
    return items


def _extract_rjcodes_from_mail(msg: "email.message.Message") -> List[str]:
    """
    从邮件中提取 RJ 号，同时扫描：
    - text/plain 正文
    - text/html 原始 HTML（覆盖 href 链接里的 RJ 号，DLsite 邮件 RJ 号仅出现在 HTML 链接中）
    """
    plain_parts: List[str] = []
    html_parts: List[str] = []

    def _collect(m: "email.message.Message"):
        if m.is_multipart():
            for part in m.walk():
                ct = part.get_content_type()
                payload = part.get_payload(decode=True)
                if not isinstance(payload, bytes):
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if ct == "text/plain":
                    plain_parts.append(decoded)
                elif ct == "text/html":
                    html_parts.append(decoded)
        else:
            payload = m.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = m.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if m.get_content_type() == "text/html":
                    html_parts.append(decoded)
                else:
                    plain_parts.append(decoded)

    _collect(msg)
    # 合并 plain 和 html 一起扫描，确保捕获 HTML href 里的 RJ 号
    combined = "\n".join(plain_parts) + "\n" + "\n".join(html_parts)
    return _extract_rjcodes_from_text(combined)


def _build_new_release_email_card_html(circle_name: str, items: List[Dict[str, object]]) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value or "").strip(), quote=True)

    rows: List[str] = []
    for item in items:
        rjcode = esc(item.get("mail_rjcode") or item.get("display_rjcode") or item.get("canonical_rjcode") or item.get("rjcode"))
        title = esc(item.get("title") or rjcode or "新作")
        image_url = esc(item.get("image_url") or "")
        product_url = esc(item.get("product_url") or "")
        price_text = esc(item.get("price_text") or "")
        work_type = esc(item.get("work_type") or "")
        canonical = esc(item.get("canonical_rjcode") or "")
        display = esc(item.get("display_rjcode") or "")
        badges = []
        if price_text:
            badges.append(f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;border-radius:7px;background:#fff7ed;color:#c2410c;font-size:12px;font-weight:700;">{price_text}</span>')
        if work_type:
            badges.append(f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;border-radius:7px;background:#ecfeff;color:#0e7490;font-size:12px;font-weight:700;">{work_type}</span>')
        if item.get("has_asmr_one"):
            badges.append('<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;border-radius:7px;background:#dcfce7;color:#15803d;font-size:12px;font-weight:700;">可下载</span>')
        if item.get("has_kikoeru"):
            badges.append('<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;border-radius:7px;background:#dbeafe;color:#1d4ed8;font-size:12px;font-weight:700;">服务器已有</span>')

        image_cell = (
            f'<img src="{image_url}" alt="{title}" width="168" style="display:block;width:168px;max-width:168px;border-radius:10px;border:1px solid rgba(15,23,42,.08);object-fit:cover;">'
            if image_url
            else '<div style="width:168px;height:118px;border-radius:10px;background:#e2e8f0;color:#64748b;font-size:13px;font-weight:700;text-align:center;line-height:118px;">No Cover</div>'
        )
        title_html = f'<a href="{product_url}" style="color:#0f172a;text-decoration:none;" target="_blank">{title}</a>' if product_url else title
        relation = f'<div style="margin-top:7px;color:#94a3b8;font-size:12px;font-weight:700;">{canonical} → {display}</div>' if canonical and display and canonical != display else ""

        rows.append(f'''
          <tr>
            <td style="padding:14px 0;border-top:1px solid #e5e7eb;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                <tr>
                  <td width="184" valign="top" style="width:184px;padding-right:16px;">{image_cell}</td>
                  <td valign="top" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;">
                    <div style="margin-bottom:8px;color:#2563eb;font-size:12px;font-weight:800;letter-spacing:.02em;">{rjcode}</div>
                    <div style="margin-bottom:10px;color:#0f172a;font-size:18px;font-weight:800;line-height:1.45;">{title_html}</div>
                    <div style="margin-bottom:8px;">{''.join(badges)}</div>
                    <div style="color:#475569;font-size:13px;line-height:1.7;">社团：{esc(item.get("circle_name") or circle_name)}</div>
                    {relation}
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        ''')

    return f'''
      <div style="margin:0;padding:24px;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;color:#0f172a;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:760px;margin:0 auto;border-collapse:collapse;">
          <tr>
            <td style="padding:20px 22px;border-radius:14px;background:#ffffff;border:1px solid #e2e8f0;box-shadow:0 10px 30px rgba(15,23,42,.08);">
              <div style="margin-bottom:4px;color:#16a34a;font-size:13px;font-weight:900;">NEW RELEASE</div>
              <div style="margin-bottom:8px;color:#0f172a;font-size:22px;font-weight:900;">{esc(circle_name)} 有新作品发售</div>
              <div style="margin-bottom:4px;color:#64748b;font-size:13px;">已写入社团补全索引，可在 Prekikoeru 查看状态。</div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin-top:14px;">
                {''.join(rows)}
              </table>
            </td>
          </tr>
        </table>
      </div>
    '''


class EmailWatcherService:
    """
    IMAP IDLE 邮件监听服务。

    生命周期：
        service = get_email_watcher_service()
        await service.start()   # 应用启动时调用
        await service.stop()    # 应用关闭时调用
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 状态信息（供 /api/email-watcher/status 返回）
        self._mode: str = "stopped"          # stopped / idle / polling / error
        self._last_check_at: Optional[str] = None
        self._total_mails_processed: int = 0
        self._total_rjcodes_triggered: int = 0
        self._last_error: str = ""
        self._fail_count: int = 0

        # 去重缓存（rjcode -> 最后处理时间戳）
        self._processed_rjcodes: Dict[str, float] = {}
        self._processed_message_ids: Set[str] = set()
        self._dedup_ttl: float = 24 * 3600  # 24 小时 TTL

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def start(self):
        """启动后台 IDLE 监听任务。"""
        from ..config.settings import get_config
        config = get_config()
        if not config.email_watcher.enabled:
            logger.info("[邮件监听] 已禁用，跳过启动")
            return

        self._loop = asyncio.get_event_loop()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._idle_loop(), name="email_watcher_idle_loop")
        logger.info("[邮件监听] 服务启动，IMAP: %s:%s", config.email_watcher.imap_host, config.email_watcher.imap_port)

    async def stop(self):
        """停止后台 IDLE 监听任务。"""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._mode = "stopped"
        logger.info("[邮件监听] 服务已停止")

    def get_status(self) -> Dict:
        """返回当前运行状态。"""
        return {
            "enabled": True,
            "mode": self._mode,
            "last_check_at": self._last_check_at,
            "total_mails_processed": self._total_mails_processed,
            "total_rjcodes_triggered": self._total_rjcodes_triggered,
            "last_error": self._last_error,
            "fail_count": self._fail_count,
        }

    async def poll_once(self):
        """手动触发一次邮件检查（调试用）。"""
        from ..config.settings import get_config
        config = get_config()
        if not config.email_watcher.username:
            return {"success": False, "message": "邮箱账号未配置"}
        try:
            result = await asyncio.to_thread(self._run_single_fetch, config)
            msg_parts = [f"触发索引 {result['count']} 个"]
            if result['unseen_total'] == 0:
                msg_parts.append("未读邮件 0 封（邮件可能已读，或发件人/主题过滤未匹配）")
            else:
                msg_parts.append(f"找到未读 {result['unseen_total']} 封，匹配 {result['matched_mails']} 封")
            if result['skipped_subject_filter']:
                msg_parts.append(f"主题过滤跳过 {result['skipped_subject_filter']} 封")
            if result.get('skipped_self_notification'):
                msg_parts.append(f"自家通知跳过 {result['skipped_self_notification']} 封")
            if result['skipped_read']:
                msg_parts.append(f"已处理去重跳过 {result['skipped_read']} 封")
            if result['rjcodes']:
                msg_parts.append(f"RJ号: {', '.join(result['rjcodes'])}")
            return {"success": True, "message": "；".join(msg_parts), **result}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def _mark_email_watcher_tag(self, rjcode: str) -> Dict[str, str]:
        from ..models.database import CircleWork, SessionLocal

        normalized_rjcode = str(rjcode or "").strip().upper()
        if not normalized_rjcode:
            return {}

        db = SessionLocal()
        try:
            rows = db.query(CircleWork).all()
            for work in rows:
                linked_rjcodes = list(work.linked_rjcodes or [])
                candidates = {
                    str(work.canonical_rjcode or "").strip().upper(),
                    str(work.display_rjcode or "").strip().upper(),
                    *(str(code or "").strip().upper() for code in linked_rjcodes),
                }
                if normalized_rjcode not in candidates:
                    continue
                tags = list(work.source_tags or [])
                if "email_watcher" not in tags:
                    tags.append("email_watcher")
                    work.source_tags = tags
                    db.commit()
                    logger.info(
                        "[邮件监听] 已为 %s 添加 email_watcher 来源标签 -> circle=%s canonical=%s",
                        normalized_rjcode,
                        work.circle_id,
                        work.canonical_rjcode,
                    )
                return {
                    "circle_id": str(work.circle_id or "").strip(),
                    "canonical_rjcode": str(work.canonical_rjcode or "").strip().upper(),
                    "display_rjcode": str(work.display_rjcode or "").strip().upper(),
                    "title": str(work.title or "").strip(),
                }
            return {}
        except Exception:
            db.rollback()
            logger.warning("[邮件监听] 更新 source_tags 失败 rjcode=%s", normalized_rjcode, exc_info=True)
            return {}
        finally:
            db.close()

    def _is_rjcode_persistently_processed(self, rjcode: str) -> bool:
        from ..models.database import CircleWork, SessionLocal

        normalized_rjcode = str(rjcode or "").strip().upper()
        if not normalized_rjcode:
            return False

        db = SessionLocal()
        try:
            rows = (
                db.query(CircleWork)
                .filter(
                    (CircleWork.canonical_rjcode == normalized_rjcode)
                    | (CircleWork.display_rjcode == normalized_rjcode)
                )
                .all()
            )
            if not rows:
                rows = db.query(CircleWork).all()
            for work in rows:
                linked_rjcodes = list(work.linked_rjcodes or [])
                candidates = {
                    str(work.canonical_rjcode or "").strip().upper(),
                    str(work.display_rjcode or "").strip().upper(),
                    *(str(code or "").strip().upper() for code in linked_rjcodes),
                }
                if normalized_rjcode not in candidates:
                    continue
                return "email_watcher" in set(work.source_tags or [])
            return False
        except Exception:
            logger.warning("[邮件监听] 查询持久化去重状态失败 rjcode=%s", normalized_rjcode, exc_info=True)
            return False
        finally:
            db.close()

    def _notification_event_exists(self, event_key: str) -> bool:
        from ..models.database import NotificationInboxItem, SessionLocal

        key = str(event_key or "").strip()
        if not key:
            return False

        db = SessionLocal()
        try:
            return db.query(NotificationInboxItem.id).filter(NotificationInboxItem.event_key == key).first() is not None
        except Exception:
            logger.warning("[邮件监听] 查询通知事件去重状态失败 event_key=%s", key, exc_info=True)
            return False
        finally:
            db.close()

    async def _emit_new_release_notifications(self, grouped_items: Dict[str, Dict[str, object]]) -> None:
        if not grouped_items:
            return

        from ..config.settings import get_config
        from .notification_email_service import send_notification_email
        from .task_notification_service import create_custom_notification

        cfg = get_config()
        for circle_id, payload in grouped_items.items():
            circle_name = str(payload.get("circle_name") or circle_id or "未知社团").strip()
            items = list(payload.get("items") or [])
            if not items:
                continue
            rjcodes: List[str] = []
            for item in items:
                code = str(
                    item.get("mail_rjcode")
                    or item.get("display_rjcode")
                    or item.get("canonical_rjcode")
                    or ""
                ).strip().upper()
                if code and code not in rjcodes:
                    rjcodes.append(code)
            if not rjcodes:
                continue

            title = f"({circle_name})有新作品发售"
            summary = f"{circle_name} 新作 {len(rjcodes)} 个：{', '.join(rjcodes)}"
            event_key = f"email_watcher:new_release:{circle_id}:{'|'.join(rjcodes)}"
            event_already_exists = self._notification_event_exists(event_key)
            if event_already_exists:
                logger.info("[邮件监听] 新作通知已存在，跳过重复通知和邮件: %s", event_key)
                continue
            create_custom_notification(
                event_key=event_key,
                event_type="email_watcher_new_release",
                title=title,
                summary=summary,
                severity="success",
                task_domain="circle_completion",
                task_kind="email_watcher_new_release",
                source_page="circle-completion",
                source_action="email_new_release",
                source_label=circle_name,
                business_key=f"email_watcher:{circle_id}",
                rjcode=rjcodes[0],
                route_path="/circle-completion",
                route_query={"circle_id": circle_id},
            )

            if not (cfg.notification_email.enabled and cfg.notification_email.to_email and cfg.notification_email.smtp_host):
                continue
            # 站内通知会通过 SSE 驱动社团补全页刷新；邮件稍后发送，避免早于页面数据刷新到达。
            await asyncio.sleep(1.2)
            lines = [f"{circle_name} 有新作"]
            for item in items:
                code = str(item.get("mail_rjcode") or item.get("display_rjcode") or item.get("canonical_rjcode") or "").strip().upper()
                work_title = str(item.get("title") or "").strip()
                lines.append(f"- {code} {work_title}".strip())
            lines.append("已写入社团补全索引，请在 Prekikoeru 查看。")
            text_body = "\n".join(lines)
            html_body = _build_new_release_email_card_html(circle_name, items)
            await send_notification_email(title, html_body, text_body)

    async def _trigger_index_for_rjcodes(self, items: List[Dict[str, str]], config, batch_id: str) -> List[Dict[str, object]]:
        grouped_items: Dict[str, Dict[str, object]] = {}
        results: List[Dict[str, object]] = []
        for item in items:
            result = await self._trigger_index_for_rjcode(item, config, batch_id)
            results.append(result)
            if not result.get("success"):
                continue
            circle_id = str(result.get("circle_id") or "").strip()
            if not circle_id:
                continue
            bucket = grouped_items.setdefault(circle_id, {
                "circle_name": str(result.get("circle_name") or "").strip(),
                "items": [],
            })
            bucket["items"].append(result)
        await self._emit_new_release_notifications(grouped_items)
        return results

    async def _upsert_email_release_work(
        self,
        *,
        item: Dict[str, str],
        product: Dict[str, object],
        product_info_result: Dict[str, object],
        circle_name: str,
        maker_id: str,
    ) -> Dict[str, object]:
        from .circle_completion_service import get_circle_completion_service
        from ..models.database import CircleCatalog, CircleExternalIdentity, CircleWork, SessionLocal

        circle_service = get_circle_completion_service()
        rjcode = circle_service.normalize_rjcode(item.get("rjcode"))
        if not rjcode:
            raise ValueError("RJ 号为空")

        canonical_info = await circle_service.resolve_canonical_rj(rjcode)
        canonical = circle_service.normalize_rjcode(canonical_info.get("canonical_rjcode")) or rjcode
        linked_rjcodes = [
            circle_service.normalize_rjcode(code)
            for code in list(canonical_info.get("linked_rjcodes") or [])
            if circle_service.normalize_rjcode(code)
        ]
        if rjcode not in linked_rjcodes:
            linked_rjcodes.append(rjcode)

        metadata = await circle_service._fetch_metadata_dict(rjcode)
        product_release_date = str(product.get("regist_date") or product.get("release_date") or "").strip()
        if product_release_date and metadata.get("release_date") != product_release_date:
            metadata = {**metadata, "release_date": product_release_date}
        product_cover_url = ""
        if isinstance(product.get("image_main"), dict):
            product_cover_url = str((product.get("image_main") or {}).get("url") or "").strip()
        title = str(
            metadata.get("work_name")
            or product.get("work_name")
            or item.get("title")
            or rjcode
        ).strip()
        display_rjcode = circle_service.normalize_rjcode(product.get("workno")) or rjcode
        normalized_name = circle_service.normalize_circle_name(circle_name)
        image_url = circle_service._normalize_dlsite_cover_url(
            product_cover_url,
            display_rjcode,
        ) or str(item.get("image_url") or "").strip()

        probe_candidates = [display_rjcode, canonical, *linked_rjcodes]
        actual_rjcode, _ = await circle_service._find_public_downloadable_work(
            canonical_info,
            display_rjcode or canonical,
            metadata_map={display_rjcode: metadata, canonical: metadata},
            extra_candidates=probe_candidates,
        )
        actual_norm = circle_service.normalize_rjcode(actual_rjcode)
        kikoeru_state = await circle_service._probe_kikoeru_state_for_candidates(
            probe_candidates,
            use_cache=True,
        )
        found_rjcodes = [
            circle_service.normalize_rjcode(code)
            for code in list(kikoeru_state.get("found_rjcodes") or [])
            if circle_service.normalize_rjcode(code)
        ]
        subtitle_rjcodes = [
            circle_service.normalize_rjcode(code)
            for code in list(kikoeru_state.get("subtitle_rjcodes") or [])
            if circle_service.normalize_rjcode(code)
        ]

        db = SessionLocal()
        try:
            from ..models.database import WorkMetadata

            catalog = None
            if normalized_name:
                catalog = (
                    db.query(CircleCatalog)
                    .filter(CircleCatalog.circle_name_normalized == normalized_name)
                    .order_by(CircleCatalog.last_indexed_at.desc(), CircleCatalog.updated_at.desc())
                    .first()
                )
            circle_id = str((catalog.circle_id if catalog else "") or maker_id or normalized_name or circle_name).strip()
            if not circle_id:
                raise ValueError("无法解析社团 ID")
            if catalog is None:
                catalog = db.query(CircleCatalog).filter(CircleCatalog.circle_id == circle_id).first()
            if catalog is None:
                catalog = CircleCatalog(circle_id=circle_id)
                db.add(catalog)

            catalog.circle_name = circle_name or catalog.circle_name or circle_id
            catalog.circle_name_normalized = normalized_name or catalog.circle_name_normalized
            source_flags = {flag for flag in str(catalog.source_mask or "").split(",") if flag}
            source_flags.add("dlsite")
            if actual_norm:
                source_flags.add("asmr_one")
            if found_rjcodes:
                source_flags.add("kikoeru")
            catalog.source_mask = ",".join(sorted(source_flags))
            catalog.last_indexed_at = datetime.now()
            catalog.last_local_sync_at = datetime.now()
            catalog.updated_at = datetime.now()

            identity = None
            if normalized_name:
                identity = (
                    db.query(CircleExternalIdentity)
                    .filter(CircleExternalIdentity.circle_name_normalized == normalized_name)
                    .first()
                )
                if identity is None:
                    identity = CircleExternalIdentity(circle_name_normalized=normalized_name)
                    db.add(identity)
                identity.maker_id = maker_id or identity.maker_id or ""
                identity.updated_at = datetime.now()

            row = (
                db.query(CircleWork)
                .filter(CircleWork.circle_id == catalog.circle_id, CircleWork.canonical_rjcode == canonical)
                .first()
            )
            if row is None:
                row = CircleWork(id=str(uuid.uuid4()), circle_id=catalog.circle_id, canonical_rjcode=canonical)
                db.add(row)

            metadata_targets = sorted({
                code for code in [rjcode, display_rjcode, canonical, *linked_rjcodes]
                if circle_service.normalize_rjcode(code)
            })
            for metadata_rjcode in metadata_targets:
                normalized_meta_rj = circle_service.normalize_rjcode(metadata_rjcode)
                metadata_row = db.query(WorkMetadata).filter(WorkMetadata.rjcode == normalized_meta_rj).first()
                if metadata_row is None:
                    metadata_row = WorkMetadata(rjcode=normalized_meta_rj)
                    db.add(metadata_row)
                metadata_row.work_name = str(product.get("work_name") or metadata.get("work_name") or title or metadata_row.work_name or "").strip()
                metadata_row.maker_id = maker_id or str(metadata.get("maker_id") or metadata_row.maker_id or "").strip()
                metadata_row.maker_name = circle_name or str(metadata.get("maker_name") or metadata_row.maker_name or "").strip()
                if product_release_date:
                    metadata_row.release_date = product_release_date
                metadata_row.cover_url = product_cover_url or str(metadata.get("cover_url") or metadata_row.cover_url or "").strip()
                metadata_row.tags = metadata.get("tags") or metadata_row.tags or []
                metadata_row.cvs = metadata.get("cvs") or metadata_row.cvs or []
                metadata_row.cached_at = datetime.now()
                metadata_row.expires_at = None
                circle_service._metadata_cache.pop(normalized_meta_rj, None)

            row.display_rjcode = display_rjcode or row.display_rjcode or canonical
            row.title = title or row.title or canonical
            row.maker_id = maker_id or row.maker_id or ""
            row.maker_name = circle_name or row.maker_name or ""
            row.image_url = image_url or row.image_url or ""
            row.linked_rjcodes = sorted(set(linked_rjcodes or [row.display_rjcode or canonical]))
            row.has_dlsite = True
            row.has_asmr_one = bool(actual_norm)
            row.asmr_available_rjcode = actual_norm or None
            row.has_kikoeru = bool(found_rjcodes)
            row.kikoeru_found_rjcodes = found_rjcodes
            row.kikoeru_subtitle_rjcodes = subtitle_rjcodes
            work_flags = {flag for flag in str(row.source_mask or "").split(",") if flag}
            work_flags.add("dlsite")
            if actual_norm:
                work_flags.add("asmr_one")
            if found_rjcodes:
                work_flags.add("kikoeru")
            row.source_mask = ",".join(sorted(work_flags))
            tags = list(row.source_tags or [])
            if "email_watcher" not in tags:
                tags.append("email_watcher")
            row.source_tags = tags
            row.dlsite_cached_at = datetime.now()
            row.asmr_one_cached_at = datetime.now() if actual_norm else row.asmr_one_cached_at
            row.updated_at = datetime.now()
            db.commit()

            return {
                "success": True,
                "mode": "rj_direct_upsert",
                "mail_rjcode": rjcode,
                "circle_id": str(catalog.circle_id or ""),
                "circle_name": str(catalog.circle_name or circle_name or ""),
                "maker_id": maker_id,
                "canonical_rjcode": canonical,
                "display_rjcode": str(row.display_rjcode or ""),
                "title": str(row.title or ""),
                "price_text": str(item.get("price_text") or "").strip(),
                "work_type": str(item.get("work_type") or "").strip(),
                "image_url": str(row.image_url or item.get("image_url") or "").strip(),
                "product_url": str(item.get("product_url") or "").strip(),
                "has_asmr_one": bool(row.has_asmr_one),
                "has_kikoeru": bool(row.has_kikoeru),
                "fallback_source": str(product_info_result.get("fallback_source") or ""),
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def test_connection(self, host: str, port: int, ssl: bool, username: str, password: str, mailbox: str) -> Dict:
        """测试 IMAP 连接。"""
        try:
            result = await asyncio.to_thread(
                self._do_test_connection, host, port, ssl, username, password, mailbox
            )
            return result
        except Exception as exc:
            return {"success": False, "message": f"连接失败: {exc}"}

    # ------------------------------------------------------------------
    # 内部主循环
    # ------------------------------------------------------------------

    async def _idle_loop(self):
        """主 IDLE 循环，保持长连接并监听新邮件。"""
        from ..config.settings import get_config
        consecutive_fails = 0

        while not self._stop_event.is_set():
            config = get_config()
            if not config.email_watcher.enabled:
                await asyncio.sleep(30)
                continue

            try:
                self._mode = "idle"
                self._fail_count = consecutive_fails
                await asyncio.to_thread(self._run_idle_session, config)
                consecutive_fails = 0
                self._fail_count = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_fails += 1
                self._fail_count = consecutive_fails
                self._last_error = str(exc)
                self._mode = "error"
                logger.warning("[邮件监听] IDLE 会话失败 (连续 %d 次): %s", consecutive_fails, exc)

                if consecutive_fails >= 3:
                    # 降级为 polling 模式
                    self._mode = "polling"
                    logger.warning("[邮件监听] 连续失败 %d 次，降级为 fallback polling", consecutive_fails)
                    try:
                        await asyncio.to_thread(self._run_single_fetch, config)
                        self._last_check_at = datetime.now().isoformat(timespec="seconds")
                    except Exception as poll_exc:
                        logger.warning("[邮件监听] fallback polling 也失败: %s", poll_exc)

                    await asyncio.sleep(config.email_watcher.fallback_poll_interval_seconds)
                else:
                    await asyncio.sleep(30)

    def _run_idle_session(self, config):
        """
        单次完整 IMAP IDLE 会话（在 thread 中同步运行）。
        - 建立连接
        - 循环 IDLE，直到收到新邮件通知或超时
        - 处理新邮件后继续循环，直到外部 stop_event 置位
        """
        try:
            from imapclient import IMAPClient
        except ImportError:
            raise RuntimeError("imapclient 未安装，请执行: pip install imapclient>=3.0.1")

        imap_host = config.email_watcher.imap_host
        imap_port = config.email_watcher.imap_port
        imap_ssl = config.email_watcher.imap_ssl
        idle_timeout = config.email_watcher.idle_timeout_minutes * 60

        with IMAPClient(host=imap_host, port=imap_port, ssl=imap_ssl, timeout=IMAP_CONNECT_TIMEOUT_SECONDS) as client:
            client.login(config.email_watcher.username, config.email_watcher.password)
            client.select_folder(config.email_watcher.mailbox)
            logger.info("[邮件监听] IMAP 登录成功，进入 IDLE 模式")

            # 进入 IDLE 循环前先检查一次现有未读邮件
            self._fetch_and_process(client, config)

            while not self._stop_event.is_set():
                client.idle()
                try:
                    # 阻塞等待服务器 pushback，超时后重新 IDLE（RFC 要求不超过 29 分钟）
                    responses = client.idle_check(timeout=idle_timeout)
                finally:
                    client.idle_done()

                if self._stop_event.is_set():
                    break

                # 检查是否有新邮件通知（服务器发来 EXISTS 或 FETCH 响应）
                has_new = any(
                    (isinstance(r, tuple) and len(r) >= 2 and r[1] in (b'EXISTS', b'RECENT', b'FETCH'))
                    for r in responses
                )
                if has_new or not responses:
                    # 不管是否有通知都扫一次（timeout 空响应也扫，避免遗漏）
                    self._fetch_and_process(client, config)

                self._last_check_at = datetime.now().isoformat(timespec="seconds")

    def _run_single_fetch(self, config) -> dict:
        """
        单次 fetch（非 IDLE），用于 fallback polling 和手动触发。
        返回诊断字典：{ count, unseen_total, matched_mails, rjcodes }
        """
        try:
            from imapclient import IMAPClient
        except ImportError:
            raise RuntimeError("imapclient 未安装，请执行: pip install imapclient>=3.0.1")

        imap_host = config.email_watcher.imap_host
        imap_port = config.email_watcher.imap_port
        imap_ssl = config.email_watcher.imap_ssl

        with IMAPClient(host=imap_host, port=imap_port, ssl=imap_ssl, timeout=IMAP_CONNECT_TIMEOUT_SECONDS) as client:
            client.login(config.email_watcher.username, config.email_watcher.password)
            client.select_folder(config.email_watcher.mailbox)
            result = self._fetch_and_process(client, config)
            self._last_check_at = datetime.now().isoformat(timespec="seconds")
            return result

    def _fetch_and_process(self, client, config) -> dict:
        """
        搜索未读 DLsite 邮件，解析新作卡片并触发社团索引。
        """
        try:
            from imapclient.imapclient import SEEN
        except ImportError:
            SEEN = b'\\Seen'

        sender_filter = str(config.email_watcher.sender_filter or "").strip()
        subject_filter = str(config.email_watcher.subject_filter or "").strip()

        diag = {
            "count": 0,
            "unseen_total": 0,
            "matched_mails": 0,
            "rjcodes": [],
            "items": [],
            "mail_summaries": [],
            "skipped_read": 0,
            "skipped_sender_filter": 0,
            "skipped_subject_filter": 0,
            "skipped_self_notification": 0,
            "dlsite_subject_total": 0,
            "dlsite_from_total": 0,
        }

        since_date = (datetime.now() - timedelta(days=EMAIL_WATCHER_LOOKBACK_DAYS)).date()
        # 先在服务端限定未读 + 最近 2 天，避免老邮箱历史未读过多。
        # 再额外合并最近 2 天的 DLsite 主题/发件人候选：QQ 网页端未读状态和 IMAP UNSEEN 偶尔不一致。
        criteria = ['UNSEEN', 'SINCE', since_date]

        try:
            uids = client.search(criteria)
        except Exception as exc:
            logger.warning("[邮件监听] 搜索邮件失败: %s", exc)
            return diag

        dlsite_subject_uids = []
        dlsite_from_uids = []
        try:
            dlsite_subject_uids = client.search(['SINCE', since_date, 'SUBJECT', 'DLsite'])
        except Exception as exc:
            logger.debug("[邮件监听] SUBJECT DLsite 搜索失败，继续使用未读集合: %s", exc)
        try:
            dlsite_from_uids = client.search(['SINCE', since_date, 'FROM', 'dlsite'])
        except Exception as exc:
            logger.debug("[邮件监听] FROM dlsite 搜索失败，继续使用未读集合: %s", exc)

        diag["dlsite_subject_total"] = len(dlsite_subject_uids)
        diag["dlsite_from_total"] = len(dlsite_from_uids)
        merged_uids = list(dict.fromkeys(list(uids) + list(dlsite_subject_uids) + list(dlsite_from_uids)))

        diag["unseen_total"] = len(uids)
        logger.info(
            "[邮件监听] 搜索条件=%s 找到最近 %d 天未读邮件 %d 封；DLsite主题候选 %d 封，发件人候选 %d 封，合并检查 %d 封",
            criteria,
            EMAIL_WATCHER_LOOKBACK_DAYS,
            len(uids),
            len(dlsite_subject_uids),
            len(dlsite_from_uids),
            len(merged_uids),
        )

        if not merged_uids:
            return diag

        # 先只取头部做 From/Subject/Message-ID 筛选，命中的邮件才拉正文。
        try:
            header_messages = client.fetch(
                merged_uids,
                ['BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)]', 'ENVELOPE']
            )
        except Exception as exc:
            logger.warning("[邮件监听] 获取邮件头失败: %s", exc)
            return diag

        parsed_items: List[Dict[str, str]] = []
        processed_uids = []
        matched_header_uids: List = []
        header_cache: Dict[object, Dict[str, str]] = {}

        for uid, data in header_messages.items():
            raw_header = (
                data.get(b'BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)]')
                or data.get(b'BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)]')
            )
            header_msg = None
            if raw_header:
                try:
                    header_msg = email.message_from_bytes(raw_header)
                except Exception as exc:
                    logger.debug("[邮件监听] uid=%s 解析邮件头失败，尝试 ENVELOPE 兜底: %s", uid, exc)
            if header_msg is None:
                header_msg = _header_msg_from_envelope(data.get(b'ENVELOPE'))
            if header_msg is None:
                logger.warning("[邮件监听] uid=%s 无法读取邮件头和 ENVELOPE，已跳过；fetch keys=%s", uid, list(data.keys()))
                continue

            message_id = header_msg.get('Message-ID', '') or header_msg.get('Message-Id', '')
            if message_id and message_id in self._processed_message_ids:
                diag["skipped_read"] += 1
                processed_uids.append(uid)
                continue

            subject = _decode_header_value(header_msg.get('Subject', ''))
            from_header = _decode_header_value(header_msg.get('From', ''))
            logger.debug("[邮件监听] uid=%s From=%r 主题=%r", uid, from_header, subject)
            if not _sender_matches_filter(header_msg, sender_filter, subject):
                logger.debug("[邮件监听] uid=%s 发件人过滤不匹配（关键词=%r，From=%r），跳过", uid, sender_filter, from_header)
                diag["skipped_sender_filter"] += 1
                continue
            if _is_self_generated_notification(header_msg, subject, config):
                logger.debug("[邮件监听] uid=%s 是 Prekikoeru 自己发出的通知邮件，跳过", uid)
                diag["skipped_self_notification"] += 1
                continue
            if not _subject_matches_filter(subject, subject_filter):
                logger.debug("[邮件监听] uid=%s 主题过滤不匹配（关键词=%r），跳过", uid, subject_filter)
                diag["skipped_subject_filter"] += 1
                continue

            logger.info("[邮件监听] 命中候选邮件 uid=%s From=%r 主题=%r", uid, from_header, subject)
            matched_header_uids.append(uid)
            header_cache[uid] = {
                "message_id": str(message_id or ""),
                "subject": subject,
                "from_header": from_header,
            }

        if not matched_header_uids:
            logger.info(
                "[邮件监听] 头部筛选完成：候选 0 封，发件人跳过 %d，主题跳过 %d，自发通知跳过 %d",
                diag["skipped_sender_filter"],
                diag["skipped_subject_filter"],
                diag["skipped_self_notification"],
            )
            return diag

        logger.info("[邮件监听] 头部筛选完成：候选 %d 封，开始获取正文", len(matched_header_uids))

        raw_messages = {}
        for uid in matched_header_uids:
            try:
                fetched = client.fetch([uid], ['BODY.PEEK[]'])
                raw_messages.update(fetched or {})
            except Exception as exc:
                logger.warning("[邮件监听] 获取邮件 uid=%s 内容失败，已跳过: %s", uid, exc)
                continue

        if not raw_messages:
            logger.warning("[邮件监听] 命中邮件头 %d 封，但正文均获取失败", len(matched_header_uids))
            return diag

        for uid, data in raw_messages.items():
            raw_body = data.get(b'BODY.PEEK[]') or data.get(b'BODY[]') or data.get(b'BODY[]PEEK')
            if not raw_body:
                continue

            try:
                msg = email.message_from_bytes(raw_body)
            except Exception:
                continue

            cached_header = header_cache.get(uid, {})
            message_id = cached_header.get("message_id") or msg.get('Message-ID', '') or msg.get('Message-Id', '')
            subject = cached_header.get("subject") or _decode_header_value(msg.get('Subject', ''))
            message_items = _extract_new_release_items_from_mail(msg)
            if not message_items:
                fallback_rjcodes = _extract_rjcodes_from_mail(msg)
                subject_rjcodes = _extract_rjcodes_from_text(subject)
                for code in subject_rjcodes:
                    if code not in fallback_rjcodes:
                        fallback_rjcodes.append(code)
                message_items = [
                    {
                        "rjcode": code,
                        "title": subject,
                        "circle_name": "",
                        "price_text": "",
                        "work_type": "",
                        "image_url": "",
                        "product_url": "",
                    }
                    for code in fallback_rjcodes
                ]

            diag["matched_mails"] += 1
            if message_items:
                mail_rjcodes = [str(item.get("rjcode") or "").strip().upper() for item in message_items if str(item.get("rjcode") or "").strip()]
                logger.info("[邮件监听] 邮件 uid=%s 主题=%r 解析到新作: %s", uid, subject, mail_rjcodes)
                diag["mail_summaries"].append({
                    "uid": str(uid),
                    "subject": subject,
                    "message_id": message_id,
                    "item_count": len(message_items),
                    "rjcodes": mail_rjcodes,
                })
                for item in message_items:
                    parsed_items.append({
                        **item,
                        "mail_uid": str(uid),
                        "mail_subject": subject,
                        "message_id": str(message_id or ""),
                    })
                self._total_mails_processed += 1
            else:
                logger.warning("[邮件监听] 邮件 uid=%s 主题=%r 未解析到任何新作卡片", uid, subject)

            if message_id:
                self._processed_message_ids.add(message_id)
                # 防止无限增长
                if len(self._processed_message_ids) > 2000:
                    self._processed_message_ids = set(list(self._processed_message_ids)[-1000:])

            processed_uids.append(uid)

        # 对收集到的作品去重后触发索引
        triggered = 0
        now = time.time()
        self._processed_rjcodes = {
            k: v for k, v in self._processed_rjcodes.items()
            if now - v < self._dedup_ttl
        }
        unique_items: List[Dict[str, str]] = []
        seen_batch_rjcodes: Set[str] = set()
        for item in parsed_items:
            rjcode = str(item.get("rjcode") or "").strip().upper()
            if not rjcode or rjcode in seen_batch_rjcodes:
                continue
            seen_batch_rjcodes.add(rjcode)
            if rjcode in self._processed_rjcodes:
                logger.debug("[邮件监听] RJ 号 %s 在 24h 内已处理，跳过", rjcode)
                continue
            if self._is_rjcode_persistently_processed(rjcode):
                logger.info("[邮件监听] RJ 号 %s 已由邮件监听写入过索引，跳过重复执行", rjcode)
                self._processed_rjcodes[rjcode] = now
                continue
            self._processed_rjcodes[rjcode] = now
            self._total_rjcodes_triggered += 1
            triggered += 1
            diag["rjcodes"].append(rjcode)
            unique_items.append(item)
        diag["items"] = unique_items

        batch_id = f"email-watch-{uuid.uuid4().hex}"
        if unique_items:
            triggered_uids: Set[str] = {
                str(item.get("mail_uid") or "").strip()
                for item in unique_items
                if str(item.get("mail_uid") or "").strip()
            }
            if self._loop and not self._loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(
                    self._trigger_index_for_rjcodes(unique_items, config, batch_id),
                    self._loop,
                )
                future.add_done_callback(
                    lambda done: logger.warning(
                        "[邮件监听] 后台社团索引失败: %s",
                        done.exception(),
                    )
                    if done.exception()
                    else logger.info("[邮件监听] 后台社团索引完成: %s", diag["rjcodes"])
                )
            else:
                logger.warning("[邮件监听] 事件循环不可用，无法触发新作批次索引: %s", diag["rjcodes"])
                triggered_uids = set()

            processed_triggered_uids = [uid for uid in processed_uids if str(uid) in triggered_uids]
            # 标记已读：只标记已成功派发后台索引的邮件，避免手动检查接口被索引耗时拖到超时。
            if config.email_watcher.mark_as_read and processed_triggered_uids:
                try:
                    client.add_flags(processed_triggered_uids, [SEEN])
                except Exception as exc:
                    logger.warning("[邮件监听] 标记已读失败: %s", exc)

            # 移入指定文件夹：只移动“成功触发任务”的邮件
            move_folder = str(config.email_watcher.move_to_folder or "").strip()
            if move_folder and processed_triggered_uids:
                try:
                    client.move(processed_triggered_uids, move_folder)
                except Exception as exc:
                    logger.warning("[邮件监听] 移动邮件失败 (%s): %s", move_folder, exc)

        diag["count"] = triggered
        try:
            from ..core.activity_log_service import write_activity_log as _wal
        except ImportError:
            try:
                from .activity_log_service import write_activity_log as _wal
            except ImportError:
                _wal = None
        if _wal:
            if triggered > 0:
                circle_names = [
                    str(item.get("circle_name") or "").strip()
                    for item in unique_items
                    if str(item.get("circle_name") or "").strip()
                ]
                unique_circles = list(dict.fromkeys(circle_names))
                summary = (
                    f"监视新作：发现 {diag['unseen_total']} 封未读，"
                    f"识别新作 {triggered} 个，涉及社团 {len(unique_circles)} 个"
                )
                status = "success"
            elif diag["unseen_total"] == 0:
                summary = f"监视新作：无未读邮件（sender_filter={config.email_watcher.sender_filter}）"
                status = "info"
            else:
                summary = f"监视新作：未读 {diag['unseen_total']} 封，匹配 {diag['matched_mails']} 封，无可识别新作"
                status = "info"
            try:
                _wal(
                    category="email_watcher",
                    action="fetch_check",
                    status=status,
                    summary=summary,
                    detail={
                        "mode": "email_new_release_batch",
                        "batch_id": batch_id,
                        "unseen_total": diag["unseen_total"],
                        "matched_mails": diag["matched_mails"],
                        "triggered": triggered,
                        "rjcodes": diag["rjcodes"],
                        "circle_names": list(dict.fromkeys(
                            str(item.get("circle_name") or "").strip()
                            for item in unique_items
                            if str(item.get("circle_name") or "").strip()
                        )),
                        "items": unique_items[:80],
                        "mail_summaries": diag["mail_summaries"][:20],
                        "skipped_sender_filter": diag["skipped_sender_filter"],
                        "skipped_subject_filter": diag["skipped_subject_filter"],
                        "skipped_self_notification": diag["skipped_self_notification"],
                        "skipped_read": diag["skipped_read"],
                        "dlsite_subject_total": diag["dlsite_subject_total"],
                        "dlsite_from_total": diag["dlsite_from_total"],
                        "sender_filter": config.email_watcher.sender_filter,
                        "subject_filter": config.email_watcher.subject_filter,
                    },
                )
            except Exception as log_exc:
                logger.warning("[邮件监听] 写活动日志失败: %s", log_exc)
        return diag

    async def _trigger_index_for_rjcode(self, item: Dict[str, str], config, batch_id: str):
        """
        通过 RJ 号查询社团名，判断是否已有社团，选择全量/增量索引。
        """
        from .circle_completion_service import get_circle_completion_service
        from .dlsite_service import get_dlsite_service
        from ..models.database import CircleCatalog, SessionLocal

        rjcode = str(item.get("rjcode") or "").strip().upper()
        logger.info("[邮件监听] 开始处理 RJ: %s", rjcode)

        # 通过 RJ 号获取社团信息
        dlsite_service = get_dlsite_service()
        try:
            product_info_result = await dlsite_service.get_product_info(rjcode)
        except Exception as exc:
            logger.warning("[邮件监听] 获取 %s 产品信息失败: %s", rjcode, exc)
            return {"success": False, "rjcode": rjcode, "error": str(exc), "item": item}

        if not product_info_result:
            logger.warning("[邮件监听] %s 未查到产品信息，跳过", rjcode)
            return {"success": False, "rjcode": rjcode, "error": "未查到产品信息", "item": item}

        product = product_info_result.get('product') or {}
        circle_name = str(product.get('maker_name') or "").strip()
        maker_id = str(product.get('maker_id') or "").strip().upper()

        if not circle_name:
            logger.warning("[邮件监听] %s 无法获取社团名，跳过", rjcode)
            return {"success": False, "rjcode": rjcode, "error": "无法获取社团名", "item": item}

        logger.info("[邮件监听] RJ %s → 社团: %r (maker_id=%s)", rjcode, circle_name, maker_id)

        try:
            direct_result = await self._upsert_email_release_work(
                item=item,
                product=product,
                product_info_result=product_info_result,
                circle_name=circle_name,
                maker_id=maker_id,
            )
            logger.info(
                "[邮件监听] RJ 直入完成: %s → %s (%s)",
                rjcode,
                direct_result.get("circle_name") or circle_name,
                direct_result.get("circle_id") or "",
            )
            try:
                from .activity_log_service import write_activity_log
                write_activity_log(
                    category="email_watcher",
                    action="circle_index_triggered",
                    status="success",
                    summary=f"监视新作直入：{circle_name} · {rjcode}",
                    rjcode=rjcode,
                    detail={
                        "mode": "email_new_release_item",
                        "index_mode": "RJ 直入增量",
                        "batch_id": batch_id,
                        "circle_name": circle_name,
                        "maker_id": maker_id,
                        "rjcode": rjcode,
                        "only_new_works": True,
                        "source": "email_watcher",
                        "circle_id": str(direct_result.get("circle_id") or ""),
                        "mail_subject": str(item.get("mail_subject") or "").strip(),
                        "mail_uid": str(item.get("mail_uid") or "").strip(),
                        "message_id": str(item.get("message_id") or "").strip(),
                        "work_title": str(direct_result.get("title") or item.get("title") or "").strip(),
                        "mail_circle_name": str(item.get("circle_name") or "").strip(),
                        "price_text": str(item.get("price_text") or "").strip(),
                        "work_type": str(item.get("work_type") or "").strip(),
                        "image_url": str(direct_result.get("image_url") or item.get("image_url") or "").strip(),
                        "product_url": str(item.get("product_url") or "").strip(),
                        "direct_upsert": True,
                    },
                )
            except Exception:
                pass
            return direct_result
        except Exception as direct_exc:
            logger.warning("[邮件监听] RJ 直入失败，回退社团索引: %s -> %s", rjcode, direct_exc, exc_info=True)

        # 判断该社团是否已建立索引
        circle_service = get_circle_completion_service()
        normalized_name = circle_service.normalize_circle_name(circle_name)
        catalog_exists = False
        try:
            db = SessionLocal()
            try:
                existing = (
                    db.query(CircleCatalog)
                    .filter(CircleCatalog.circle_name_normalized == normalized_name)
                    .first()
                )
                catalog_exists = existing is not None
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[邮件监听] 查询社团数据库失败: %s", exc)

        only_new = catalog_exists
        index_mode = "增量（only_new_works）" if only_new else "全量（首次建立）"
        logger.info("[邮件监听] 触发社团索引: %r，模式: %s", circle_name, index_mode)

        try:
            result = await circle_service.index_circle_catalog(
                circle_name,
                only_new_works=only_new,
                include_dlsite=True,
                include_kikoeru=True,
            )
            logger.info("[邮件监听] 社团 %r 索引完成", circle_name)
            tagged_work = await self._mark_email_watcher_tag(rjcode)
            try:
                from .activity_log_service import write_activity_log
                write_activity_log(
                    category="email_watcher",
                    action="circle_index_triggered",
                    status="success",
                    summary=f"监视新作：{circle_name} · {rjcode} · {index_mode}",
                    rjcode=rjcode,
                    detail={
                        "mode": "email_new_release_item",
                        "batch_id": batch_id,
                        "circle_name": circle_name,
                        "maker_id": maker_id,
                        "rjcode": rjcode,
                        "only_new_works": only_new,
                        "index_mode": index_mode,
                        "source": "email_watcher",
                        "circle_id": str(result.get("circle_id") or ""),
                        "mail_subject": str(item.get("mail_subject") or "").strip(),
                        "mail_uid": str(item.get("mail_uid") or "").strip(),
                        "message_id": str(item.get("message_id") or "").strip(),
                        "work_title": str(item.get("title") or tagged_work.get("title") or "").strip(),
                        "mail_circle_name": str(item.get("circle_name") or "").strip(),
                        "price_text": str(item.get("price_text") or "").strip(),
                        "work_type": str(item.get("work_type") or "").strip(),
                        "image_url": str(item.get("image_url") or "").strip(),
                        "product_url": str(item.get("product_url") or "").strip(),
                        "tagged_work": tagged_work,
                    },
                )
            except Exception:
                pass
            return {
                "success": True,
                "mail_rjcode": str(rjcode or "").strip().upper(),
                "circle_id": str(result.get("circle_id") or ""),
                "circle_name": circle_name,
                "maker_id": maker_id,
                "canonical_rjcode": str(tagged_work.get("canonical_rjcode") or ""),
                "display_rjcode": str(tagged_work.get("display_rjcode") or ""),
                "title": str(item.get("title") or tagged_work.get("title") or ""),
                "price_text": str(item.get("price_text") or "").strip(),
                "work_type": str(item.get("work_type") or "").strip(),
                "image_url": str(item.get("image_url") or "").strip(),
                "product_url": str(item.get("product_url") or "").strip(),
            }
        except Exception as exc:
            logger.error("[邮件监听] 社团 %r 索引失败: %s", circle_name, exc, exc_info=True)
            try:
                from .activity_log_service import write_activity_log
                write_activity_log(
                    category="email_watcher",
                    action="circle_index_triggered",
                    status="failed",
                    summary=f"监视新作失败：{circle_name} · {rjcode} · {exc}",
                    rjcode=rjcode,
                    detail={
                        "mode": "email_new_release_item",
                        "batch_id": batch_id,
                        "circle_name": circle_name,
                        "rjcode": rjcode,
                        "mail_subject": str(item.get("mail_subject") or "").strip(),
                        "work_title": str(item.get("title") or "").strip(),
                        "mail_circle_name": str(item.get("circle_name") or "").strip(),
                        "price_text": str(item.get("price_text") or "").strip(),
                        "work_type": str(item.get("work_type") or "").strip(),
                        "image_url": str(item.get("image_url") or "").strip(),
                        "product_url": str(item.get("product_url") or "").strip(),
                        "error": str(exc),
                    },
                )
            except Exception:
                pass
            return {"success": False, "rjcode": rjcode, "circle_name": circle_name, "error": str(exc), "item": item}

    # ------------------------------------------------------------------
    # 连接测试
    # ------------------------------------------------------------------

    def _do_test_connection(self, host: str, port: int, ssl: bool, username: str, password: str, mailbox: str) -> Dict:
        """执行 IMAP 连接测试（同步，在 thread 中调用）。"""
        try:
            from imapclient import IMAPClient
        except ImportError:
            return {"success": False, "message": "imapclient 未安装，请执行: pip install imapclient>=3.0.1"}

        try:
            with IMAPClient(host=host, port=port, ssl=ssl, timeout=IMAP_CONNECT_TIMEOUT_SECONDS) as client:
                client.login(username, password)
                client.select_folder(mailbox)
                unseen = client.search(['UNSEEN'])
                return {
                    "success": True,
                    "message": f"连接成功，INBOX 未读邮件: {len(unseen)} 封",
                    "unseen_count": len(unseen),
                }
        except TimeoutError:
            return {
                "success": False,
                "message": f"连接 IMAP 超时（{IMAP_CONNECT_TIMEOUT_SECONDS}s）: {host}:{port}。请检查 Docker 容器到该地址的出站 TCP 连接是否放行。",
            }
        except OSError as exc:
            if getattr(exc, "winerror", None) == 10060 or "timed out" in str(exc).lower():
                return {
                    "success": False,
                    "message": f"连接 IMAP 超时（{IMAP_CONNECT_TIMEOUT_SECONDS}s）: {host}:{port}。请检查 Docker 容器到该地址的出站 TCP 连接是否放行。",
                }
            return {"success": False, "message": f"连接失败: {exc}"}
        except Exception as exc:
            return {"success": False, "message": f"连接失败: {exc}"}


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------

_email_watcher_service: Optional[EmailWatcherService] = None


def get_email_watcher_service() -> EmailWatcherService:
    global _email_watcher_service
    if _email_watcher_service is None:
        _email_watcher_service = EmailWatcherService()
    return _email_watcher_service
