import base64
import hashlib
import hmac
import io
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config.settings import get_config, save_config
from ..models.database import (
    SecurityGateAuthLog,
    SecurityGateBlacklist,
    SecurityGateEmailThrottle,
    SessionLocal,
    get_local_now,
)

logger = logging.getLogger(__name__)

COOKIE_NAME = "kikoerumanager_gate"
ISSUER = "KikoeruManager"
ACCOUNT = "System Gate"


class SecurityGateService:
    """系统级 Google Authenticator 门禁服务。"""

    def get_client_ip(self, request: Request) -> str:
        cfg = get_config().security_gate
        if cfg.trust_proxy_headers:
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                first = xff.split(",", 1)[0].strip()
                if first:
                    return first
            real_ip = request.headers.get("x-real-ip", "").strip()
            if real_ip:
                return real_ip
        return request.client.host if request.client else "unknown"

    def is_bound(self) -> bool:
        return bool((get_config().security_gate.secret or "").strip())

    def is_enforced(self) -> bool:
        cfg = get_config().security_gate
        return bool(cfg.enabled and cfg.secret)

    def public_state(self, request: Optional[Request] = None) -> dict:
        cfg = get_config().security_gate
        ip_address = self.get_client_ip(request) if request else ""
        blocked = self.get_active_blacklist(ip_address) if ip_address else None
        return {
            "enabled": bool(cfg.enabled),
            "enforced": bool(cfg.enabled and cfg.secret),
            "bound": bool(cfg.secret),
            "has_pending_setup": bool(cfg.pending_secret),
            "allow_remember_device": bool(cfg.allow_remember_device),
            "session_hours": int(cfg.session_hours or 8),
            "remember_days": int(cfg.remember_days or 30),
            "blacklist_enabled": bool(cfg.blacklist_enabled),
            "failure_window_minutes": int(cfg.failure_window_minutes or 10),
            "max_failures": int(cfg.max_failures or 5),
            "blocked": bool(blocked),
            "blocked_info": blocked.to_dict() if blocked else None,
        }

    def sanitize_config(self) -> dict:
        data = get_config().security_gate.model_dump()
        data["secret"] = "********" if data.get("secret") else ""
        data["pending_secret"] = "********" if data.get("pending_secret") else ""
        data["bound"] = bool(get_config().security_gate.secret)
        data["has_pending_setup"] = bool(get_config().security_gate.pending_secret)
        return data

    def create_setup(self) -> dict:
        secret = self.generate_secret()
        cfg = get_config().security_gate
        save_config({"security_gate": {**cfg.model_dump(), "pending_secret": secret}})
        return self._setup_payload(secret)

    def confirm_setup(self, code: str, request: Request) -> dict:
        cfg = get_config().security_gate
        secret = (cfg.pending_secret or cfg.secret or "").strip()
        if not secret:
            raise ValueError("尚未生成验证器绑定密钥")
        if not self.verify_totp(secret, code):
            self.record_auth_event(
                request=request,
                event_type="setup_failed",
                success=False,
                failure_reason="验证码错误",
                code=code,
            )
            raise ValueError("验证码错误，请确认手机时间已自动同步")
        save_config({"security_gate": {**cfg.model_dump(), "secret": secret, "pending_secret": ""}})
        self.record_auth_event(request=request, event_type="setup_confirmed", success=True, code=code)
        return {"ok": True, "message": "验证器绑定完成"}

    def reset_setup(self, request: Request) -> dict:
        cfg = get_config().security_gate
        save_config({"security_gate": {**cfg.model_dump(), "secret": "", "pending_secret": "", "enabled": False}})
        self.record_auth_event(request=request, event_type="totp_reset", success=True)
        self.maybe_send_alert("totp_reset", self.get_client_ip(request), request.headers.get("user-agent", ""), str(request.url.path), {})
        return {"ok": True, "message": "验证器已重置，门禁已关闭"}

    def verify_access(self, code: str, remember: bool, request: Request) -> dict:
        cfg = get_config().security_gate
        ip_address = self.get_client_ip(request)
        blocked = self.get_active_blacklist(ip_address)
        if blocked:
            self.record_blocked_visit(request, blocked)
            return {"ok": False, "blocked": True, "message": "当前来源已被系统阻止"}
        if not cfg.secret:
            return {"ok": False, "message": "验证器尚未绑定"}
        if self.verify_totp(cfg.secret, code):
            hours = int(cfg.session_hours or 8)
            remember_allowed = bool(remember and cfg.allow_remember_device)
            if remember_allowed:
                expires_at = get_local_now() + timedelta(days=int(cfg.remember_days or 30))
            else:
                expires_at = get_local_now() + timedelta(hours=hours)
            token = self.create_session_token(expires_at)
            self.record_auth_event(request=request, event_type="verify_success", success=True, code=code)
            return {
                "ok": True,
                "blocked": False,
                "token": token,
                "max_age": max(1, int((expires_at - get_local_now()).total_seconds())),
                "expires_at": expires_at.isoformat(),
            }

        triggered = self.handle_failed_verify(request, code)
        return {
            "ok": False,
            "blocked": bool(triggered.get("blocked")),
            "message": triggered.get("message") or "验证码错误",
            "remaining_attempts": triggered.get("remaining_attempts", 0),
        }

    def verify_cookie(self, token: str) -> bool:
        cfg = get_config().security_gate
        if not token or not cfg.secret:
            return False
        try:
            exp_text, nonce, sig = token.split(".", 2)
            expected = self._sign_token(exp_text, nonce)
            if not hmac.compare_digest(sig, expected):
                return False
            return int(exp_text) > int(time.time())
        except Exception:
            return False

    def create_session_token(self, expires_at: datetime) -> str:
        exp_text = str(int(expires_at.timestamp()))
        nonce = base64.urlsafe_b64encode(os.urandom(12)).decode("ascii").rstrip("=")
        return f"{exp_text}.{nonce}.{self._sign_token(exp_text, nonce)}"

    def clear_cookie_kwargs(self) -> dict:
        return {"key": COOKIE_NAME, "path": "/"}

    def get_active_blacklist(self, ip_address: str) -> Optional[SecurityGateBlacklist]:
        if not ip_address:
            return None
        with SessionLocal() as db:
            return (
                db.query(SecurityGateBlacklist)
                .filter(SecurityGateBlacklist.ip_address == ip_address, SecurityGateBlacklist.active == True)
                .first()
            )

    def record_blocked_visit(self, request: Request, item: SecurityGateBlacklist) -> None:
        item.last_seen_at = get_local_now()
        with SessionLocal() as db:
            existing = db.query(SecurityGateBlacklist).filter(SecurityGateBlacklist.id == item.id).first()
            if existing:
                existing.last_seen_at = item.last_seen_at
                db.commit()
        self.record_auth_event(
            request=request,
            event_type="blocked_visit",
            success=False,
            failure_reason="来源已被拉黑",
            triggered_blacklist=True,
        )
        self.maybe_send_alert(
            "blocked_visit",
            item.ip_address,
            request.headers.get("user-agent", ""),
            str(request.url.path),
            {"failure_count": item.failure_count, "reason": item.reason},
        )

    def handle_failed_verify(self, request: Request, code: str) -> dict:
        cfg = get_config().security_gate
        ip_address = self.get_client_ip(request)
        now = get_local_now()
        window_start = now - timedelta(minutes=int(cfg.failure_window_minutes or 10))
        with SessionLocal() as db:
            failure_count = (
                db.query(SecurityGateAuthLog)
                .filter(
                    SecurityGateAuthLog.ip_address == ip_address,
                    SecurityGateAuthLog.success == False,
                    SecurityGateAuthLog.event_type.in_(["verify_failed", "setup_failed"]),
                    SecurityGateAuthLog.created_at >= window_start,
                )
                .count()
            ) + 1
            should_block = bool(cfg.blacklist_enabled and failure_count >= int(cfg.max_failures or 5))
            self._insert_auth_log(
                db=db,
                request=request,
                event_type="verify_failed",
                success=False,
                failure_reason="验证码错误",
                code=code,
                triggered_blacklist=should_block,
            )
            if should_block:
                existing = db.query(SecurityGateBlacklist).filter(SecurityGateBlacklist.ip_address == ip_address).first()
                if existing:
                    existing.active = True
                    existing.permanent = True
                    existing.failure_count = failure_count
                    existing.reason = f"{cfg.failure_window_minutes} 分钟内失败 {failure_count} 次"
                    existing.last_seen_at = now
                    if not existing.blocked_at:
                        existing.blocked_at = now
                    existing.unblocked_at = None
                    existing.unblock_reason = ""
                else:
                    db.add(SecurityGateBlacklist(
                        id=str(uuid.uuid4()),
                        ip_address=ip_address,
                        reason=f"{cfg.failure_window_minutes} 分钟内失败 {failure_count} 次",
                        failure_count=failure_count,
                        permanent=True,
                        active=True,
                        blocked_at=now,
                        last_seen_at=now,
                    ))
                db.commit()
                self.maybe_send_alert(
                    "blacklisted",
                    ip_address,
                    request.headers.get("user-agent", ""),
                    str(request.url.path),
                    {"failure_count": failure_count},
                )
                return {"blocked": True, "remaining_attempts": 0, "message": "失败次数过多，当前来源已被永久拉黑"}
            db.commit()
        remaining = max(0, int(cfg.max_failures or 5) - failure_count)
        self.maybe_send_alert(
            "verify_failed",
            ip_address,
            request.headers.get("user-agent", ""),
            str(request.url.path),
            {"failure_count": failure_count, "remaining_attempts": remaining},
        )
        return {"blocked": False, "remaining_attempts": remaining, "message": "验证码错误"}

    def list_logs(self, db: Session, result: str = "all", ip: str = "", limit: int = 50) -> list[dict]:
        query = db.query(SecurityGateAuthLog)
        if result == "success":
            query = query.filter(SecurityGateAuthLog.success == True)
        elif result == "failed":
            query = query.filter(SecurityGateAuthLog.success == False)
        elif result == "blacklist":
            query = query.filter(SecurityGateAuthLog.triggered_blacklist == True)
        if ip:
            query = query.filter(SecurityGateAuthLog.ip_address.contains(ip.strip()))
        rows = query.order_by(desc(SecurityGateAuthLog.created_at)).limit(min(max(int(limit or 50), 1), 200)).all()
        return [row.to_dict() for row in rows]

    def list_blacklist(self, db: Session, include_inactive: bool = False) -> list[dict]:
        query = db.query(SecurityGateBlacklist)
        if not include_inactive:
            query = query.filter(SecurityGateBlacklist.active == True)
        rows = query.order_by(desc(SecurityGateBlacklist.blocked_at)).limit(200).all()
        return [row.to_dict() for row in rows]

    def unblock(self, db: Session, item_id: str, reason: str, request: Request) -> dict:
        item = db.query(SecurityGateBlacklist).filter(SecurityGateBlacklist.id == item_id).first()
        if not item:
            raise ValueError("黑名单记录不存在")
        item.active = False
        item.unblocked_at = get_local_now()
        item.unblock_reason = reason or "管理员手动解除"
        db.commit()
        self.record_auth_event(
            request=request,
            event_type="blacklist_unblocked",
            success=True,
            failure_reason="",
            detail={"ip_address": item.ip_address, "reason": item.unblock_reason},
        )
        return item.to_dict()

    def record_auth_event(
        self,
        request: Request,
        event_type: str,
        success: bool,
        failure_reason: str = "",
        code: str = "",
        triggered_blacklist: bool = False,
        detail: Optional[dict] = None,
    ) -> None:
        with SessionLocal() as db:
            self._insert_auth_log(
                db=db,
                request=request,
                event_type=event_type,
                success=success,
                failure_reason=failure_reason,
                code=code,
                triggered_blacklist=triggered_blacklist,
                detail=detail,
            )
            db.commit()

    def maybe_send_alert(self, event_type: str, ip_address: str, user_agent: str, path: str, detail: dict) -> None:
        cfg = get_config().security_gate
        if not cfg.email_alert_enabled:
            return
        if event_type == "verify_failed" and not cfg.email_alert_on_failure:
            return
        if event_type == "blacklisted" and not cfg.email_alert_on_blacklist:
            return
        if event_type == "blocked_visit" and not cfg.email_alert_on_blocked_visit:
            return
        if event_type == "totp_reset" and not cfg.email_alert_on_reset:
            return

        throttle_key = f"{event_type}:{ip_address}"
        now = get_local_now()
        with SessionLocal() as db:
            row = db.query(SecurityGateEmailThrottle).filter(SecurityGateEmailThrottle.throttle_key == throttle_key).first()
            if row and row.last_sent_at and (now - row.last_sent_at).total_seconds() < int(cfg.email_alert_min_interval_seconds or 300):
                return
            if row:
                row.last_sent_at = now
            else:
                db.add(SecurityGateEmailThrottle(throttle_key=throttle_key, last_sent_at=now))
            db.commit()

        try:
            import asyncio
            from .notification_email_service import send_notification_email

            title_map = {
                "verify_failed": "门禁验证码失败",
                "blacklisted": "门禁已自动拉黑来源",
                "blocked_visit": "黑名单来源再次访问",
                "totp_reset": "验证器绑定已重置",
            }
            subject = f"[KikoeruManager] {title_map.get(event_type, '系统门禁提醒')}"
            html = self._build_alert_html(title_map.get(event_type, event_type), ip_address, user_agent, path, detail)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(send_notification_email(subject, html))
            except RuntimeError:
                asyncio.run(send_notification_email(subject, html))
        except Exception:
            logger.warning("[门禁] 邮件提醒发送调度失败", exc_info=True)

    def _insert_auth_log(
        self,
        db: Session,
        request: Request,
        event_type: str,
        success: bool,
        failure_reason: str = "",
        code: str = "",
        triggered_blacklist: bool = False,
        detail: Optional[dict] = None,
    ) -> None:
        code_value = "".join(ch for ch in str(code or "") if ch.isdigit())
        hint = ""
        if code_value:
            hint = f"{code_value[:1]}****{code_value[-1:]}" if len(code_value) >= 2 else "*"
        db.add(SecurityGateAuthLog(
            id=str(uuid.uuid4()),
            event_type=event_type,
            ip_address=self.get_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            path=str(request.url.path),
            success=success,
            failure_reason=failure_reason or "",
            code_length=len(code_value),
            code_hint=hint,
            triggered_blacklist=triggered_blacklist,
            detail=detail or {},
        ))

    def _setup_payload(self, secret: str) -> dict:
        uri = self.otpauth_uri(secret)
        return {
            "secret": secret,
            "otpauth_uri": uri,
            "qr_data_uri": self.qr_data_uri(uri),
        }

    def _sign_token(self, exp_text: str, nonce: str) -> str:
        cfg = get_config().security_gate
        key = hashlib.sha256((cfg.secret or "unbound").encode("utf-8")).digest()
        raw = f"{exp_text}.{nonce}".encode("utf-8")
        return hmac.new(key, raw, hashlib.sha256).hexdigest()

    @staticmethod
    def generate_secret() -> str:
        return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")

    @staticmethod
    def otpauth_uri(secret: str) -> str:
        label = quote(f"{ISSUER}:{ACCOUNT}")
        issuer = quote(ISSUER)
        return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"

    @staticmethod
    def qr_data_uri(uri: str) -> str:
        try:
            import qrcode

            img = qrcode.make(uri)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
        except Exception:
            logger.info("[门禁] qrcode 依赖不可用，前端将只展示密钥和 otpauth URI")
            return ""

    @staticmethod
    def verify_totp(secret: str, code: str, window: int = 1) -> bool:
        cleaned = "".join(ch for ch in str(code or "") if ch.isdigit())
        if len(cleaned) != 6:
            return False
        now_counter = int(time.time() // 30)
        for offset in range(-window, window + 1):
            if hmac.compare_digest(SecurityGateService._totp_at(secret, now_counter + offset), cleaned):
                return True
        return False

    @staticmethod
    def _totp_at(secret: str, counter: int) -> str:
        padding = "=" * ((8 - len(secret) % 8) % 8)
        key = base64.b32decode((secret + padding).upper())
        msg = int(counter).to_bytes(8, "big")
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code_int = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
        return f"{code_int % 1000000:06d}"

    @staticmethod
    def _build_alert_html(title: str, ip_address: str, user_agent: str, path: str, detail: dict) -> str:
        rows = {
            "事件": title,
            "时间": get_local_now().isoformat(timespec="seconds"),
            "IP 地址": ip_address,
            "访问路径": path,
            "浏览器": user_agent,
            "失败次数": detail.get("failure_count", ""),
            "剩余次数": detail.get("remaining_attempts", ""),
            "原因": detail.get("reason", ""),
        }
        body = "".join(
            f"<tr><td style='padding:8px 12px;color:#64748b'>{k}</td><td style='padding:8px 12px;color:#0f172a'>{v}</td></tr>"
            for k, v in rows.items()
            if v not in ("", None)
        )
        return (
            "<div style='font-family:Arial,Helvetica,sans-serif;line-height:1.6'>"
            f"<h2 style='margin:0 0 12px;color:#0f172a'>{title}</h2>"
            "<table style='border-collapse:collapse;border:1px solid #e2e8f0'>"
            f"{body}</table></div>"
        )


_service: Optional[SecurityGateService] = None


def get_security_gate_service() -> SecurityGateService:
    global _service
    if _service is None:
        _service = SecurityGateService()
    return _service
