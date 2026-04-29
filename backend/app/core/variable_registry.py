"""变量注册表：定义 Block 系统可使用的变量键及其 payload 路径、示例值。

变量 key 全部中文化（"任务标题"、"摘要"...），便于业务用户理解；
同时通过 ALIAS 表保留旧英文 key（"title"、"summary"...）兼容，
让历史模板继续工作。
"""
import html as _html
import re

VARIABLE_REGISTRY = {
    "任务标题": {"path": "title", "label": "任务标题", "example": "示例任务标题"},
    "摘要": {"path": "summary", "label": "摘要", "example": "批量任务结束，3/3 个完成"},
    "任务类型": {"path": "domain_label", "label": "任务类型", "example": "导入处理"},
    "RJ号": {"path": "rjcode", "label": "RJ 号", "example": "RJ123456"},
    "事件名称": {"path": "event_label", "label": "事件名称", "example": "任务完成"},
    "事件图标": {"path": "event_icon", "label": "事件图标", "example": "✅"},
    "时间": {"path": "created_at_text", "label": "时间", "example": "2024-01-01 12:00:00"},
    "严重程度": {"path": "severity", "label": "严重程度", "example": "success"},
    "总文件数": {"path": "stats.total_files", "label": "总文件数", "example": "10"},
    "总大小": {"path": "stats.total_size", "label": "总大小", "example": "256 MB"},
    "业务数据块": {"path": "payload_sections", "label": "业务数据块", "example": "自动渲染统计 / 文件树 / 日志"},
    "统计网格": {"path": "stats_grid_section", "label": "统计网格", "example": "自动渲染统计网格"},
    "文件树": {"path": "file_tree_section", "label": "文件树", "example": "自动渲染文件清单"},
    "差异对比": {"path": "diff_section", "label": "差异对比", "example": "自动渲染差异列表"},
    "执行日志": {"path": "task_log_section", "label": "执行日志", "example": "自动渲染执行日志"},
}

VARIABLE_ALIASES = {
    "title": "任务标题",
    "summary": "摘要",
    "domain_label": "任务类型",
    "rjcode": "RJ号",
    "event_label": "事件名称",
    "event_icon": "事件图标",
    "created_at": "时间",
    "severity": "严重程度",
    "stats.total_files": "总文件数",
    "stats.total_size": "总大小",
    "payload_sections": "业务数据块",
    "stats_grid_section": "统计网格",
    "file_tree_section": "文件树",
    "diff_section": "差异对比",
    "task_log_section": "执行日志",
}


def _normalize_key(key: str) -> str:
    """把英文别名规范化为中文 key；中文 key 原样返回。"""
    return VARIABLE_ALIASES.get(key, key)


def resolve_variable(key: str, payload: dict, fallback: str = "") -> str:
    """从 payload 中按点号路径解析变量，结果已 HTML escape。

    支持中文 key（推荐）和英文别名（兼容），二者都会先经 VARIABLE_REGISTRY
    走 path 字段，找到 payload 中真实路径后取值。
    """
    canonical = _normalize_key(key)
    actual_path = canonical
    meta = VARIABLE_REGISTRY.get(canonical)
    if meta and meta.get("path"):
        actual_path = meta["path"]

    parts = actual_path.split(".")
    value = payload
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
        if value is None:
            return _html.escape(fallback)
    if value is None:
        return _html.escape(fallback)
    return _html.escape(str(value))


_VAR_PLACEHOLDER_RE = re.compile(r"\{([^{}\s]+)\}")


def substitute_variables(text: str, payload: dict, *, escape: bool = True) -> str:
    """把字符串里的 {var} 占位符替换为 payload 中对应值。

    - escape=True: 替换值会被 HTML escape，适用于会被当 HTML 渲染的场景（富文本块）。
    - escape=False: 不 escape，适用于已知会被作为纯文本展示的字段（邮件主题）。

    支持中文 key（{任务标题}）和英文别名（{title}）。未注册的变量保留原文。
    """
    if not text:
        return ""

    def _repl(match):
        key = match.group(1)
        canonical = _normalize_key(key)
        actual_path = canonical
        meta = VARIABLE_REGISTRY.get(canonical)
        if meta and meta.get("path"):
            actual_path = meta["path"]

        parts = actual_path.split(".")
        value = payload
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
            if value is None:
                return match.group(0)
        if value is None:
            return match.group(0)
        text_value = str(value)
        return _html.escape(text_value) if escape else text_value

    return _VAR_PLACEHOLDER_RE.sub(_repl, text)


