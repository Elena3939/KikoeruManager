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
- 日期调度最多使用 3 个并发 worker；每个日期内的 `product/info/ajax` 请求另有限制，避免日期并发和 HTTP 并发相乘打满服务器连接。
- 待处理发售日按该发售日下最小原作 RJ 升序排序；worker 取到一个发售日后，必须完整完成该发售日的特典搜索，再领取下一个发售日。
- 选中作品触发时，前端会按发售日传入选中的原作 RJ；后端以该发售日下选中 RJ 为锚点构造邻近候选，避免被同日其它公开作品的超大 RJ 跨度拖入整日全范围探测。
- 同一发售日选中多个作品时，候选按选中 RJ 的数字顺序合并去重，实际探测从最早选中 RJ 附近开始推进。
- 续跑时会跳过已完成作品级结论的原作，只扫描未判明的作品和发售日。
- 同一发售日被多个调度来源同时命中时，必须先按 RJ 数字区间切成稳定 range shard，并通过 active lease 排除正在查询的 RJ，避免不同 worker 重复请求同一格或漏掉相邻区间。
- `dlsite_bonus_probe_cache` 写入先进入 Redis dirty buffer，再低批次回写 PostgreSQL。`price` / `wishlist_count` 数据库列必须是 `BIGINT`，启动兼容迁移会强制校验 `udt_name=int8`；回写失败会 ACK 当前批次，避免毒数据反复重放打爆 DB / 日志，后续任务仍可重新从 DLsite 或 Redis overlay 补缓存。

## 异常规则

- `403`、`429`、风控页、HTTP 异常、日期页解析异常、批量 RJ 探测异常，都不能写出 `no_bonus`。
- 扫描范围超过预算时，可以沉淀已命中的隐藏特典线索，但不能把未覆盖的原作标为 `no_bonus`；该发售日记录为 `incomplete`，整轮任务继续完成并在汇总中提示 `incomplete_count`。
- 只有候选 RJ 全部得到稳定的 `ok` 或 `missing` 结果后，才允许写入剩余原作的 `no_bonus`。

## 进度字段

- `checked_probe_count` 表示已经确认过的 RJ 数。
- `probe_count` 表示本轮候选 RJ 总数。
- `request_count` 表示 DLsite 批量请求次数，最多 500 个 RJ 合并为 1 次请求。
- `original_count`、`original_concluded_count`、`original_pending_count` 表示作品级结论进度。
- `incomplete_count` 表示本轮中因预算等非网络异常未形成完整作品级结论的发售日数量。
