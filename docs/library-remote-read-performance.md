# 远程库存交互读路径

## 搜索建议

- `GET /api/library/index/global-search?mode=suggest` 只读取可用库存索引，不触发本地递归或群晖 `SYNO.FileStation.Search` 兜底。
- 未建索引或远程库存会在 `library_status[].search_mode` 返回 `skipped_suggest`，`fallback_used=false`。
- 完整搜索仍可在索引零命中时走受控 fallback；建议下拉不能用完整搜索替代，否则会重新引入固定等待远程超时的问题。

## 群晖库存容量

- `GET /api/library/storage-info?library_id=...` 的容量口径是“该库存根路径所属共享文件夹所在卷”，不是整台群晖所有卷的总和。
- 后端从库存 `root_path` 取第一个路径段作为 share，例如 `/ASMR/作品` 对应 `/ASMR`；通过 `SYNO.FileStation.List.list_share` 的 `volume_status` 读取该 share 所属卷的 `totalspace` 与 `freespace`。
- 返回保留 `total_size_bytes`、`used_size_bytes`、`free_size_bytes`、`free_space_gb` 和 `volumes` 兼容字段，并补充 `storage_scope=share_volume`、`share_name`、`share_path` 说明统计范围。
- 找不到对应 share 或群晖没有返回容量时直接报错，不允许回退为整机卷容量求和，避免上传预览得到虚假的可用空间。

## 缓存与超时

- 同一 `library_id` 的并发刷新共用一个 singleflight 任务，避免页面并发请求重复访问群晖。
- 有历史缓存且缓存过期时，前台最多等待 `350ms`；刷新未完成就返回旧值并标记 `stale=true`、`stale_reason=timeout`，后台继续刷新。
- 冷启动或显式刷新最多等待 `2s`；超时返回 `504`，在途刷新继续执行并填充缓存，前台不会再被群晖长超时拖住。
