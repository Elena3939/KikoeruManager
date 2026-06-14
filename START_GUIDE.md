# KikoeruManager 快速启动指南

## 安装（首次使用）

双击运行 `setup.bat`，自动安装所有依赖。
脚本会检查本机 PostgreSQL；如果没有可用环境，会通过 `scripts\install-postgresql.ps1` 安装 / 初始化 PostgreSQL，并把随机生成的数据库密码写入 `data\config\config.yaml`。

## 日常启动

### 方式1：一键启动（推荐）
双击 `start-all.bat`
- 自动启动前后端服务
- 自动检查并启动本机 PostgreSQL
- 打开两个命令行窗口
- 关闭窗口即可停止服务

### 方式2：单独启动
- **只启动后端**: 双击 `backend\start.bat`
- **只启动前端**: 双击 `frontend\start.bat`

## 访问地址

- **前端界面**: http://localhost:5556
- **后端API**: http://localhost:5555
- **API文档**: http://localhost:5555/docs

## 目录说明

```
kikoerumanager/
├── start-all.bat      # 一键启动（用这个！）
├── setup.bat          # 首次安装
├── backend/
│   └── start.bat      # 后端启动
├── frontend/
│   └── start.bat      # 前端启动
├── test_data/         # 测试数据目录
└── data/
    └── config/        # 运行态配置文件
```

## 常见问题

### 1. 提示缺少Python
安装 Python 3.11+：https://www.python.org/downloads/

### 2. 提示缺少Node.js
安装 Node.js 18+：https://nodejs.org/

### 3. PostgreSQL 未就绪
先运行 `setup.bat`。日常启动时 `start-all.bat` 会尝试启动本机 PostgreSQL；如果服务损坏或端口被占用，再看 `scripts\install-postgresql.ps1` 的输出。

### 4. 端口被占用
- 后端端口 5555
- 前端端口 5556

后端端口可通过 `PORT` 环境变量修改；前端开发端口在 `frontend\vite.config.js`。

### 5. 如何停止服务？
直接关闭命令行窗口，或按 `Ctrl+C`

## 测试数据

将压缩包放入 `test_data\input\` 目录，系统会自动处理。
