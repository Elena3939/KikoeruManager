const EMAIL_HEADER_URL = 'https://im.gurl.eu.org/file/AgACAgEAAxkDAAEBgcVp8OfJBO4AAUxLd8WPdMwRLA8TX28AAnsMaxuveYhHvw-4JedMJTcBAAMCAAN3AAM7BA.png'

export const DEFAULT_EMAIL_HTML = `<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f8fa;padding:34px 0;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" border="0" style="width:620px;max-width:calc(100% - 32px);background:#ffffff;border:1px solid #e9eaee;border-radius:18px;border-collapse:separate;overflow:hidden;box-shadow:0 18px 48px rgba(20,24,31,0.08);">

<tr>
<td style="padding:0;background:#ffffff;">
  <img src="${EMAIL_HEADER_URL}" alt="Prekikoeru Mail" width="620" style="display:block;width:100%;max-width:620px;height:auto;border:0;outline:none;text-decoration:none;">
</td>
</tr>

<tr>
<td style="padding:24px 34px 0 34px;background:#ffffff;text-align:center;">
  <div style="margin:0 0 13px 0;font-size:13px;line-height:1.5;color:#7b4fb4;font-weight:800;">{事件图标} {事件名称} · {时间}</div>
  <h1 style="margin:0;font-size:24px;line-height:1.34;font-weight:700;color:#16181d;letter-spacing:0;">{任务标题}</h1>
  <p style="margin:12px auto 0 auto;max-width:480px;font-size:14px;line-height:1.75;color:#5d6470;">{摘要}</p>
</td>
</tr>

<tr>
<td style="padding:28px 34px 0 34px;background:#ffffff;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #eceef3;border-radius:14px;border-collapse:separate;overflow:hidden;background:#ffffff;">
    <tr>
      <td style="padding:16px 18px;border-bottom:1px solid #eceef3;">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#9aa1ac;margin-bottom:5px;">任务类型</div>
        <div style="font-size:14px;font-weight:650;color:#1f2329;">{任务类型}</div>
      </td>
      <td style="padding:16px 18px;border-bottom:1px solid #eceef3;border-left:1px solid #eceef3;">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#9aa1ac;margin-bottom:5px;">摘要</div>
        <div style="font-size:14px;font-weight:650;color:#1f2329;line-height:1.55;">{摘要}</div>
      </td>
    </tr>
    <tr>
      <td colspan="2" style="padding:16px 18px;">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#9aa1ac;margin-bottom:5px;">状态</div>
        <div style="font-size:14px;font-weight:650;color:#1f2329;">{事件图标} {事件名称}</div>
      </td>
    </tr>
  </table>
</td>
</tr>

<tr>
<td style="padding:18px 34px 0 34px;background:#ffffff;">
  {业务数据块}
</td>
</tr>

<tr>
<td style="padding:28px 34px 32px 34px;background:#ffffff;">
  <div style="height:1px;background:#eceef3;margin-bottom:16px;"></div>
  <p style="margin:0;text-align:center;font-size:12px;line-height:1.7;color:#8a9099;">此邮件由 <strong style="color:#4f5661;font-weight:650;">Prekikoeru</strong> 自动生成。任务详情可在桌面端任务中心查看。</p>
</td>
</tr>

</table>
</td></tr>
</table>`

export const DEFAULT_SUBJECT = '[Prekikoeru] {任务类型}{事件名称} · {任务标题}'
