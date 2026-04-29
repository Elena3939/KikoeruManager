"""邮件安全 HTML 清洗器。

优先使用 nh3（Rust 加速），不可用时回退到基于 re 的白名单过滤。
目标：输出 email-safe HTML（允许 table/inline-style/基础文本，禁止 script/iframe 等）。
"""
import re

_ALLOWED_TAGS = frozenset({
    "p", "br", "b", "strong", "i", "em", "u", "s", "del",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "a", "span", "div",
    "table", "thead", "tbody", "tr", "th", "td",
    "img",
    "hr", "blockquote", "pre", "code",
    "details", "summary",
})

_ALLOWED_ATTRS = frozenset({
    "style", "href", "target", "rel", "class", "align", "valign",
    "colspan", "rowspan", "width", "height", "bgcolor",
    "border", "cellpadding", "cellspacing",
    "src", "alt", "open",
    # 变量 pill 标记：富文本里的变量节点用 data-var 存储变量 key，
    # 后端在 substitute 前会还原为 {key}
    "data-var",
})

_DANGEROUS_BLOCK_RE = re.compile(
    r'<\s*(script|iframe|object|embed|form|input|textarea|select|button|link|meta|base|svg|math)\b'
    r'[^>]*>.*?<\s*/\s*\1\s*>',
    re.IGNORECASE | re.DOTALL,
)
_DANGEROUS_SELF_RE = re.compile(
    r'<\s*(script|iframe|object|embed|form|input|link|meta|base)\b[^>]*/?>',
    re.IGNORECASE,
)
_EVENT_ATTR_RE = re.compile(r'\s+on\w+\s*=\s*(?:["\'][^"\']*["\']|\S+)', re.IGNORECASE)
_JAVASCRIPT_HREF_RE = re.compile(r'(href\s*=\s*["\'])javascript:[^"\']*(["\'])', re.IGNORECASE)


def sanitize_html(html_content: str) -> str:
    """清洗 HTML，移除危险标签与属性，输出 email-safe 内容。"""
    if not html_content:
        return ""
    try:
        import nh3
        return nh3.clean(
            html_content,
            tags=_ALLOWED_TAGS,
            attributes={tag: _ALLOWED_ATTRS for tag in _ALLOWED_TAGS},
            link_rel=None,
        )
    except ImportError:
        pass
    result = _DANGEROUS_BLOCK_RE.sub("", html_content)
    result = _DANGEROUS_SELF_RE.sub("", result)
    result = _EVENT_ATTR_RE.sub("", result)
    result = _JAVASCRIPT_HREF_RE.sub(r'\1#\2', result)
    return result
