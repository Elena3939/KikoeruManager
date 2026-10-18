"""首次使用已有服务时收集连接信息；保存后由运行时实际校验连接。"""
from urllib.parse import urlsplit


def configure_external_services(config, state, embedded_pg, embedded_redis):
    database = config.get('database', {})
    cache = config.get('redis', {})
    own_pg = (database.get('password') == state.get('pg_password')
              and database.get('username') == 'kikoerumanager')
    own_redis = state.get('redis_password', '') in cache.get('url', '')
    need_pg = not embedded_pg and (own_pg or not all(database.get(k) for k in ('host', 'database', 'username')))
    need_redis = not embedded_redis and (own_redis or not cache.get('url'))
    if not need_pg and not need_redis:
        return

    import tkinter as tk
    from tkinter import ttk, messagebox

    window = tk.Tk()
    window.title('KikoeruManager · 连接已有服务')
    window.resizable(False, False)
    panel = ttk.Frame(window, padding=24)
    panel.grid()
    ttk.Label(panel, text='已取消内置组件，请填写已有服务连接。\nPostgreSQL 请使用专用数据库，账号需有建表及 pg_trgm 扩展权限。',
              justify='left').grid(row=0, column=0, columnspan=2, pady=(0, 16))
    fields = {}
    definitions = []
    if need_pg:
        definitions += [('host', 'PostgreSQL 地址', '127.0.0.1'), ('port', '端口', '5432'),
                        ('database', '数据库名', 'kikoerumanager'), ('username', '用户名', ''),
                        ('password', '密码', ''), ('sslmode', 'SSL 模式', 'prefer')]
    if need_redis:
        definitions += [('url', 'Redis 连接 URL', 'redis://127.0.0.1:6379/0')]
    for row, (key, label, default) in enumerate(definitions, start=1):
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky='w', pady=5)
        value = tk.StringVar(value=default)
        fields[key] = value
        ttk.Entry(panel, textvariable=value, width=46, show='*' if key in ('password', 'url') else '').grid(
            row=row, column=1, padx=(12, 0), pady=5)
    accepted = False

    def save():
        nonlocal accepted
        values = {key: field.get() if key == 'password' else field.get().strip() for key, field in fields.items()}
        try:
            if need_pg:
                if not all(values[k] for k in ('host', 'database', 'username')):
                    raise ValueError('数据库地址、数据库名和用户名不能为空。')
                values['port'] = int(values['port'])
                if not 1 <= values['port'] <= 65535:
                    raise ValueError('端口范围为 1–65535。')
                if values['sslmode'] not in ('disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'):
                    raise ValueError('SSL 模式无效。')
            if need_redis:
                parsed = urlsplit(values['url'])
                if parsed.scheme not in ('redis', 'rediss') or not parsed.hostname:
                    raise ValueError('Redis URL 格式应为 redis://:密码@地址:端口/0。')
            if need_pg:
                config['database'] = {k: values[k] for k in ('host', 'port', 'database', 'username', 'password', 'sslmode')}
            if need_redis:
                config['redis'] = {'enabled': True, 'required': True, 'environment': 'desktop', 'url': values['url']}
        except ValueError as exc:
            messagebox.showerror('连接配置有误', str(exc), parent=window)
            return
        accepted = True
        window.destroy()

    ttk.Button(panel, text='保存并连接', command=save).grid(row=len(definitions) + 1, column=1, sticky='e', pady=(16, 0))
    window.mainloop()
    if not accepted:
        raise RuntimeError('已取消已有服务配置，未启动应用。')
