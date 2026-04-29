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

// ─── 积木版默认模板：把上面那段 HTML 拆成多个独立、可单独编辑的块 ───────
//
// 设计原则：
//   1. 每个 rich_text 块只放一段紧凑、自包含的 HTML，不嵌套邮件外壳，
//      避免在画布里出现「邮件壳套邮件壳」的歪扭叠层。
//   2. 业务数据用 typed block（stats_grid / file_tree / task_log），
//      由后端按 payload 自动渲染；没数据时退回简洁占位。
//   3. 用户可单独删 / 隐藏 / 复制每一块，比单一巨型 rich_text 友好得多。
function _uid(prefix) {
  return `blk_${prefix}_` + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
}

export function buildDefaultEmailBlocks() {
  return [
    {
      id: _uid('header_image'),
      type: 'rich_text',
      enabled: true,
      schemaVersion: 1,
      props: {
        contentJson: null,
        htmlCache: `<p style="margin:0;"><img src="${EMAIL_HEADER_URL}" alt="Prekikoeru Mail" style="display:block;width:100%;max-width:100%;height:auto;border:0;border-radius:12px;outline:none;text-decoration:none;"></p>`,
      },
    },
    {
      id: _uid('event_meta'),
      type: 'rich_text',
      enabled: true,
      schemaVersion: 1,
      props: {
        contentJson: null,
        htmlCache: `<p style="margin:18px 0 0 0;text-align:center;font-size:13px;line-height:1.5;color:#7b4fb4;font-weight:700;">{事件图标} {事件名称} · {时间}</p>`,
      },
    },
    {
      id: _uid('title_summary'),
      type: 'rich_text',
      enabled: true,
      schemaVersion: 1,
      props: {
        contentJson: null,
        htmlCache: `<h1 style="margin:8px 0 0 0;text-align:center;font-size:24px;line-height:1.34;font-weight:700;color:#16181d;">{任务标题}</h1>
<p style="margin:12px auto 0 auto;max-width:480px;text-align:center;font-size:14px;line-height:1.75;color:#5d6470;">{摘要}</p>`,
      },
    },
    {
      id: _uid('info_grid'),
      type: 'rich_text',
      enabled: true,
      schemaVersion: 1,
      props: {
        contentJson: null,
        htmlCache: `<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 0 0;border:1px solid #eceef3;border-radius:14px;border-collapse:separate;overflow:hidden;background:#ffffff;">
<tr>
  <td style="padding:14px 16px;border-bottom:1px solid #eceef3;">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#9aa1ac;margin-bottom:4px;">任务类型</div>
    <div style="font-size:14px;font-weight:650;color:#1f2329;">{任务类型}</div>
  </td>
  <td style="padding:14px 16px;border-bottom:1px solid #eceef3;border-left:1px solid #eceef3;">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#9aa1ac;margin-bottom:4px;">摘要</div>
    <div style="font-size:14px;font-weight:650;color:#1f2329;line-height:1.55;">{摘要}</div>
  </td>
</tr>
<tr>
  <td colspan="2" style="padding:14px 16px;">
    <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#9aa1ac;margin-bottom:4px;">状态</div>
    <div style="font-size:14px;font-weight:650;color:#1f2329;">{事件图标} {事件名称}</div>
  </td>
</tr>
</table>`,
      },
    },
    {
      id: _uid('stats'),
      type: 'stats_grid',
      enabled: true,
      schemaVersion: 1,
      props: {
        columns: 3,
        items: [
          { key: 'total_files', label: '总文件数', icon: '' },
          { key: 'total_size',  label: '总大小',   icon: '' },
          { key: 'duration',    label: '耗时',     icon: '' },
        ],
      },
    },
    {
      id: _uid('files'),
      type: 'file_tree',
      enabled: true,
      schemaVersion: 1,
      props: { title: '文件清单', sourceKey: 'file_tree', maxItems: 12 },
    },
    {
      id: _uid('logs'),
      type: 'task_log',
      enabled: true,
      schemaVersion: 1,
      props: { title: '执行日志', sourceKey: 'recent_logs', maxLines: 8 },
    },
    {
      id: _uid('hr'),
      type: 'divider',
      enabled: true,
      schemaVersion: 1,
      props: { color: '#eceef3', margin: 18 },
    },
    {
      id: _uid('footer'),
      type: 'rich_text',
      enabled: true,
      schemaVersion: 1,
      props: {
        contentJson: null,
        htmlCache: `<p style="margin:0;text-align:center;font-size:12px;line-height:1.7;color:#8a9099;">此邮件由 <strong style="color:#4f5661;font-weight:650;">Prekikoeru</strong> 自动生成。任务详情可在桌面端任务中心查看。</p>`,
      },
    },
  ]
}
