/**
 * 默认邮件模板（HTML 模式）
 *
 * 设计灵感：Vercel / Linear / Stripe 等海外 SaaS 通知邮件
 * - 600px 居中容器，白底 + 极淡灰背景
 * - 顶部 logo / 品牌名 + 极简标题
 * - 主体卡片：状态徽章 + 标题 + 摘要 + 关键字段 grid
 * - 底部签名 + 取消订阅链接（占位）
 * - 全 inline style，兼容主流邮件客户端
 */

export const DEFAULT_EMAIL_HTML = `<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f6f7f9;padding:32px 0;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border:1px solid #ececef;border-radius:14px;overflow:hidden;">

<!-- 品牌头 -->
<tr><td style="padding:28px 36px 0 36px;">
<table width="100%" cellpadding="0" cellspacing="0" border="0">
<tr>
<td style="font-size:13px;font-weight:600;color:#1d1d1f;letter-spacing:0.02em;">
<span style="display:inline-block;width:10px;height:10px;background:#1d1d1f;border-radius:3px;vertical-align:middle;margin-right:8px;"></span>
Prekikoeru
</td>
<td align="right" style="font-size:11px;color:#8e8e93;letter-spacing:0.04em;">{时间}</td>
</tr>
</table>
</td></tr>

<!-- 状态徽章 -->
<tr><td style="padding:24px 36px 0 36px;">
<span style="display:inline-block;font-size:11px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#1f8f4e;background:#e8f5ee;border:1px solid #bce0c9;padding:3px 10px;border-radius:99px;">
{事件图标} {事件名称}
</span>
</td></tr>

<!-- 标题 -->
<tr><td style="padding:14px 36px 0 36px;">
<h1 style="font-size:22px;font-weight:600;color:#1d1d1f;line-height:1.35;margin:0;letter-spacing:-0.01em;">
{任务标题}
</h1>
</td></tr>

<!-- 摘要 -->
<tr><td style="padding:10px 36px 0 36px;">
<p style="font-size:14px;color:#48484a;line-height:1.6;margin:0;">
{摘要}
</p>
</td></tr>

<!-- 关键字段卡 -->
<tr><td style="padding:24px 36px 0 36px;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fafafa;border:1px solid #ececef;border-radius:10px;">
<tr>
<td style="padding:14px 18px;border-right:1px solid #ececef;">
<div style="font-size:10px;font-weight:600;color:#8e8e93;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">分类</div>
<div style="font-size:13px;color:#1d1d1f;font-weight:500;">{任务类型}</div>
</td>
<td style="padding:14px 18px;border-right:1px solid #ececef;">
<div style="font-size:10px;font-weight:600;color:#8e8e93;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">RJ 号</div>
<div style="font-size:13px;color:#1d1d1f;font-weight:500;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{RJ号}</div>
</td>
<td style="padding:14px 18px;">
<div style="font-size:10px;font-weight:600;color:#8e8e93;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">耗时</div>
<div style="font-size:13px;color:#1d1d1f;font-weight:500;">{时间}</div>
</td>
</tr>
</table>
</td></tr>

<!-- 分隔 -->
<tr><td style="padding:28px 36px 0 36px;">
<div style="height:1px;background:#ececef;"></div>
</td></tr>

<!-- 签名说明 -->
<tr><td style="padding:18px 36px 28px 36px;">
<p style="font-size:12px;color:#8e8e93;line-height:1.6;margin:0;">
此邮件由 <strong style="color:#48484a;font-weight:500;">Prekikoeru</strong> 自动生成。任务详情可在桌面端"任务中心"查看。
</p>
</td></tr>

</table>

<!-- 底部 footer -->
<table width="560" cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">
<tr><td align="center" style="font-size:10px;color:#a1a1a6;letter-spacing:0.04em;line-height:1.7;">
Prekikoeru · 本地部署 · 请勿回复
</td></tr>
</table>

</td></tr>
</table>`

/**
 * 默认主题模板
 */
export const DEFAULT_SUBJECT = '[Prekikoeru] {任务类型}{事件名称} · {任务标题}'
