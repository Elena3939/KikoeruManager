# 配置热重载功能说明

## 功能概述

应用程序现已支持配置文件的实时读取和热重载功能，修改配置后无需重启程序即可生效。

## 实现方式

### 1. 自动监控（推荐）

系统使用 `watchdog` 库监控配置文件变化，当检测到配置文件被修改时，会自动重新加载配置。

**工作原理：**
- 应用启动时自动启动配置文件监控器
- 监控 `config/config.yaml` 文件的变化
- 文件修改后 0.5 秒内自动检测并重新加载
- 所有模块会立即使用新的配置值

**支持的修改方式：**
- 直接编辑 `config/config.yaml` 文件
- 通过其他程序修改配置文件
- 使用版本控制工具更新配置文件

### 2. 手动刷新

在前端界面中提供了"从配置文件刷新"按钮，点击后会：
1. 调用后端 `/api/config/reload` 接口
2. 从磁盘重新读取配置文件
3. 更新内存中的配置对象
4. 刷新前端显示的配置值

**使用方法：**
1. 修改 `config/config.yaml` 文件
2. 在设置页面点击右上角的"从配置文件刷新"按钮
3. 确认配置已更新

### 3. 前端保存配置

通过前端界面修改配置并保存时：
1. 配置会自动保存到 `config/config.yaml`
2. 内存中的配置对象会立即更新
3. 相关文件监控系统会检测到变化
4. 所有服务会使用最新配置

## 配置文件位置

### 开发环境
```
d:\Clash Verge\KikoeruTool-1.6.4\config\config.yaml
```

### 生产环境（打包后）
```
<data_directory>\config\config.yaml
```
其中 `<data_directory>` 通常是：
- Windows: `C:\Users\<用户名>\AppData\Roaming\KikoeruManager\data`
- Linux: `~/.local/share/KikoeruManager/data`
- macOS: `~/Library/Application Support/KikoeruManager/data`

## 配置热重载流程

```
配置文件修改
    ↓
watchdog 检测到变化（0.5 秒防抖）
    ↓
自动重新加载配置到内存
    ↓
通知所有注册的回调函数
    ↓
各服务模块使用新配置
    ↓
日志记录加载结果
```

## API 接口

### POST /api/config/reload

手动触发配置重新加载

**请求示例：**
```bash
curl -X POST http://localhost:8000/api/config/reload
```

**响应示例：**
```json
{
  "message": "配置重新加载成功",
  "config_file": "/path/to/config/config.yaml",
  "timestamp": "2026-03-16T12:34:56.789012"
}
```

## 日志输出

配置热重载时会输出以下日志：

```
[CONFIG] 检测到配置文件修改：/path/to/config.yaml
[CONFIG] 开始重新加载配置文件...
[CONFIG] 配置重新加载成功
[CONFIG] storage.input_path = /new/input/path
[CONFIG] rename.template = '{rjcode} {work_name}'
```

## 注意事项

1. **并发安全**：配置读写操作使用锁机制，确保线程安全
2. **防抖处理**：文件修改后延迟 0.5 秒加载，避免多次触发
3. **错误处理**：如果配置文件格式错误，会保留原有配置并记录错误日志
4. **服务影响**：配置热重载不会影响正在进行的任务
5. **特殊服务**：密码清理和压缩包清理服务会在配置变更后自动重启

## 测试功能

可以使用提供的测试脚本验证热重载功能：

```bash
python test_config_hot_reload.py
```

测试内容：
- 自动监控配置文件变化
- 手动调用 reload API
- 配置恢复原状

## 故障排除

### 配置未自动更新

1. 检查日志输出，确认 watchdog 是否检测到变化
2. 确认配置文件路径正确
3. 检查 YAML 语法是否正确
4. 尝试手动点击"从配置文件刷新"按钮

### 配置加载失败

1. 查看 `data/app.log` 日志文件
2. 确认配置文件编码为 UTF-8
3. 检查配置项是否符合格式要求
4. 使用 YAML 验证工具检查语法

## 技术细节

### 后端实现

- **文件监控**：`watchdog.observers.Observer`
- **事件处理**：`ConfigFileChangeHandler`
- **配置加载**：`load_config()` 函数
- **回调机制**：`register_config_change_callback()`

### 前端实现

- **刷新按钮**：Settings.vue 页面顶部
- **API 调用**：`configApi.reload()`
- **状态管理**：Vue 3 Composition API
- **图标组件**：Element Plus Refresh 图标

## 版本信息

- 功能添加时间：2026-03-16
- 依赖库：watchdog >= 3.0.0
- API 版本：1.0.0
- 前端版本：1.1.0
