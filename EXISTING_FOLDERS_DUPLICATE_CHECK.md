# 已有文件夹查重说明

## 1. 这个功能解决什么问题

很多用户的库存里已经有一批“手动解压”或“历史遗留”的作品文件夹，它们不是由 Prekikoeru 本身解压出来的，因此不能直接走普通压缩包流程。

“已有文件夹”模块就是为这种场景准备的。

它可以：

- 扫描已有文件夹目录
- 提取 RJ 号
- 对每个文件夹做增强查重
- 支持按选择的策略继续处理并入库

## 2. 工作流程

1. 在设置中配置 `existing_folders_path`
2. 打开“已有文件夹”页面
3. 执行扫描
4. 查看每个文件夹的查重结果
5. 对冲突项选择处理方式
6. 提交处理任务

## 3. 支持的能力

### 扫描缓存

系统会把扫描结果缓存到数据库，避免每次都从头全量解析。

### 重复检查

支持：

- 直接重复
- 关联作品查重
- 语言版本冲突

### 冲突详情

前端会展示：

- 冲突类型
- 已存在路径
- 关联作品列表
- 当前作品在作品族中的类型
- 推荐处理动作

### 按策略继续处理

你可以在冲突弹窗中：

- 删除当前文件夹
- 继续处理
- 按推荐策略处理

## 4. 与普通任务的区别

普通任务针对压缩包，流程包含解压。

已有文件夹任务针对已经存在的目录，流程通常是：

1. 提取 RJ 号
2. 查重
3. 获取元数据
4. 重命名
5. 过滤
6. 导入字幕
7. 分类

不会重复执行解压步骤。

## 5. 相关接口

前端主要使用以下接口：

- `GET /api/existing-folders`
- `POST /api/existing-folders/scan`
- `POST /api/existing-folders/check-duplicates`
- `POST /api/existing-folders/process`
- `POST /api/existing-folders/process-with-resolution`
- `POST /api/existing-folders/delete`
- `POST /api/existing-folders/refresh-cache`
- `POST /api/existing-folders/clear-cache`

## 6. 数据存储

已有文件夹相关缓存与记录位于数据库中，对应模型定义在：

[database.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/models/database.py)

其中包含：

- 文件夹路径
- RJ 号
- 缓存时间
- 查重结果

## 7. 适用场景

- 迁移旧库存
- 接手别人整理过的目录
- 想对现有目录重新套用重命名和分类规则
- 想批量排查库存中的重复或冲突版本

## 8. 使用建议

- 首次使用时先关闭自动批量处理，先看查重结果是否符合预期
- 先验证重命名模板，再批量处理已有文件夹
- 如果库存中长期保留多语言版本，不要把所有冲突都当成“错误”
- 大批量处理前建议备份库存目录

## 9. 相关代码位置

- [ExistingFolders.vue](D:/Clash%20Verge/KikoeruTool_Elena/frontend/src/views/ExistingFolders.vue)
- [task_engine.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/core/task_engine.py)
- [database.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/models/database.py)
- [routes.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/api/routes.py)
