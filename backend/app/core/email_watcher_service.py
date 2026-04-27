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
import logging
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


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
            if result['skipped_read']:
                msg_parts.append(f"已处理去重跳过 {result['skipped_read']} 封")
            if result['rjcodes']:
                msg_parts.append(f"RJ号: {', '.join(result['rjcodes'])}")
            return {"success": True, "message": "；".join(msg_parts), **result}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

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

        with IMAPClient(host=imap_host, port=imap_port, ssl=imap_ssl) as client:
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

        with IMAPClient(host=imap_host, port=imap_port, ssl=imap_ssl) as client:
            client.login(config.email_watcher.username, config.email_watcher.password)
            client.select_folder(config.email_watcher.mailbox)
            result = self._fetch_and_process(client, config)
            self._last_check_at = datetime.now().isoformat(timespec="seconds")
            return result

    def _fetch_and_process(self, client, config) -> dict:
        """
        搜索未读 DLsite 邮件，解析提取 RJ 号，触发社团索引。
        返回诊断字典：{ count, unseen_total, matched_mails, rjcodes, skipped_read, skipped_subject_filter }
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
            "skipped_read": 0,
            "skipped_subject_filter": 0,
        }

        # 构建搜索条件
        criteria = ['UNSEEN']
        if sender_filter:
            criteria += ['FROM', sender_filter]

        try:
            uids = client.search(criteria)
        except Exception as exc:
            logger.warning("[邮件监听] 搜索邮件失败: %s", exc)
            return diag

        diag["unseen_total"] = len(uids)
        logger.info("[邮件监听] 搜索条件=%s 找到未读邮件 %d 封", criteria, len(uids))

        if not uids:
            return diag

        # 批量获取邮件
        try:
            raw_messages = client.fetch(uids, ['BODY[]', 'ENVELOPE'])
        except Exception as exc:
            logger.warning("[邮件监听] 获取邮件内容失败: %s", exc)
            return diag

        all_rjcodes: Set[str] = set()
        processed_uids = []

        for uid, data in raw_messages.items():
            raw_body = data.get(b'BODY[]') or data.get(b'BODY[]PEEK')
            if not raw_body:
                continue

            try:
                msg = email.message_from_bytes(raw_body)
            except Exception:
                continue

            # 去重：Message-ID
            message_id = msg.get('Message-ID', '') or msg.get('Message-Id', '')
            if message_id and message_id in self._processed_message_ids:
                diag["skipped_read"] += 1
                processed_uids.append(uid)
                continue

            # 主题过滤
            subject = _decode_header_value(msg.get('Subject', ''))
            logger.info("[邮件监听] uid=%s 主题=%r", uid, subject)
            if subject_filter and subject_filter not in subject:
                logger.info("[邮件监听] uid=%s 主题过滤不匹配（关键词=%r），跳过", uid, subject_filter)
                diag["skipped_subject_filter"] += 1
                continue

            # 提取 RJ 号（同时扫描 plain + html，兼容 DLsite RJ 号仅在 HTML href 中的格式）
            rjcodes = _extract_rjcodes_from_mail(msg)
            # 主题中也补充扫描
            subject_rjcodes = _extract_rjcodes_from_text(subject)
            for code in subject_rjcodes:
                if code not in rjcodes:
                    rjcodes.append(code)

            diag["matched_mails"] += 1
            if rjcodes:
                logger.info("[邮件监听] 邮件 uid=%s 主题=%r 提取到 RJ: %s", uid, subject, rjcodes)
                all_rjcodes.update(rjcodes)
                self._total_mails_processed += 1
            else:
                logger.warning("[邮件监听] 邮件 uid=%s 主题=%r 未提取到任何 RJ 号", uid, subject)

            if message_id:
                self._processed_message_ids.add(message_id)
                # 防止无限增长
                if len(self._processed_message_ids) > 2000:
                    self._processed_message_ids = set(list(self._processed_message_ids)[-1000:])

            processed_uids.append(uid)

        # 标记已读
        if config.email_watcher.mark_as_read and processed_uids:
            try:
                client.add_flags(processed_uids, [SEEN])
            except Exception as exc:
                logger.warning("[邮件监听] 标记已读失败: %s", exc)

        # 移入指定文件夹
        move_folder = str(config.email_watcher.move_to_folder or "").strip()
        if move_folder and processed_uids:
            try:
                client.move(processed_uids, move_folder)
            except Exception as exc:
                logger.warning("[邮件监听] 移动邮件失败 (%s): %s", move_folder, exc)

        # 对收集到的 RJ 号去重后触发索引
        triggered = 0
        now = time.time()
        # 清理过期缓存
        self._processed_rjcodes = {
            k: v for k, v in self._processed_rjcodes.items()
            if now - v < self._dedup_ttl
        }
        for rjcode in all_rjcodes:
            if rjcode in self._processed_rjcodes:
                logger.debug("[邮件监听] RJ 号 %s 在 24h 内已处理，跳过", rjcode)
                continue
            self._processed_rjcodes[rjcode] = now
            self._total_rjcodes_triggered += 1
            triggered += 1
            diag["rjcodes"].append(rjcode)
            # 在 asyncio 事件循环中调度触发索引（thread-safe）
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self._trigger_index_for_rjcode(rjcode, config),
                    self._loop,
                )
            else:
                logger.warning("[邮件监听] 事件循环不可用，无法触发 RJ %s 索引", rjcode)

        diag["count"] = triggered
        # 写活动日志：每次 fetch 完成后记录一条诊断日志
        try:
            from ..core.activity_log_service import write_activity_log as _wal
        except ImportError:
            try:
                from .activity_log_service import write_activity_log as _wal
            except ImportError:
                _wal = None
        if _wal:
            if triggered > 0:
                summary = f"邮件监听：发现 {diag['unseen_total']} 封未读，触发社团索引 {triggered} 个（{', '.join(diag['rjcodes'])}）"
                status = "success"
            elif diag["unseen_total"] == 0:
                summary = f"邮件监听：无未读邮件（sender_filter={config.email_watcher.sender_filter}）"
                status = "info"
            else:
                summary = f"邮件监听：未读 {diag['unseen_total']} 封，匹配 {diag['matched_mails']} 封，无新 RJ 号"
                status = "info"
            try:
                _wal(
                    category="email_watcher",
                    action="fetch_check",
                    status=status,
                    summary=summary,
                    detail={
                        "unseen_total": diag["unseen_total"],
                        "matched_mails": diag["matched_mails"],
                        "triggered": triggered,
                        "rjcodes": diag["rjcodes"],
                        "skipped_subject_filter": diag["skipped_subject_filter"],
                        "skipped_read": diag["skipped_read"],
                        "sender_filter": config.email_watcher.sender_filter,
                        "subject_filter": config.email_watcher.subject_filter,
                    },
                )
            except Exception as log_exc:
                logger.warning("[邮件监听] 写活动日志失败: %s", log_exc)
        return diag

    async def _trigger_index_for_rjcode(self, rjcode: str, config):
        """
        通过 RJ 号查询社团名，判断是否已有社团，选择全量/增量索引。
        """
        from .circle_completion_service import get_circle_completion_service
        from .dlsite_service import get_dlsite_service
        from ..models.database import CircleCatalog, SessionLocal

        logger.info("[邮件监听] 开始处理 RJ: %s", rjcode)

        # 通过 RJ 号获取社团信息
        dlsite_service = get_dlsite_service()
        try:
            product_info_result = await dlsite_service.get_product_info(rjcode)
        except Exception as exc:
            logger.warning("[邮件监听] 获取 %s 产品信息失败: %s", rjcode, exc)
            return

        if not product_info_result:
            logger.warning("[邮件监听] %s 未查到产品信息，跳过", rjcode)
            return

        product = product_info_result.get('product') or {}
        circle_name = str(product.get('maker_name') or "").strip()
        maker_id = str(product.get('maker_id') or "").strip().upper()

        if not circle_name:
            logger.warning("[邮件监听] %s 无法获取社团名，跳过", rjcode)
            return

        logger.info("[邮件监听] RJ %s → 社团: %r (maker_id=%s)", rjcode, circle_name, maker_id)

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
            await circle_service.index_circle_catalog(
                circle_name,
                only_new_works=only_new,
                include_dlsite=True,
                include_kikoeru=True,
            )
            logger.info("[邮件监听] 社团 %r 索引完成", circle_name)
            # 标记该 RJ 号为 email_watcher 来源（新作标识）
            try:
                from ..models.database import CircleWork, SessionLocal
                db = SessionLocal()
                try:
                    work = (
                        db.query(CircleWork)
                        .filter(
                            (CircleWork.canonical_rjcode == rjcode) |
                            (CircleWork.display_rjcode == rjcode)
                        )
                        .first()
                    )
                    if work:
                        tags = list(work.source_tags or [])
                        if "email_watcher" not in tags:
                            tags.append("email_watcher")
                            work.source_tags = tags
                            db.commit()
                            logger.info("[邮件监听] 已为 %s 添加 email_watcher 来源标签", rjcode)
                finally:
                    db.close()
            except Exception as tag_exc:
                logger.warning("[邮件监听] 更新 source_tags 失败: %s", tag_exc)
            try:
                from .activity_log_service import write_activity_log
                write_activity_log(
                    category="email_watcher",
                    action="circle_index_triggered",
                    status="success",
                    summary=f"邮件监听触发社团索引：{circle_name}（{rjcode}，{index_mode}）",
                    rjcode=rjcode,
                    detail={
                        "circle_name": circle_name,
                        "maker_id": maker_id,
                        "rjcode": rjcode,
                        "only_new_works": only_new,
                        "index_mode": index_mode,
                        "source": "email_watcher",
                    },
                )
            except Exception:
                pass
        except Exception as exc:
            logger.error("[邮件监听] 社团 %r 索引失败: %s", circle_name, exc, exc_info=True)
            try:
                from .activity_log_service import write_activity_log
                write_activity_log(
                    category="email_watcher",
                    action="circle_index_triggered",
                    status="error",
                    summary=f"邮件监听触发社团索引失败：{circle_name}（{rjcode}）：{exc}",
                    rjcode=rjcode,
                    detail={"circle_name": circle_name, "rjcode": rjcode, "error": str(exc)},
                )
            except Exception:
                pass

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
            with IMAPClient(host=host, port=port, ssl=ssl) as client:
                client.login(username, password)
                client.select_folder(mailbox)
                unseen = client.search(['UNSEEN'])
                return {
                    "success": True,
                    "message": f"连接成功，INBOX 未读邮件: {len(unseen)} 封",
                    "unseen_count": len(unseen),
                }
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
