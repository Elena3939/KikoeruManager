import asyncio
import logging
import smtplib
import ssl
import time
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _build_message(from_email: str, from_name: str, to_email: str, subject: str, html_body: str, text_body: str = None) -> MIMEMultipart:
    msg = MIMEMultipart('alternative')
    clean_subject = subject.replace('\r', '').replace('\n', '')
    msg['Subject'] = Header(clean_subject, 'utf-8')
    msg['From'] = f"{from_name} <{from_email}>" if from_name else from_email
    msg['To'] = to_email
    msg['X-Prekikoeru-Notification'] = '1'
    if text_body:
        msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    return msg


def _send_smtp_sync(cfg, subject: str, html_body: str, text_body: str = None):
    """同步 SMTP 发送，在线程池中调用。

    日志原则：主机 / 端口 / 加密方式 / 发件人 / 收件人 / 主题、html、text 长度
    以及各阶段耗时、异常类型都要落到 logger.info / warning / error。密码绝不输出。
    """
    from_email = cfg.from_email or cfg.username
    mode = "SSL" if cfg.smtp_ssl else ("STARTTLS" if cfg.smtp_starttls else "PLAIN")
    html_len = len(html_body or "")
    text_len = len(text_body or "")
    logger.info(
        "[通知邮件] 准备发送 host=%s port=%s mode=%s from=%s to=%s subject=%r html_len=%d text_len=%d",
        cfg.smtp_host, cfg.smtp_port, mode, from_email, cfg.to_email, subject, html_len, text_len,
    )
    msg = _build_message(from_email, cfg.from_name, cfg.to_email, subject, html_body, text_body)
    msg_size = len(msg.as_string())
    logger.debug("[通知邮件] MIME 包装完成 size=%d bytes", msg_size)

    t_start = time.perf_counter()
    try:
        if cfg.smtp_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=context, timeout=cfg.connect_timeout_seconds) as server:
                t_conn = time.perf_counter()
                logger.debug("[通知邮件] SSL 握手完成 host=%s port=%s elapsed=%.2fs", cfg.smtp_host, cfg.smtp_port, t_conn - t_start)
                if cfg.username:
                    server.login(cfg.username, cfg.password)
                    logger.debug("[通知邮件] 登录成功 user=%s", cfg.username)
                server.sendmail(from_email, [cfg.to_email], msg.as_string())
        elif cfg.smtp_starttls:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.connect_timeout_seconds) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                t_conn = time.perf_counter()
                logger.debug("[通知邮件] STARTTLS 握手完成 host=%s port=%s elapsed=%.2fs", cfg.smtp_host, cfg.smtp_port, t_conn - t_start)
                if cfg.username:
                    server.login(cfg.username, cfg.password)
                    logger.debug("[通知邮件] 登录成功 user=%s", cfg.username)
                server.sendmail(from_email, [cfg.to_email], msg.as_string())
        else:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.connect_timeout_seconds) as server:
                if cfg.username:
                    server.login(cfg.username, cfg.password)
                    logger.debug("[通知邮件] 登录成功 user=%s", cfg.username)
                server.sendmail(from_email, [cfg.to_email], msg.as_string())
    except Exception:
        elapsed = time.perf_counter() - t_start
        logger.warning("[通知邮件] SMTP 发送异常 host=%s mode=%s elapsed=%.2fs", cfg.smtp_host, mode, elapsed)
        raise
    elapsed = time.perf_counter() - t_start
    logger.info(
        "[通知邮件] 发送成功 host=%s mode=%s to=%s size=%d bytes elapsed=%.2fs",
        cfg.smtp_host, mode, cfg.to_email, msg_size, elapsed,
    )


async def send_notification_email(subject: str, html_body: str, text_body: str = None) -> bool:
    """异步发送通知邮件，不阻塞事件循环。

    返回发送是否成功。未启用 / 未配置时会记录 info 日志作为跳过标识。
    """
    from ..config.settings import get_config
    cfg = get_config().notification_email
    if not cfg.enabled:
        logger.info("[通知邮件] 跳过发送：未启用 notification_email.enabled")
        return False
    if not cfg.to_email or not cfg.smtp_host:
        logger.warning("[通知邮件] 跳过发送：配置不完整 to=%r host=%r", cfg.to_email, cfg.smtp_host)
        return False
    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _send_smtp_sync, cfg, subject, html_body, text_body),
            timeout=cfg.send_timeout_seconds
        )
        return True
    except asyncio.TimeoutError:
        logger.error(
            "[通知邮件] 发送超时 host=%s port=%s timeout=%ss subject=%r",
            cfg.smtp_host, cfg.smtp_port, cfg.send_timeout_seconds, subject,
        )
        return False
    except Exception as e:
        logger.error(
            "[通知邮件] 发送失败 host=%s port=%s err_type=%s err=%s subject=%r",
            cfg.smtp_host, cfg.smtp_port, type(e).__name__, e, subject, exc_info=True,
        )
        return False


