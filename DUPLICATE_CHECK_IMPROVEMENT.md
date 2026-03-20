# 增强查重功能说明

这份文档说明 Prekikoeru 当前的增强查重设计，重点覆盖关联作品、翻译版本和远端 Kikoeru 服务器查重。

## 1. 目标

传统按 RJ 号做“是否重复”判断不够用，因为实际整理场景里常见：

- 原作与汉化版共存
- 父级作品与子级拆分作品共存
- 同系列不同语言版本共存
- 本地库和远端 Kikoeru 库需要一起判断

增强查重的目标就是把“重复”从单一 RJ 号匹配，提升为“同一作品族”的判断。

## 2. 当前能力

### 直接重复

识别库存中是否已经存在同 RJ 号作品。

### 关联作品查重

支持识别：

- 原作
- 翻译版本
- 父级作品
- 子级作品

并返回更详细的冲突类型与建议处理动作。

### 远端 Kikoeru 查重

支持连接外部 Kikoeru 服务器，根据 RJ 号或关联作品链做远端库存检查。

## 3. 主要接口

以下接口已经在后端实现：

- `GET /api/linked-works/{rjcode}`
- `GET /api/linked-works/{rjcode}/check-library`
- `POST /api/conflicts/enhanced-check`
- `POST /api/kikoeru-server/check`

前端已在“已有文件夹”和“设置”等页面接入相关能力。

## 4. 返回结果包含什么

增强查重结果通常包含：

- `is_duplicate`
- `conflict_type`
- `direct_duplicate`
- `linked_works_found`
- `analysis_info`
- `related_rjcodes`
- `resolution_options`

这些字段会被前端用于展示：

- 冲突标签
- 语言与作品类型统计
- 推荐处理动作
- 明细弹窗

## 5. 冲突类型的实际含义

### `DUPLICATE`

同一 RJ 号已存在，通常表示直接重复。

### 关联作品型冲突

这类冲突说明不是简单重复，而是作品族内部已有相关版本，例如：

- 库中已有原作
- 当前待处理的是翻译版
- 或者反过来

这时更适合展示“保留两者”或“按你当前策略选择”的决策，而不是简单删除。

## 6. 推荐处理思路

### 直接重复

常见策略：

- 保留旧版本
- 保留新版本
- 合并保留
- 跳过处理

### 关联作品

更常见的推荐策略是：

- 保留两者
- 明确区分语言版本
- 仅在命名、分类、目录结构上区分，而不是删除其中一个

## 7. 与已有文件夹处理的关系

“已有文件夹”页面是增强查重的重要使用场景。

处理过程通常是：

1. 扫描已有文件夹
2. 提取 RJ 号
3. 执行增强查重
4. 展示冲突详情
5. 用户根据推荐动作决定是否继续处理

## 8. 与 Kikoeru 服务器查重的关系

如果启用了 Kikoeru 服务器配置，系统可以在本地库存之外继续检查远端是否存在。

适合场景：

- 本地和远端都有库存
- 需要避免重复导入到同一生态
- 想在“预解压阶段”就先判断是否值得继续处理

## 9. 相关代码位置

- [duplicate_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/duplicate_service.py)
- [kikoeru_duplicate_service.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/kikoeru_duplicate_service.py)
- [ExistingFolders.vue](D:/Clash%20Verge/KikoeruTool_Elena/frontend/src/views/ExistingFolders.vue)
- [routes.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/api/routes.py)

## 10. 使用建议

- 不要把“有关联作品”一律当成“必须删除”
- 先把命名模板和分类规则设计好，再启用自动处理
- 如果你的库中长期保留多语言版本，优先选择“保留两者”的策略
- 如果启用远端查重，注意保护好服务器地址、用户名和 Token
