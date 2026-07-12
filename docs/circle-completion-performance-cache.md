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
- cover API 本地命中时直接返回 `data/img/` 文件；文件缺失时立即返回 `404`，由前端回退到 DLsite 远程封面，同时后端按文件名去重创建补图任务。补图任务完成后，后续请求自然命中本地缓存，首屏图片请求不再等待 CDN。
- Docker 环境优先使用 `DATA_PATH/img` 作为封面缓存目录；默认镜像里 `DATA_PATH=/app/data`，因此缓存会落到持久化卷 `/app/data/img`。
- DLsite 图片路径里同时有目录 bucket RJ 和真实文件 RJ 时，缓存文件名取真实文件 RJ，避免翻译版 / 关联版显示 RJ 与封面 RJ 不一致导致 404。
- 按需下载失败时仍返回 404，前端 `WorkCard` 保留原有 DLsite fallback，不影响功能。

## DLsite 社团身份发现

- 社团身份不依赖库存索引；库存只在作品目录建立后投影本地收录态。
- 未知 maker ID 的社团先请求 DLsite 正式作品搜索页，只解析真实作品链接和 `.maker_name` 中的 `/circle/profile/=/maker_id/RG*.html`，不再对整页扫描全部 RJ。
- 名称标准化后只接受唯一 maker ID；同名对应多个 RG 时直接返回歧义错误，不自动选择。
- 作品搜索没有身份结果时可检查预告搜索，但预告结果同样必须含名称匹配的 maker 链接；`home-touch` 返回的全站预告页不会产生候选。
- maker ID 确认后只抓 maker 专属 profile 和 maker 专属 announce；已有 maker ID 的路径跳过身份搜索，保持原有快速路径。
- 搜索和预告同时发生网络异常时返回“DLsite 社团搜索暂时不可用”，不能误报为社团不存在。

## 验证入口

- 后端：`backend` 下执行 `.\venv\Scripts\python.exe -m pytest tests/test_circle_completion_announce_search.py tests/test_circle_completion_maker_discovery.py tests/test_circle_completion_paged_view.py tests/test_circle_completion_bonus_grouping.py -q`
- 前端：`frontend` 下执行 `npm run build`
- 浏览器：打开 `http://localhost:5556/circle-completion`，点击多个社团，再执行分页 `1 -> 2 -> 3 -> 2`，观察卡片是否保留、是否出现整体跳高或空白重建。