def build_sample_payload(event_type: str = "completed", domain: str = "import") -> dict:
    """构建用于预览的示例 Payload。"""
    _EVENT_LABELS = {"completed": "任务完成", "failed": "任务失败", "waiting_manual": "等待人工处理"}
    _EVENT_ICONS = {"completed": "✅", "failed": "❌", "waiting_manual": "⚠️"}
    _SEVERITY_MAP = {"completed": "success", "failed": "danger", "waiting_manual": "warning"}
    return {
        "event_type": event_type,
        "title": "示例任务标题",
        "summary": "批量任务结束，3/3 个完成",
        "domain_label": "导入处理",
        "rjcode": "RJ123456",
        "event_label": _EVENT_LABELS.get(event_type, event_type),
        "event_icon": _EVENT_ICONS.get(event_type, ""),
        "created_at_text": "2024-01-01 12:00:00",
        "severity": _SEVERITY_MAP.get(event_type, "info"),
        "stats": {
            "total_files": "3",
            "total_size": "256 MB",
            "duration": "12.4s",
            "succeeded": "3",
            "failed": "0",
        },
        "file_tree": [
            {
                "name": "RJ123456",
                "status": "kept",
                "children": [
                    {
                        "name": "audio",
                        "status": "kept",
                        "children": [
                            {"path": "track01.flac", "size_text": "42.1 MB", "status": "kept", "badges": ["已上传"]},
                            {"path": "track02.flac", "size_text": "38.6 MB", "status": "kept", "badges": ["已上传"]},
                            {"path": "sample.mp3", "size_text": "3.4 MB", "status": "filtered"},
                        ],
                    },
                    {"path": "cover.jpg", "size_text": "1.2 MB", "status": "kept", "badges": ["已上传"]},
                    {"path": "readme.txt", "size_text": "256 B", "status": "filtered"},
                ],
            }
        ],
        "download_files": [
            {
                "name": "RJ123456",
                "status": "kept",
                "children": [
                    {
                        "name": "WAV",
                        "status": "kept",
                        "children": [
                            {
                                "name": "効果音あり_WAV",
                                "status": "kept",
                                "children": [
                                    {"path": "Track01_A.wav", "size_text": "107.2 MB", "status": "kept", "badges": ["已上传"]},
                                    {"path": "Track02_A.wav", "size_text": "87.8 MB", "status": "kept", "badges": ["已上传"]},
                                ],
                            }
                        ],
                    },
                    {"path": "cover.jpg", "size_text": "1.42 MB", "status": "kept", "badges": ["已上传"]},
                    {"path": "preview.png", "size_text": "1.47 MB", "status": "kept", "badges": ["已上传"]},
                ],
            }
        ],
        "download_work_cards": [
            {
                "rjcode": "RJ123456",
                "title": "【早期購入特典付き】ひたすら“ぎゅー”してお互い「好き好き」と言わなきゃいけない、あまあまクール大好きペア",
                "circle_name": "防講潤滑剤",
                "cover_url": "https://img.dlsite.jp/modpub/images2/work/doujin/RJ123000/RJ123456_img_main.jpg",
                "size_text": "1.32 GB",
                "file_count": 7,
            }
        ],
        "diff_items": [
            {"label": "社团名", "old": "Tsuki", "new": "Tsuki Studio"},
            {"label": "封面", "old": "", "new": "cover_v2.jpg"},
            {"label": "RJ 编号", "old": "RJ123456", "new": "RJ123456"},
            {"label": "标签", "old": "ASMR", "new": "ASMR / 治愈"},
        ],
        "recent_logs": [
            {"ts": "12:00:01", "level": "info", "text": "开始处理任务 RJ123456"},
            {"ts": "12:00:03", "level": "info", "text": "下载封面：cover.jpg (1.2 MB)"},
            {"ts": "12:00:05", "level": "warn", "text": "检测到重复文件 sample.mp3，已过滤"},
            {"ts": "12:00:08", "level": "info", "text": "解压完成，共 3 个有效文件"},
            {"ts": "12:00:12", "level": "info", "text": "任务完成，耗时 12.4s"},
        ],
        "domain": domain,
    }
