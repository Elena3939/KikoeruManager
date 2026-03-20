# 本地开发说明

## 1. 环境要求

- Python 3.11+
- Node.js 18+
- npm
- 7-Zip

## 2. 依赖位置

- 后端依赖：[backend/requirements.txt](D:/Clash%20Verge/KikoeruTool_Elena/backend/requirements.txt)
- 测试依赖：[backend/requirements-test.txt](D:/Clash%20Verge/KikoeruTool_Elena/backend/requirements-test.txt)
- 前端依赖：[frontend/package.json](D:/Clash%20Verge/KikoeruTool_Elena/frontend/package.json)

## 3. 一键启动脚本

开发环境推荐直接使用项目已有脚本：

- [start-dev.bat](D:/Clash%20Verge/KikoeruTool_Elena/start-dev.bat)
- [start-dev.ps1](D:/Clash%20Verge/KikoeruTool_Elena/start-dev.ps1)
- [start-dev.sh](D:/Clash%20Verge/KikoeruTool_Elena/start-dev.sh)

脚本会处理：

- Python/Node.js 检查
- 后端虚拟环境创建
- 依赖修复
- 前端依赖安装
- 前后端启动

## 4. 手动启动

### 后端

```bash
cd backend
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m app.main
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 5. 默认访问地址

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

## 6. 配置文件在开发环境中的使用方式

当前仓库需要你明确区分：

- 示例配置：[backend/config/config.yaml](D:/Clash%20Verge/KikoeruTool_Elena/backend/config/config.yaml)
- 运行时配置：由 `CONFIG_PATH` 或默认路径决定

建议做法：

### 方式一：显式指定

在启动前设置：

```bat
set CONFIG_PATH=D:\Clash Verge\KikoeruTool_Elena\backend\config\config.yaml
```

或 PowerShell：

```powershell
$env:CONFIG_PATH="D:\Clash Verge\KikoeruTool_Elena\backend\config\config.yaml"
```

### 方式二：复制示例到实际运行位置

如果你不想依赖环境变量，就把示例配置复制到运行时默认位置再启动。

## 7. 调试建议

### 后端

- 直接使用 `python -m app.main`
- API 文档可用于快速验证接口
- 主要日志文件在 `data/app.log`

### 前端

- 使用 Vite 开发服务器
- 直接打开浏览器开发者工具查看接口请求与页面状态

## 8. 开发注意事项

- 修改配置模型后要同步更新前端设置页
- 修改路由后要同步更新菜单与文档
- 不要把真实账号、Token 和私有地址提交到配置文件
- 如果要验证打包行为，不要只在 Vite 模式下测试

## 9. 运行中常见问题

### 8000 或 5173 被占用

结束旧进程后再重启。

### `7z` 不可用

检查系统是否安装 7-Zip，并确认路径可执行。

### 前端能打开但接口报错

优先检查后端是否启动、配置路径是否正确、日志里是否有配置解析失败信息。
