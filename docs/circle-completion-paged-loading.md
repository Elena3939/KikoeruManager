# 社团补全分页加载接口

## 背景

大社团详情页不能继续一次性返回全量作品。`RG33577` 这类社团旧接口会一次构造数百条作品和约 MB 级 JSON，前端再对全量 `detail.works` 做筛选、分页、来源对比和图片加载，打开页面时容易卡顿。

新版页面拆成“摘要”和“当前 tab 当前页作品”两条读路径：

- 摘要只返回社团基础信息和统计。
- 作品列表按 tab、筛选、搜索、排序、分页查询。
- 全选当前筛选结果单独走编号接口，保持旧语义。
- 旧详情接口继续保留，兼容旧前端。

## API

### `GET /api/circle-completion/circles/{circle_id}/summary`

参数：

- `include_dl_only`: `boolean`，默认 `true`。

返回社团摘要，不返回 `works`：

- `circle_id`
- `circle_name`
- `source_mask`
- `last_indexed_at`
- `owned_count`
- `missing_count`
- `downloadable_count`
- `dl_only_count`
- `filtered_count`
- `total_works`
- `unreleased_count`
- `new_works_count`
- `bonus_works_count`
- `owned_stats`
- `compare_stats`
- `status_filter_counts`

### `GET /api/circle-completion/circles/{circle_id}/works`

参数：

- `tab`: `missing | owned | compare`，默认 `missing`。
- `page`: 页码，默认 `1`。
- `page_size`: 每页数量，默认 `10`，服务端最大 `200`。
- `include_dl_only`: 是否包含无 ASMR.ONE 来源的缺失作品。
- `status_filters`: 逗号分隔，支持 `repairable,downloadable,missing,no_source`。
- `owned_filter`: `all | original | simplified | traditional | subtitle | bonus`。
- `compare_filter`: `all | kikoeru | dlsite | asmr_one | missing`。
- `search`: owned / compare tab 搜索标题、RJ、关联 RJ。
- `sort`: `updated_desc | release_asc | release_desc`。

返回：

- `items`
- `total`
- `page`
- `page_size`
- `page_count`
- 同 summary 的统计字段

`missing` / `owned` 的 `items` 不返回 `owned_paths`、完整 `source_compare` 等重字段。`compare` 返回扁平来源对比 DTO，用 `sourceCompare` 展示三方来源，不把普通列表 payload 放大。

### `GET /api/circle-completion/circles/{circle_id}/work-codes`

使用与 `works` 相同的筛选参数，但不分页。返回：

- `canonical_rjcodes`
- `downloadable_rjcodes`
- `requested_rjcodes`
- `total`
- `downloadable_count`

前端“全选”使用这个接口，所以选中的是当前筛选结果全部作品，不是只选当前页。

### `GET /api/circle-completion/circles/{circle_id}/work-location`

参数与 `works` 使用同一套筛选 / 排序口径，额外包含：

- `rjcode`: 要定位的 RJ 号，可为 canonical、display、关联 RJ、下载计划 RJ。
- `page_size`: 当前列表页大小。

返回轻量定位结果，不返回作品列表，也不返回全量 RJ codes：

- `matched`: 当前 tab / 筛选 / 排序下是否命中。
- `canonical_rjcode`
- `display_rjcode`
- `page`
- `page_size`
- `page_count`
- `total`

页头 RJ 搜索跳转用这个接口计算目标页，避免为了翻页定位把当前筛选结果的全部 RJ 拉到前端。

### `GET /api/circle-completion/work-search`

参数：

- `keyword`: 作品标题、RJ 号或关联 RJ 号。
- `limit`: 返回数量，默认 `20`，服务端最大 `50`。

返回已建立社团索引内命中的作品，不触发 DLsite / Kikoeru 外部请求：

- `circle_id`
- `circle_name`
- `canonical_rjcode`
- `display_rjcode`
- `linked_rjcodes`
- `title`
- `image_url`
- `thumb_image_url`
- `cvs`
- `release_date`
- `owned`
- `server_owned`
- `has_asmr_one`
- `asmr_available_rjcode`
- `last_indexed_at`

前端页头搜索框使用这个接口。点击结果后根据 `owned` 状态切到目标社团的 `已满足` 或 `缺失作品` tab，再通过 `work-location` 翻到目标页并高亮命中卡片；页头搜索框保留命中 RJ。无命中时展示 `No Data`。

## 前端数据流

`CircleCompletion.vue` 不再把 `detail.works` 当全社团全量数组使用。现在它只代表当前 tab 当前页：

- 选中社团时并发请求 `summary` 和当前 tab 第 1 页。
- 切 tab、分页、筛选、搜索、排序时只请求 `works`。
- 搜索有 debounce，避免每个字符都打接口。
- 页头 RJ / 作品定位搜索只查已建立索引，使用 debounce + AbortController 取消上一次请求，不会触发社团索引或外部 HTTP；无命中时展示 No Data 状态。
- 搜索结果点击后只请求轻量定位结果和目标页，不请求旧 full detail，也不拉全量 `work-codes`，避免大社团定位跳转造成额外卡顿。
- 邻近社团预取只缓存 summary + missing 首屏，并保存分页元信息，避免把 summary 总数误当当前页总数。
- 下载预览、刷新选中、开始下载仍使用 `canonical_rjcodes`，接口语义不变。

## 图片加载

`CircleWorksViewport` 继续使用 `@tanstack/vue-virtual`。卡片和列表行新增 `imageActive`：

- 未激活时只显示占位，不挂真实 `src`。
- 只有虚拟可见行和 overscan 内作品进入图片加载队列。
- 同屏图片加载并发限制为 `6`。
- 图片仍使用 `loading="lazy"`、`decoding="async"`、`fetchpriority="low"`。
- 本地 `/api/circle-completion/cover/*` 仍优先，DLsite 远程 URL 只作为 fallback。

## 验证

本变更不需要数据库迁移，也没有新增索引。首屏性能收益来自减少响应体、减少前端全量数组计算、限制图片并发，而不是数据库结构调整。

## 索引任务进度与本地拥有态

社团索引启动阶段不再同步等待 `sync_local_owned_index()` 全量重建 `library_owned_works`。全量重建会读取所有已索引社团作品并解析关联 RJ，线上中等规模库首次执行可能卡住 80 秒以上。

当前社团的拥有态在索引后段通过 ready 库存索引局部核对：

- ready 库存索引可用时，只 upsert / prune 当前社团涉及的 canonical RJ。
- ready 库存索引不可用时，不清理旧 `library_owned_works` 快照，避免误删拥有态。
- 详情页、摘要和左侧社团统计继续从 `LibraryOwnedWork` 读取，当前社团索引完成后会立刻写回新快照。

前端社团索引进度以 `/api/events/stream` SSE 为主通道。启动任务后不再立即轮询 job 状态；运行中耗时由本地计时器每秒递增。只有当前 job 超过 45 秒没有收到 SSE 事件，或页面恢复 / 终态收尾时，才调用 job 状态接口兜底校正。

回归验证入口：

- `cd backend && venv\Scripts\python.exe -m pytest tests\test_circle_completion_paged_view.py -q --maxfail=1`
- `cd backend && venv\Scripts\python.exe -m pytest tests\test_circle_completion_owned_sync.py -q --maxfail=1`
- `cd frontend && npm run build`
