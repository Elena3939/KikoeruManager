# 配置重载说明

Prekikoeru 当前提供两种配置更新方式：

- 手动重载：通过 API 或前端按钮重新读取配置文件
- 自动监视：`settings.py` 中已实现 `watchdog` 监听，但只有显式调用 `start_config_watcher()` 的启动入口才会启用

## 当前项目状态

### 一定可用的方式

手动重载接口：

```text
POST /api/config/reload
```

前端 `设置` 页也已经接入这个接口。

### 已实现但不是所有入口默认启用的方式

自动文件监视逻辑定义在：

[settings.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/config/settings.py)

其中包括：

- `ConfigFileChangeHandler`
- `start_config_watcher()`
- `stop_config_watcher()`
- `reload_config()`

当前仓库中，自动监视由 [backend/run.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/run.py) 调用；而常用启动入口如 `python -m app.main` 和当前桌面打包入口并不会默认启动自动监视。

换句话说：

- 如果你用常规开发脚本或桌面版，建议把“手动重载”当作标准方式
- 如果你准备切到 `backend/run.py` 作为入口，可以使用自动监听配置文件变化

## 配置文件位置

### Docker

```text
/app/config/config.yaml
```

### Windows 桌面打包版

```text
<exe目录>\data\config\config.yaml
```

### 开发环境

开发环境具体取决于 `CONFIG_PATH` 是否设置。

- 设置了 `CONFIG_PATH`：按该路径读取
- 未设置：按默认路径解析并在运行目录中创建

仓库中提供的示例配置位于：

[backend/config/config.yaml](D:/Clash%20Verge/KikoeruTool_Elena/backend/config/config.yaml)

## 手动重载用法

### 方式一：前端按钮

进入“设置”页面，点击“从配置文件刷新”或同类操作按钮。

### 方式二：直接调用 API

```bash
curl -X POST http://localhost:8000/api/config/reload
```

成功时会返回：

- 消息
- 当前配置文件路径
- 时间戳

## 自动监视工作方式

自动监视基于 `watchdog`，流程如下：

1. 启动配置观察器
2. 监听配置文件所在目录
3. 检测到文件变化后进行防抖
4. 调用 `load_config()` 或 `reload_config()`
5. 通知已注册的回调

## 哪些修改适合重载

- 存储路径
- 解压参数
- 重命名模板
- 分类规则
- 过滤规则
- 密码库清理与已处理压缩包清理策略
- Kikoeru 与 ASMR 相关配置

## 注意事项

- 正在运行的任务不会自动回滚
- 修改配置前建议备份
- 配置文件编码应为 UTF-8
- YAML 语法错误会导致重载失败

## 故障排查

### 调用重载后仍然无变化

- 检查 `CONFIG_PATH` 指向的到底是哪份文件
- 检查日志中的配置文件路径
- 确认你修改的是运行时配置，而不是仓库示例配置

### 自动监视没有触发

- 确认当前启动入口是否调用了 `start_config_watcher()`
- 如果没有，直接使用手动重载接口
