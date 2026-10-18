# Windows 安装包试用版

支持 Windows 10/11 x64。安装用户无需安装 Python、Node.js、PostgreSQL、Redis 或 PowerShell 7。
当前 PostgreSQL Windows 二进制在中文程序路径下初始化失败，因此程序安装目录限制为 ASCII 路径；数据目录可使用中文。
应用通过系统托盘运行，启动后打开浏览器；关闭浏览器不会退出应用。

## 本机构建

构建机需要项目 Python 虚拟环境、Node.js、7-Zip、Inno Setup 6.7.3。
PostgreSQL 使用已验证的 18.4 二进制目录，只收集 bin/lib/share 和许可证，绝不打包数据库数据。
提前准备 tools/unar、tools/aria2、tools/baidupcs-go；目录必须包含完整依赖和许可证。

```pwsh
./scripts/build-windows-installer.ps1
```

输出位于 output/windows，默认读取当前代码最近的标准版本 tag，不创建发布标签。
安装器标题、文件名及应用内版本使用同一版本；App / 安装器 / 托盘图标从网页标签页 webIcon.png 生成，向导插图使用 Inno 默认素材。
正式版本指定 X.Y.Z，与标准 vX.Y.Z 标签对应。
SHA256SUMS.txt 用于校验下载的安装包，runtime-manifest.json 记录随包运行时文件摘要。

## 数据与退出

程序默认安装到当前用户 LocalAppData/Programs/KikoeruManager。
安装向导可单独选择数据目录，默认 LocalAppData/KikoeruManager。
数据库、配置、缓存、日志和默认库存目录均位于所选目录。
关闭托盘程序后，可将整个数据目录移动到新位置，再修改安装目录下的
data-location.txt 为新目录的完整路径。必须整体迁移，不能只移动数据库文件。
业务配置可在应用设置页修改，也可关闭程序后编辑数据目录下的 config/config.yaml。
首次启动生成独立数据库和随机密码，不复制仓库配置，不连接系统已有数据库。
此行为仅适用于选中内置组件时。
安装向导分别提供 PostgreSQL / Redis 的“使用安装包内置服务”和“连接本机已有服务”单选页。
随包文件只解压所选内置组件，不进行网络下载；选择已有服务时会跳过对应内置组件。
首次启动会要求填写已有服务连接，保存至数据目录 config/config.yaml；之后可编辑配置。
PostgreSQL 必须已有专用数据库，连接账号需要建表权限和 pg_trgm 扩展权限。
只有 psql 客户端不等于已安装数据库服务；无法仅凭检测到客户端就自动取消服务组件。
使用已有服务时，应用不负责启动、停止或删除该服务。
重新运行安装器并取消内置组件会清理安装目录 runtime/postgresql 或 runtime/redis，保留数据目录。
安装目录 runtime-options.ini 的 postgresql / redis 可设为 embedded 或 external；
切回 embedded 前需重新运行安装器安装对应组件，不会自动迁移数据库内容。
通过托盘的“退出应用”关闭后端、Redis 和 PostgreSQL。
升级与卸载默认保留用户数据；卸载前先从托盘退出应用。

## 试用版验证边界

本机已验证全新数据目录初始化 PostgreSQL、pg_trgm、Redis，二次启动保留凭据；
并验证桌面入口的健康接口、前端首页及正常关闭数据库。
已验证两项均使用已有服务、仅 PostgreSQL 内置、仅 Redis 内置三种组合，
以及打包程序连接已有服务后加载首页、退出且保持已有服务存活。
实际安装器已验证取消组件后清理内置程序目录。
随包解压与下载工具已执行版本检查。构建产物不包含本机配置或数据库。

发布前必须在干净 Windows 虚拟机验证安装、首次启动、业务操作、升级与卸载。
当前未配置代码签名，不能宣称已通过 SmartScreen 信誉验证。
Redis 使用 redis-windows 提供的非官方 Windows 构建，版本固定并校验 SHA-256。
不得把 .runtime、output、data 中的本地数据提交到仓库。