def _friendly_smtp_error(e: Exception) -> str:
    """将底层 socket/SMTP 异常翻译为可读中文"""
    import smtplib
    msg = str(e)
    msg_lower = msg.lower()
    # DNS 解析失败
    if 'getaddrinfo failed' in msg or 'Name or service not known' in msg or '11003' in msg or '11001' in msg:
        return '无法解析 SMTP 主机名，请确认主机地址填写正确（如 smtp.qq.com、smtp.gmail.com）'
    # 连接拒绝 / 超时
    if 'Connection refused' in msg or 'timed out' in msg_lower or '10061' in msg:
        return '连接被拒绝或超时，请检查主机地址和端口号是否正确（465 → SSL，587 → STARTTLS）'
    # 认证失败 535 / 454
    if '535' in msg or '454' in msg or 'Authentication' in msg or 'credentials' in msg_lower or 'username and password' in msg_lower:
        return '认证失败，请检查账号和授权码（QQ/163/126 邮箱需在网页版开启 SMTP 后使用授权码，而非登录密码）'
    # SSL/TLS 握手失败
    if 'SSL' in msg or 'ssl' in msg or 'WRONG_VERSION' in msg or 'TLSV1' in msg or 'handshake' in msg_lower:
        return 'SSL/TLS 握手失败，请检查加密方式与端口是否匹配（465 选 SSL，587 选 STARTTLS）'
    # 服务器意外断开 —— SMTPServerDisconnected / Connection unexpectedly closed
    if isinstance(e, smtplib.SMTPServerDisconnected) or 'unexpectedly closed' in msg_lower or 'disconnected' in msg_lower or 'EOF' in msg:
        return ('服务器意外断开连接。常见原因：\n'
                '① QQ/163/126 邮箱未在网页版「设置 → 账户」中开启 SMTP 服务\n'
                '② 端口或加密方式不匹配（QQ → 465/SSL，Gmail → 587/STARTTLS）\n'
                '③ IP 被临时限速，稍后再试')
    # 发件被拒 550/553
    if '550' in msg or '553' in msg:
        return f'发件被服务器拒绝（{msg[:120]}），请检查发件地址是否与账号一致'
    return msg


def test_smtp_connection(config_dict: dict) -> dict:
    """测试 SMTP 连接，返回 {ok: bool, message: str}"""
    class _FakeCfg:
        pass
    cfg = _FakeCfg()
    cfg.smtp_host = config_dict.get('smtp_host', '').strip()
    cfg.smtp_port = int(config_dict.get('smtp_port', 465))
    cfg.smtp_ssl = bool(config_dict.get('smtp_ssl', True))
    cfg.smtp_starttls = bool(config_dict.get('smtp_starttls', False))
    cfg.username = config_dict.get('username', '')
    _raw_pwd = config_dict.get('password', '')
    if _raw_pwd == '********':
        try:
            from ..config.settings import get_config
            _raw_pwd = get_config().notification_email.password
        except Exception:
            _raw_pwd = ''
    cfg.password = _raw_pwd
    cfg.from_email = config_dict.get('from_email', '') or config_dict.get('username', '')
    cfg.from_name = config_dict.get('from_name', 'Prekikoeru')
    cfg.to_email = config_dict.get('to_email', '')
    cfg.connect_timeout_seconds = int(config_dict.get('connect_timeout_seconds', 10))
    cfg.send_timeout_seconds = int(config_dict.get('send_timeout_seconds', 30))

    if not cfg.smtp_host:
        return {'ok': False, 'message': 'SMTP 主机未配置'}
    # 检测常见填错：把邮箱地址填到主机栏
    if '@' in cfg.smtp_host:
        domain = cfg.smtp_host.split('@')[-1]
        suggestion = f'smtp.{domain}'
        return {'ok': False, 'message': f'SMTP 主机不应填邮箱地址，请填服务器地址，例如 {suggestion}'}
    if not cfg.to_email:
        return {'ok': False, 'message': '收件地址未配置'}

    try:
        _send_smtp_sync(cfg, '测试邮件 - Prekikoeru 通知中心', '<p>SMTP 配置测试成功，Prekikoeru 通知中心已就绪。</p>', 'SMTP 配置测试成功。')
        return {'ok': True, 'message': '发送成功，请检查收件箱'}
    except Exception as e:
        return {'ok': False, 'message': _friendly_smtp_error(e)}
