# 远程库存交互读路径

## 搜索建议

- `GET /api/library/index/global-search?mode=suggest` 只读取可用库存索引，不触发本地递归或群晖 `SYNO.FileStation.Search` 兜底。
- 未建索引或远程库存会在 `library_status[].search_mode` 返回 `skipped_suggest`，`fallback_used=false`。
- 完整搜索仍可在索引零命中时走受控 fallback；建议下拉不能用完整搜索替代，否则会重新引入固定等待远程超时的问题。
- 输入完整 RJ 时，索引结果按真实收录位置折叠：保留作品根目录和同库不同路径 / 多库副本，不展示继承同一 RJ 的特典、台本、图片等后代目录。
- 搜索框与建议面板之间保留可悬停桥接区；输入框失焦后，仅在鼠标确实离开搜索区域时延迟收起建议。

## “移动到...”窗口

- 目录搜索不再过滤当前已加载层级：本地库存直接查询 PostgreSQL `library_index_entries` 的 `pg_trgm` 索引；群晖库存按当前 `library_id` 调用 `SYNO.FileStation.Search`，只返回目录。前端固定 300ms 防抖、200 条上限，并在关键词变化或清空时立即取消旧请求，禁止前端递归展开整棵目录树。
- 搜索结果保留真实绝对路径和相对父路径，可直接选为移动目标或双击进入；本地索引未形成可用快照时明确提示重建，不允许静默退化为本地文件系统全库扫描。
- `POST /api/library/browser/navigation-snapshot` 只从可用的 PostgreSQL 库存索引生成当前目录、当前一级子项和祖先展开节点；索引可用时不对每个条目执行 `stat/isdir`，深路径打开不再产生逐层请求瀑布。
- 导航快照的 Redis 逻辑 key 为 `library/move-nav/{library_id}-{generation}-{view_revision}-{request_hash}`，TTL 使用统一短缓存；`generation` 或 `view_revision` 变化后自然切换新 key。Redis 未启用、读取失败或写入失败时直接读取 PostgreSQL 索引，不能影响目录导航。
- 前端目录请求使用 AbortSignal、递增 token 和索引视图版本校验。旧请求、旧库请求或晚到的旧 `view_revision` 不允许覆盖当前目录；索引导航不可用或快照过旧时回退 `/api/library/browser/list-folders`。
- `POST /api/library/browser/move-preview` 优先比较源、目标的索引子树，目录合并不算冲突；文件同名、文件/目录类型不一致、目标位于源目录内部才进入冲突确认。单棵子树达到 `100000` 条、索引缺项或顶层磁盘状态与索引不一致时回退真实文件系统预检。
- 索引预检结果使用 `library/move-plan/{uuid}` 保存 60～300 秒短期计划，并绑定源库、目标库、源路径、目标路径、索引 generation 和 view revision。计划明确过时时移动接口返回 `409` 要求重新确认；Redis 不可用或计划自然过期时不阻断移动，最终仍由文件系统执行和校验。
- 相同 `Idempotency-Key` 的已登记移动优先回放已有结果，即使原计划此时已过期也不会重复移动或误报 `409`。
- 移动成功后前端先移除当前视图中的源行，并等待返回的 `index_fences` 被 SSE / 索引状态更新到 `materialized_seq >= accepted_seq`；物化完成后做普通索引刷新，8 秒仍未完成才强制刷新列表和统计。

职责边界固定为：PostgreSQL 库存索引是导航和冲突预检读模型，Redis 只做短期加速与计划传递，真实文件系统是移动执行和最终存在性判断依据。

## 按社团分类

- 单项和批量分类复用本地移动的增量 mutation；移动结果必须透传 `operation_id`、`operation_state` 和 `index_fences`，前端先移除源行，再等待 `materialized_seq >= accepted_seq` 后读取新快照。
- 分类完成后的列表刷新固定使用 `force_refresh=false`。`force_refresh=true` 会把当前页所有顶层目录提交为读修补子树，社团目录可能包含上千文件，会造成无关递归扫描、索引中间水位闪烁和事件循环延迟。
- fence 等待只约束视图发布时间，不替代 mutation materializer；超时后仍只做普通索引读取，不用整页强制刷新制造第二批扫描任务。

## 群晖库存容量

- `GET /api/library/storage-info?library_id=...` 的容量口径是“该库存根路径所属共享文件夹所在卷”，不是整台群晖所有卷的总和。
- 后端从库存 `root_path` 取第一个路径段作为 share，例如 `/ASMR/作品` 对应 `/ASMR`；通过 `SYNO.FileStation.List.list_share` 的 `volume_status` 读取该 share 所属卷的 `totalspace` 与 `freespace`。
- 返回保留 `total_size_bytes`、`used_size_bytes`、`free_size_bytes`、`free_space_gb` 和 `volumes` 兼容字段，并补充 `storage_scope=share_volume`、`share_name`、`share_path` 说明统计范围。
- 找不到对应 share 或群晖没有返回容量时直接报错，不允许回退为整机卷容量求和，避免上传预览得到虚假的可用空间。

## 缓存与超时

- 同一 `library_id` 的并发刷新共用一个 singleflight 任务，避免页面并发请求重复访问群晖。
- 有历史缓存且缓存过期时，前台最多等待 `350ms`；刷新未完成就返回旧值并标记 `stale=true`、`stale_reason=timeout`，后台继续刷新。
- 冷启动或显式刷新最多等待 `2s`；超时返回 `504`，在途刷新继续执行并填充缓存，前台不会再被群晖长超时拖住。
