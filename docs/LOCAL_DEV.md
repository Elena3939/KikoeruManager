# 本地开发测试指南

## 快速开始（无需 Docker、无需打包）

### 1. 安装依赖

```bash
# 后端依赖（Windows 推荐直接跑 setup.bat；手动安装时也使用项目 venv）
cd backend
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt

# 前端依赖
cd ../frontend
npm install
```

### 2. 启动服务

#### Windows 用户

双击运行 `start-dev.bat` 或在命令行执行：
```cmd
start-dev.bat
```

首次使用优先运行根目录 `setup.bat`。它会检查 / 初始化本机 PostgreSQL，并把连接配置写入 `data/config/config.yaml`。

#### Linux/Mac 用户

```bash
chmod +x start-dev.sh
./start-dev.sh
```

### 3. 访问应用

- 前端界面: http://localhost:5556
- 后端API: http://localhost:5555
- API文档: http://localhost:5555/docs

### 4. 手动启动（分步）

如果不想使用脚本，可以分别启动：

**终端1 - 启动后端：**
```bash
cd backend
venv\Scripts\python.exe -m app.main
```

**终端2 - 启动前端：**
```bash
cd frontend
npm run dev
```

### 5. 测试步骤

1. **准备测试文件**
   ```bash
   # 创建测试目录
   mkdir -p test_data/input
   mkdir -p test_data/library
   mkdir -p test_data/temp
   
   # 复制压缩包到测试目录
   cp your-test-file.zip test_data/input/
   ```

2. **修改配置**
   编辑 `data/config/config.yaml`：
   ```yaml
   storage:
     input_path: "./test_data/input"
     temp_path: "./test_data/temp"
     library_path: "./test_data/library"
   ```

3. **开始测试**
   - 打开 http://localhost:5556
   - 拖拽文件到上传区域，或
   - 直接复制文件到 `test_data/input` 文件夹
   - 观察任务处理进度

### 6. 调试模式

**启用详细日志：**
```bash
# Windows
set LOG_LEVEL=DEBUG
venv\Scripts\python.exe -m app.main

# Linux/Mac
LOG_LEVEL=DEBUG python -m app.main
```

**使用 VS Code 调试：**
已创建 `.vscode/launch.json`，按 F5 即可启动调试。

### 7. 热重载

- 后端：修改代码后自动重启（uvicorn --reload）
- 前端：修改代码后自动刷新（vite HMR）

### 8. 常用命令

```bash
# 查看后端日志
tail -f backend/logs/app.log

# 清空测试数据
rm -rf test_data/temp/* test_data/library/*

# 重置测试数据库前先确认已备份；当前运行态数据在 PostgreSQL
# Windows 本地默认数据库：127.0.0.1:5432/kikoerumanager

# 运行单元测试
cd backend
venv\Scripts\python.exe -m pytest
```

### 9. 故障排除

**问题1: 前端无法连接后端**
- 检查后端是否在 5555 端口运行
- 检查 `frontend/vite.config.js` 中的代理配置

**问题2: 文件无法解压**
- 确保 7-Zip 已安装并添加到 PATH
- Windows: `where 7z`
- Linux: `which 7z`

**问题3: 权限错误**
- 以管理员身份运行终端
- 或修改文件夹权限: `chmod -R 777 test_data`

**问题4: 端口被占用**
- 后端: 设置 `PORT` 环境变量
- 前端: 修改 `frontend/vite.config.js` 中的端口

### 10. 生产环境打包

测试完成后，如需打包：

```bash
# Windows EXE
build-windows.bat

# Docker 镜像
docker-compose build
```

---

## 文件说明

- `start-dev.bat` - Windows 一键启动脚本
- `start-dev.sh` - Linux/Mac 一键启动脚本
- `data/config/config.yaml` - 本地运行态配置文件
- `test_data/` - 测试数据目录

---

## 快速测试流程

1. **启动服务**: 双击 `start-dev.bat` (Windows) 或 `./start-dev.sh` (Linux)
2. **准备文件**: 复制压缩包到 `test_data/input/`
3. **打开界面**: 浏览器访问 http://localhost:5556
4. **查看结果**: 观察任务处理和文件输出到 `test_data/library/`
5. **停止服务**: 在终端按 Ctrl+C

就这么简单！
