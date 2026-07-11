# 社团补全性能缓存说明

## 目标

社团补全读路径拆成 `state`、`summary`、`page`、`work-codes`、`recent` 几层缓存，减少切社团、翻页、全选、特典操作时对同一个社团重复构建完整状态。

## 缓存层级

- L1：进程内 `TTLCache`，命中最快，用于同 worker 内短时间复用。
- L2：Redis JSON 缓存，跨请求、跨 worker、重启后仍可短 TTL 复用。
- Source：PostgreSQL，缓存 miss 时才构建完整社团状态。

Redis 不可用时会自动降级为 L1 + 数据库，不影响功能。

## 失效规则

- 单社团写路径调用 `invalidate_completion_view_cache(circle_id)` 后，递增 `circle-completion:version:{circle_id}` 并清本进程 L1。
- 全量未知影响范围调用 `invalidate_completion_view_cache()` 后，递增全局 epoch，让旧 Redis key 自然失效。
- `/recent` 目录使用独立 `recent` 版本，社团索引、刷新、拥有态同步后会主动失效。

## 前端交互

- 切社团默认只请求 `/works`，不再并发请求 `/summary` 和 `/works` 两个冷读接口。
- `/works` 响应中的 summary 字段直接用于首屏统计。
- 翻页时保留旧页内容，叠加轻量 “更新中” 状态；新页数据返回后继续播放原有卡片入场、hover、active 动效。
- `CircleWorksViewport` 在 server paging 翻页时不再强制 `measure()`，只在布局、列数、行高变化时重新测量。

## 封面缓存

- `/works` 返回的 `image_url` / `thumb_image_url` 优先使用 `/api/circle-completion/cover/{RJ}.jpg` 和 `/api/circle-completion/cover/{RJ}_sam.jpg`。
- cover API 本地命中时直接返回 `data/img/` 文件；文件缺失时按 RJ 推导 DLsite CDN 地址，下载落盘后再返回。
- Docker 环境优先使用 `DATA_PATH/img` 作为封面缓存目录；默认镜像里 `DATA_PATH=/app/data`，因此缓存会落到持久化卷 `/app/data/img`。
- DLsite 图片路径里同时有目录 bucket RJ 和真实文件 RJ 时，缓存文件名取真实文件 RJ，避免翻译版 / 关联版显示 RJ 与封面 RJ 不一致导致 404。
- 按需下载失败时仍返回 404，前端 `WorkCard` 保留原有 DLsite fallback，不影响功能。

## 验证入口

- 后端：`backend` 下执行 `..\.venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py tests\test_circle_completion_bonus_grouping.py -q --basetemp .pytest-codex-circle-cache-final`
- 前端：`frontend` 下执行 `npm run build`
- 浏览器：打开 `http://localhost:5556/circle-completion`，点击多个社团，再执行分页 `1 -> 2 -> 3 -> 2`，观察卡片是否保留、是否出现整体跳高或空白重建。
