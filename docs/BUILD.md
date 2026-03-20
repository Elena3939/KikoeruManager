# Windows 打包说明

## 1. 当前打包入口

项目当前用于 Windows 打包的主要入口如下：

- [desktop_app.py](D:/Clash%20Verge/KikoeruTool_Elena/desktop_app.py)
- [build-release.bat](D:/Clash%20Verge/KikoeruTool_Elena/build-release.bat)
- [backend/build.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/build.py)
- [package.bat](D:/Clash%20Verge/KikoeruTool_Elena/package.bat)

推荐优先使用：

```bat
build-release.bat
```

## 2. 打包前准备

- Python 3.11+
- Node.js 18+
- 前端依赖已安装
- 后端依赖已安装
- 项目内图标文件存在：[backend/app.ico](D:/Clash%20Verge/KikoeruTool_Elena/backend/app.ico)

## 3. 推荐打包方式

在项目根目录执行：

```bat
build-release.bat
```

脚本会执行：

1. 构建前端
2. 安装后端依赖
3. 安装 PyInstaller
4. 检查 `pystray` 与 `Pillow`
5. 打包单文件 `exe`

## 4. 当前输出名称

当前文档与脚本已经统一为：

```text
Prekikoeru.exe
```

## 5. 打包版行为

桌面打包版启动后会：

- 启动内嵌后端
- 在浏览器打开本地地址
- 使用系统托盘运行
- 从项目图标中加载程序与托盘图标
- 在 `exe` 同级目录生成 `data/`

其中运行时配置文件位于：

```text
<exe目录>\data\config\config.yaml
```

## 6. 图标说明

当前打包和页面图标已经统一使用：

[backend/app.ico](D:/Clash%20Verge/KikoeruTool_Elena/backend/app.ico)

它同时用于：

- `exe` 图标
- 托盘图标
- 浏览器 favicon

前端构建时会复制到：

[frontend/public/favicon.ico](D:/Clash%20Verge/KikoeruTool_Elena/frontend/public/favicon.ico)

## 7. 备用打包方式

### 使用 Python 构建脚本

```bat
cd backend
py -3 -m pip install -r requirements.txt
py -3 build.py
```

### 使用旧脚本

```bat
package.bat
```

这个脚本仍可用，但更适合作为补充方案。

## 8. 常见问题

### 打包后没有托盘图标

优先检查：

- 包内是否带上 `app.ico`
- 运行入口是否使用当前版 [desktop_app.py](D:/Clash%20Verge/KikoeruTool_Elena/desktop_app.py)

### 标签页标题不对

检查：

- [frontend/index.html](D:/Clash%20Verge/KikoeruTool_Elena/frontend/index.html)
- 是否重新执行了前端构建

### 构建失败

先单独验证：

```bat
cd frontend
npm run build
```

以及：

```bat
py -3 -m py_compile desktop_app.py backend\build.py
```

## 9. 发布前建议

- 先确认托盘图标、页面标题和 favicon 是否一致
- 先确认配置文件能在 `data/config/config.yaml` 正常生成
- 先确认前端页面能通过打包入口访问，不依赖独立 Vite 服务
