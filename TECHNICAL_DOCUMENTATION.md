# Prekikoeru 技术文档

## 1. 项目定位

Prekikoeru 是一个围绕“本地文件整理流水线”设计的应用。它把压缩包、已有文件夹、字幕目录和库存目录接入同一个任务系统，通过规则配置驱动解压、元数据、重命名、过滤、分类、归档和同步下载。

## 2. 技术栈

### 前端

- Vue 3
- Vue Router
- Pinia
- Element Plus
- Axios
- Vite

### 后端

- FastAPI
- Uvicorn
- SQLAlchemy
- Pydantic v2
- PyYAML
- watchdog
- APScheduler
- aiohttp / httpx / requests
- Pillow / pystray

## 3. 目录结构

```text
backend/
  app/
    api/         HTTP API
    config/      配置模型与配置读写
    core/        核心业务逻辑
    models/      数据模型与数据库
frontend/
  src/
    api/         前端 API 封装
    router/      路由
    stores/      Pinia store
    views/       页面
desktop_app.py   桌面版入口
```

## 4. 前端页面与后端能力映射

| 页面 | 主要能力 |
|---|---|
| 概览 | 系统状态、监视器状态、统计信息 |
| 任务队列 | 查看和管理任务 |
| 问题作品 | 查看重复与冲突作品 |
| 库存管理 | 浏览库存与目录结构 |
| 密码库 | 查看密码与清理状态 |
| 已有文件夹 | 扫描、查重、处理已有文件夹 |
| 同步下载 | 按字幕目录扫描并发起 ASMR 同步 |
| 库存打包 | 配置和执行库存压缩打包 |
| 设置 | 编辑全部核心配置 |
| 日志 | 查看运行日志 |

## 5. 配置系统

配置模型定义在：

[backend/app/config/settings.py](backend/app/config/settings.py)

核心配置对象 `AppConfig` 包含：

- `storage`
- `processing`
- `watcher`
- `extract`
- `filter`
- `metadata`
- `rename`
- `classification`
- `password_cleanup`
- `processed_archive_cleanup`
- `path_mapping`
- `kikoeru_server`
- `asmr_sync`
- `auto_process`
- `process_existing`
- `asmr_sync_step`
- `backup_zip`

特点：

- YAML 持久化
- Pydantic 校验
- 缺省字段自动补齐
- 支持 `save_config()` 与 `reload_config()`
- 提供自动文件监视基础设施

## 6. 核心处理流

### 普通压缩包处理

1. 扫描输入目录或接收上传
2. 创建任务
3. 预检重复
4. 解压
5. 获取元数据
6. 重命名
7. 过滤
8. 分类入库
9. 归档原压缩包

这部分主要由以下模块协作完成：

- [task_engine.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/task_engine.py)
- [file_processor.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/file_processor.py)
- [extract_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/extract_service.py)
- [metadata_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/metadata_service.py)
- [rename_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/rename_service.py)
- [filter_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/filter_service.py)

### 已有文件夹处理

1. 扫描已有文件夹目录
2. 抽取 RJ 号
3. 做增强查重
4. 按配置执行元数据、重命名、过滤、字幕导入、分类

### ASMR 同步流程

1. 扫描字幕目录
2. 从文件夹名中识别 RJ 号
3. 预览可下载版本
4. 提交同步下载任务
5. 下载、同步字幕、重命名、分类、移动字幕文件夹

### 库存打包流程

1. 读取库存打包配置
2. 可选复制目录结构
3. 调用压缩逻辑生成包
4. 保存历史记录与断点状态

## 7. 查重设计

当前项目中的查重分三层：

- 直接重复：同 RJ 号或库存中已存在对应作品
- 关联作品查重：识别原作、翻译版、父级/子级关联作品
- Kikoeru 服务器查重：向远端服务查询是否已存在

相关模块：

- [duplicate_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/duplicate_service.py)
- [kikoeru_duplicate_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/kikoeru_duplicate_service.py)

## 8. 数据层

数据库定义在：

[backend/app/models/database.py](backend/app/models/database.py)

数据库承担的职责包括：

- 任务状态
- 问题作品记录
- 已有文件夹缓存
- 远端查重缓存
- 密码库与清理日志
- 已处理压缩包记录
- 库存打包记录
- 等待重试任务记录

## 9. API 层

主 API 定义在：

[backend/app/api/routes.py](backend/app/api/routes.py)

主要接口类别：

- 任务管理
- 文件上传与扫描
- 配置读取/保存/重载
- 监视器控制
- 冲突与查重
- 已有文件夹处理
- Kikoeru 服务配置与检查
- ASMR 同步
- 库存打包
- 日志与健康检查

## 10. 启动模式

### 开发模式

常用入口：

- `python -m app.main`
- `start-dev.bat`
- `start-all.bat`

特点：

- 前端和后端分开运行
- 前端由 Vite 提供
- 后端默认跑在 8000
- 前端默认跑在 5173

### Docker 模式

- 前端构建成静态文件
- 后端直接托管静态资源
- 对外仅暴露 8000

### Windows 桌面打包版

入口：

[desktop_app.py](D:/Clash%20Verge/KikoeruTool_Elena/desktop_app.py)

特点：

- 打包后使用系统托盘
- 自动打开浏览器
- 将运行数据写到 `exe` 同级 `data/`
- 使用项目内 `app.ico` 作为程序与托盘图标

## 11. 日志与运维

默认日志文件：

```text
data/app.log
```

建议重点关注：

- 配置加载日志
- 解压失败日志
- 元数据抓取异常
- Kikoeru/ASMR 外部请求错误
- 库存打包状态

## 12. 当前实现上的注意点

- 自动配置文件监视能力已实现，但不是所有启动入口默认启用
- 仓库中的 [backend/config/config.yaml](backend/config/config.yaml) 更适合作为默认模板，不一定等于运行时真正使用的配置文件
- 旧命名 `KikoeruTool_Elena` 在部分代码与依赖描述中仍有历史残留，文档层统一以 `Prekikoeru` 为准
