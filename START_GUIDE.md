# Prekikoeru 启动指南

这份文档面向日常使用者，重点说明第一次安装、启动和常见入口。

## 首次安装

### 方法一：推荐方式

直接执行：

```bat
setup.bat
```

脚本会自动完成：

- 环境检查
- 后端虚拟环境创建
- Python 依赖安装
- 前端依赖安装

### 方法二：手动安装

后端：

```bat
cd backend
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

前端：

```bat
cd frontend
npm install
```

## 日常启动方式

### 一键启动

```bat
start-all.bat
```

适合普通使用。脚本会：

- 检查依赖
- 启动后端窗口
- 启动前端窗口

### 分开启动

只启动后端：

```bat
cd backend
start.bat
```

只启动前端：

```bat
cd frontend
start.bat
```

### 开发模式启动

Windows CMD：

```bat
start-dev.bat
```

Windows PowerShell：

```powershell
.\start-dev.ps1
```

Linux/macOS：

```bash
chmod +x start-dev.sh
./start-dev.sh
```

## 访问地址

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

## 推荐的首次配置顺序

1. 打开“设置”
2. 配置存储路径
3. 配置 7-Zip 路径
4. 配置密码列表
5. 配置重命名模板
6. 配置分类规则
7. 视需要开启监视器

## 目录说明

- `backend/`：后端服务
- `frontend/`：前端界面
- `data/`：运行日志和数据库
- `test_data/`：脚本会创建的测试目录

## 配置文件位置

当前项目存在两类配置文件来源：

- 仓库内默认配置：[backend/config/config.yaml](backend/config/config.yaml)
- 实际运行时配置：由运行环境根据 `CONFIG_PATH` 或默认逻辑决定

桌面打包版首次运行后，会在 `exe` 同级目录生成：

```text
data/config/config.yaml
```

如果你希望开发环境直接使用仓库示例配置，建议手动设置 `CONFIG_PATH`，或将示例复制到实际运行位置。

## 停止服务

- 前端窗口中按 `Ctrl+C`
- 关闭脚本弹出的命令行窗口
- 或手动结束占用 5173 / 8000 端口的进程

## 常见问题

### Python 未找到

安装 Python 3.11+，并确认 `py` 或 `python` 命令可用。

### npm 未找到

安装 Node.js 18+，并确认 `npm.cmd` 可用。

### 端口被占用

项目默认使用：

- 8000：后端
- 5173：前端

先关闭旧进程，再重新启动。

### 页面能打开但没有数据

- 确认后端已启动
- 检查 `http://localhost:8000/docs`
- 查看日志页面或 `data/app.log`
