# YAAS 浏览器下载

点击爬取字幕时在访问者当前浏览器预开弹窗。后端遇到 POW 验证只记录等待状态及资源路径，不启动浏览器；前端刷新验证地址后让原弹窗跳转，由用户人工验证并通过浏览器下载。

- Windows 和 Linux / Docker 使用相同流程，不依赖 Playwright、Chromium、桌面环境或 CDP。
- 后端仅保留 `/api/browser-verification/task/{task_id}/open` 和 `/handoff`，分别用于刷新并校验公网 HTTPS 下载地址、清理对应等待任务。
- 发起浏览器跳转后清理系统等待项，不代表验证、下载或入库成功。浏览器下载失败不会自动恢复已清理任务。
- 弹窗被拦截、地址获取失败或用户在加载中关闭窗口时保留任务。
- 文件保存在访问设备的浏览器下载目录，不落在服务器库存，不自动解压、配对或入库。
- HTTP 配置中的 Cloudflare Turnstile 代理选项沿用 `imoutoheaven` 键，仅作用于服务端请求；浏览器使用自身网络。
- 本地验收脚本 `tools/check-yaas-current-browser.mjs` 使用开发目录的 Playwright 测试浏览器，不是产品运行依赖。
- `tools/check-circle-browser-download.mjs --real` 会通过真实社团页创建 RJ01168542 任务。测试夹具的成功不能代表真实源站人工验证成功。

移除容器浏览器依赖后需重新构建完整镜像才能从生产镜像层中实际移除 Chromium 及其依赖；仅热更新 Python 文件不会缩小旧镜像。
