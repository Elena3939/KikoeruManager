# 慢 SQL 与搜索索引治理

KikoeruManager 默认使用 PostgreSQL `pg_trgm` 作为搜索加速后端，不引入独立搜索服务。库存、操作历史、任务中心、密码库、已处理归档、安全网关和社团补全的片段搜索都应优先走 `searchable_text` 或与表达式索引完全一致的 SQL。

## 维护入口

- `GET /api/database/maintenance/performance`：返回数据库大小、运行参数、`pg_stat_statements` 状态、Top SQL、热点表扫描比例、搜索索引状态和优化建议。
- `GET /api/database/maintenance/search-status`：返回各业务域 trigram 索引是否就绪、缺失索引和旧索引残留。
- `POST /api/database/maintenance/pg-stat-statements/reset`：重置 `pg_stat_statements` 统计，用于优化前后对比。

`pg_stat_statements` 不可用时业务不受影响，只是 Top SQL 为空。Docker 单镜像和本地调优脚本会尽量启用预加载；外部 PostgreSQL 需要管理员自行配置 `shared_preload_libraries = 'pg_stat_statements'` 并重启。

## 查询约定

- 操作历史搜索写入 `activity_logs.searchable_text`，查询只匹配该字段。
- 任务中心搜索只匹配 `task_center_items.searchable_text`，不要回退到 `title/business_key/engine_task_id` 多列 OR。
- 库存搜索必须保持 SQL 表达式与 `idx_library_index_search_text_trgm` 一致。
- 社团补全、密码库等多字段搜索使用合并表达式索引；用户输入 `%/_/!` 必须转义。
- RJ 前缀、精确 ID、批次 ID、session key 仍走 btree / 复合索引，不强行走 trigram。
- 1 字符关键词会在前端或读路径收敛：库存搜索框默认至少 2 字符或完整 RJ；任务中心物化搜索忽略 1 字符过滤；操作历史即使允许 1 字符，也只取最多 2000 个 id 后再回查，避免宽泛关键词放大全表成本。

## 短关键词策略

- 库存全局搜索这类大范围入口，前端默认至少 2 个普通字符；完整 RJ 号或 RJ 数字串走专用 RJ 查询，不走 `%短词%`。
- 操作历史、任务中心等必须允许短关键词的入口，需要有 SQL 层 `LIMIT` / 分页上限，避免把高频短词一次性回表。
- 1-2 字符关键词不能依赖 trigram 一定命中索引；如果接口没有强分页、强作用域或专用 btree 路径，必须在入口拒绝或提示用户补充关键词。
- 所有片段搜索都必须转义 `%/_/!`，禁止把用户输入当作 SQL 通配符。

## 库存索引重建统计

- 全量 generation 扫描时同步累计条目数、文件总字节数和顶层目录数，并把这份统计传给 cutover。
- generation reconcile 只对 mutation 涉及的子树计算删除前后的统计差额，再合并回候选 generation。
- cutover 禁止再次对整个 `library_index_entries` 做 `COUNT/SUM` 聚合；`_building_generation_stats` 仅保留给兼容诊断和测试调用。
- 若新增重建阶段统计字段，必须同时更新扫描、子树 reconcile 和 cutover 三条路径，不能通过提高慢 SQL 阈值隐藏全代扫描。

## 配置

`database` 配置新增：

- `slow_query_monitor_enabled`
- `slow_query_threshold_ms`
- `auto_explain_enabled`
- `auto_explain_threshold_ms`
- `search_backend`

当前 `search_backend` 默认值为 `pg_trgm`。`pgroonga` 仅作为后续可选增强，不是默认依赖。
