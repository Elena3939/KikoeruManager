# DLsite ASMR 特典探测

社团补全的特典探测只使用 DLsite 官方数据源，目标是为已索引社团补齐早期特典、限时特典和隐藏特典，并把可复用线索沉淀到本地。

## 完成口径

- 作品级结论只有 `has_bonus` 和 `no_bonus` 两种，对应 `dlsite_bonus_original_probe_states.status`。
- 发售日完成必须满足：该发售日下所有同社团、同 maker 的原作 RJ 都已有作品级结论。
- `dlsite_bonus_probe_dates.status=completed` 只能表示该发售日完成，不能用单次 RJ 批次完成替代。
- `500RJ` 只是 `product/info/ajax` 的请求合并单位，用于减少 DLsite 请求次数，不是扫描完成依据。

## 展示规则

- 后端保留每个隐藏特典 RJ 的真实记录和父子关联，不合并写库数据。
- 社团补全作品卡只在展示层聚合同一父作品下的同名拆分特典；标题末尾形如 `_01`、`＿０１` 的编号会被去掉后作为聚合 key。
- `【早期限定415大特典】_01`、`【早期限定415大特典】_06`、`【早期限定415大特典】_09` 展示为一个 `【早期限定415大特典】`；不同基础标题仍分别显示。
- 聚合后的礼物保留成员 RJ 列表，选中、已收录、可下载、入库和预览状态按成员合并判断。

## 调度规则

- 查询前先查 `dlsite_bonus_probe_hit_index` 和 `dlsite_bonus_probe_cache`，有本地命中线索时优先确认并写入社团作品。
- 本地线索命中后仍要继续补完同发售日未结论原作，不能直接把整个发售日跳过。
- 日期调度最多使用 6 个并发 worker；每个日期内的 `product/info/ajax` 请求从 `bonus_probe.product_info_total_concurrency` 总预算中均摊，默认总并发 6，避免日期并发和 HTTP 并发相乘打满服务器连接。
- 待处理发售日按该发售日下最小原作 RJ 升序排序；worker 取到一个发售日后，必须完整完成该发售日的特典搜索，再领取下一个发售日。
- 选中作品触发时，前端会按原作发售日传入选中的原作 RJ；后端必须在该发售日全站同位数公开 RJ 边界内放开编号距离，不能只扫选中 RJ 附近。
- 选中单个原作时，日期页边界不能按同社团过滤；隐藏特典不在日期页，必须以原作发售日为硬边界，从选中 RJ 后一位扫到当天更大的同位数公开 RJ 边界，必要时再延伸到次日第一个超过当天右边界的同位数 RJ 之前。6 位旧 RJ 不参与当前新作日期边界，避免旧编号 / 翻译版把范围拉爆。
- 单选 / 选中作品复用本地隐藏特典命中时，也不能把缓存覆盖当成发售日段完成；仍要继续扫描未缓存候选，补齐同一原作的 `_02`、`_03` 等后续隐藏特典。
- 单选 / 选中作品复用本地隐藏特典命中时，必须校验命中 RJ 自身的 DLsite 发售日属于当前探测发售日；不同发售日的历史命中和旧脏 `bonus` 链接都不能覆盖当前选中原作。若已有显式 `bonus` 关联指向其它原作，只能覆盖被关联的原作，不能把同发售日其它选中 RJ 提前判为 `has_bonus`。
- 部分官方隐藏特典 `product/info/ajax` 会返回空发售日，例如 `RJ01201745`；这类命中不能因空日期被排除，应在当前探测日期内按同 maker / RJ 范围归属，并用当前原作发售日写入命中索引。若隐藏特典自身有明确发售日，则必须等于当前探测发售日。
- 同一发售日选中多个作品时，候选按当前发售日、同 maker 的公开 RJ 范围合并去重，实际探测仍按稳定 range shard 推进。
- 日期页只用于枚举公开 RJ 边界；分类不做硬过滤，不能用 `SOU` / ASMR 排除候选，因为隐藏特典可能是图片等非音声类型。最终归属和特典结构只信 `product/info/ajax`。
- 续跑时会跳过已完成作品级结论的原作，只扫描未判明的作品和发售日。
- 同一发售日被多个调度来源同时命中时，必须先按 RJ 数字区间切成稳定 range shard，并通过 active lease 排除正在查询的 RJ，避免不同 worker 重复请求同一格或漏掉相邻区间。
- `dlsite_bonus_probe_cache` 写入先进入 Redis dirty buffer，再低批次回写 PostgreSQL。`price` / `wishlist_count` 数据库列必须是 `BIGINT`，启动兼容迁移会强制校验 `udt_name=int8`；回写失败会 ACK 当前批次，避免毒数据反复重放打爆 DB / 日志，后续任务仍可重新从 DLsite 或 Redis overlay 补缓存。
- 缓存批量读取不能把几万 / 几十万 RJ 一次性塞进 `IN (...)`。小批量按 `bonus_probe.cache_lookup_batch_size` 分批（默认 1000，上限 3000），PostgreSQL 且数量达到 3000 时使用临时表 `JOIN` 回查，失败再回退分批 `IN`。

## 异常规则

- `403`、`429`、风控页、HTTP 异常、日期页解析异常、批量 RJ 探测异常，都不能写出 `no_bonus`。
- 新作日期页请求用于判断同发售日公开作品边界；该请求网络失败时必须快速返回 `http_error` 并把该发售日记为 `incomplete`，不能长时间重试拖住整站，也不能继续写 `no_bonus`。
- 扫描范围超过预算时，可以沉淀已命中的隐藏特典线索，但不能把未覆盖的原作标为 `no_bonus`；该发售日记录为 `incomplete`，整轮任务继续完成并在汇总中提示 `incomplete_count`。
- 只有候选 RJ 全部得到稳定的 `ok` 或 `missing` 结果后，才允许写入剩余原作的 `no_bonus`。

## 进度字段

- `checked_probe_count` 表示已经确认过的 RJ 数。
- `probe_count` 表示本轮候选 RJ 总数。
- 日期内 `current_probe_checked_count` / `current_probe_total_count` 是高频运行态字段，候选 lease 完成后必须先上报 `0/总数`；TaskEngine 只通过 Redis runtime/SSE 推送，不把每个 RJ 进度写进 PostgreSQL `progress_log`。
- `request_count` 表示 DLsite 批量请求次数，最多 500 个 RJ 合并为 1 次请求。
- `original_count`、`original_concluded_count`、`original_pending_count` 表示作品级结论进度。
- `incomplete_count` 表示本轮中因预算等非网络异常未形成完整作品级结论的发售日数量。
