# 通知邮件渲染与预览

发送入口为 `notification_template_service.render_email_for_outbox`。积木模板使用 `render_blocks_email`，HTML 模板使用 `_render_user_template`。模板预览接口支持传入当前草稿，不保存、不发信，按相同模式选择渲染器；只传模板 ID 时读取已保存模板。

文件清单及作品统计的图标使用文本/emoji，避免邮件客户端对内联 SVG 的截断和路径移除。嵌套目录只由子容器产生缩进；长文件名按单元格换行，避免撑宽邮件。过滤状态仍保留删除线。

积木编辑器的邮件纸固定白底，工具栏和属性面板遵循工作台主题。全局暗色规则不再覆盖邮件纸及其内部表格。全屏预览显式占据视口高度，iframe 在剩余内容区滚动。

预览监听积木、事件、主题和任务域变化；响应序号防止旧请求覆盖新状态，关闭时清理防抖任务，错误直接显示。

启动时仅在默认模板不存在时创建，保留已保存模板的积木、HTML、启用状态和适用范围。

独立回归：在仓库根目录设置 `PYTHONPATH=backend` 后运行 `python -m unittest discover -s backend/tests -p test_notification_template_rendering.py`。该用例不连接数据库或发送邮件。
