# 2026-10-22 17:19 生产库存索引堵塞与改名后不可见排查

本次仅只读排查，没有修改业务代码、线上数据、配置，没有发布或重启。时间均为北京时间。目标主机已验证为 Elena，生产容器为 elena39-kikoerumanager，镜像 elena39/kikoerumanager:1.6.129。

## 已确认的结论

1. 两个作品目录都仍在磁盘上，不是文件被删除。
2. 索引追赶存在真实的反复超时回滚：17:17:49.906 至 17:20:26.607，PostgreSQL 记录 22 次 statement timeout，全部为连接 PID 51 上的库存索引 SQL。
3. 目录统计 SQL 的 COALESCE(parent_path, '') 条件不能按现有 parent_path 普通索引定位目录。只读计划对比确认发生明显扩大读取，是这次反复超时中的明确性能缺陷。
4. 同库改名快速路径没有重算 rjcode，同时跳过目标 reconcile。路径改好了，但新 RJ 编号搜不到，这是独立且尚未恢复的正确性缺陷。
5. 17:34:32 复查所有库存 ready/idle，accepted_seq 等于 materialized_seq，未完成账本数和 pending mask 数均为 0；两个目录仍存在，但 RJ 字段仍错误。

## 文件实际位置与错误索引

| 磁盘真实目录 | 索引错误保留的 RJ | 索引子树行数 | 索引记录的文件数 |
|---|---|---:|---:|
| /library_asmr/マヨタマ/[マヨタマ][RJ01570851][] | RJ01571862 | 3505 | 3478 |
| /library_asmr/マヨタマ/[マヨタマ][RJ01549462][] | RJ01550674 | 1609 | 1560 |

通过限定父目录的一层读取及目录内部样本确认文件存在，没有执行全库扫描。文件数量来自数据库聚合字段，不是本轮重新递归计数。

library_index_entries 与 library_index_rj_entries 均保留旧 RJ，不能只修其中一张表。

## 改名与追赶时序

| 事件 | RJ01549462 | RJ01570851 |
|---|---|---|
| 原编号 | RJ01550674 | RJ01571862 |
| operation_id | 84a3db97-a2ca-45b8-914d-a59218faeb91 | 78917fe3-533b-47ef-ad6f-da53dd98991d |
| ledger seq | 3933 | 3934 |
| prepared_at | 17:17:44.903 | 17:18:43.252 |
| filesystem_started_at | 17:17:45.483 | 17:18:45.642 |
| finalized_at | 17:17:46.363 | 17:18:49.228 |
| ledger applied_at，事务内时间 | 17:20:03.552 | 17:20:29.183 |
| 状态 updated_at，事务内时间 | 17:20:07.772 | 17:20:34.131 |

PostgreSQL 同一连接随后记录 17:20:09.275 和 17:20:35.216 的 COMMIT 完成；浏览日志在 17:20:09 和 17:20:36 分别恢复一项。按改名 finalized 到上述提交完成约为 143 秒、106 秒。账本时间戳是事务内赋值，不能直接当作事务已经提交的时刻。

17:18:53 重命名接口耗时 12832ms；操作历史于 17:18:55.091 记录成功。这里的成功代表文件系统改名及账本接收完成，不代表索引追赶完成。

## 为什么“消失”

库存读路径会反连接 library_index_pending_masks，排除待物化影响范围，避免返回已失效路径。两次操作均为 move 子树并附带目标 reconcile。在追赶完成前，目录被隐藏：17:17:56 返回 44 项，17:18:53 返回 43 项，17:20:36 恢复 45 项。

遮罩解除后，新 RJ 仍搜不到的原因在生产源码：

- app/core/library_index/snapshot_store.py，_move_subtree_same_library_in_session：UPDATE 只变更 relative_path、absolute_path、parent_path、name、name_sort_key、depth、materialized_seq、indexed_at，没有更新 rjcode。
- app/core/library_index/mutation_service.py:1135-1147：同一次操作中匹配 move target 的 reconcile 被跳过。
- _find_by_rj_prefix：使用 LibraryIndexEntry.rjcode.like 查询，不会用新路径里的 RJ 替代错误旧字段。

因此短时列表消失与长期新 RJ 搜不到有不同直接原因。

## 堵塞的直接证据与代码机制

PostgreSQL 原始日志 /app/postgres/postgresql.log（本轮仅读取末尾 4MB）：

- 10 次 UPDATE library_index_entries 改名子树超时。
- 11 次 INSERT INTO library_index_directory_stats ... SELECT 聚合超时。
- 1 次 DELETE FROM library_index_rj_entries 超时。
- 最早 17:17:49.906，最晚 17:20:26.607；实际早于用户观察到的 17:19。

生产 mutation_service.py 常量：FAST_PATH_STATEMENT_TIMEOUT_MS=1500，FAST_PATH_LOCK_TIMEOUT_MS=200，FAST_PATH_PAUSE_SECONDS=1，FAST_PATH_MAX_ROWS=5000。

两个子树均小于 5000 行，进入快速路径。快速路径任一 SQL 超时即回滚整个事务，计入进程内 timeout_count，抛出 _FastPathRetryLater；调用方直接 return False，不进入普通失败计数。因此 ledger.attempt_count=0、error=NULL 不代表没有失败重试。固定 1 秒暂停后仍重试同一条账本，期间后续 seq 必须等待。

此外 _should_pause_fast_path 在 database_write.waiting>0 或主池压力高时暂停物化；当天有多次业务写预算等待 2～6 秒。该机制能继续延长等待，但未采集当时暂停计数，无法把总延迟精确拆成暂停和执行耗时。

## 目录统计 SQL 的计划验证

在生产执行只读 EXPLAIN，未执行 EXPLAIN ANALYZE，也未执行数据修改。对比保留 library_id、generation、materialized_seq 和 pending mask 条件的统计 SELECT。

原条件：COALESCE(parent_path, '') = 'マヨタマ'。

- 使用 idx_lie_generation_materialized_seq，预计取出 119365 条候选。
- Bitmap Heap Scan 再以 COALESCE(parent_path, '') 过滤目录。
- 聚合计划总代价 88457.72。

仅将非根目录条件改成 parent_path = 'マヨタマ'：

- 使用现有 idx_lie_generation_children_time，Index Cond 包含 library_id、generation、parent_path。
- 聚合计划总代价 5.10。

这是计划估计，不是实测运行时间或倍数承诺。当前 masks 已空，不能把此刻计划当作故障瞬间完整计划，但谓词无法直接匹配普通 parent_path 索引的问题已被验证；11 次统计超时由历史数据库日志直接证实。

## 数据库整体变慢的证据与边界

- 17:15 起已有多个 COMMIT 超过 1 秒；17:19:20.219 的一个 COMMIT 达 7052.530ms，17:19:36.413 达 5421.750ms。
- 17:18:19 普通按 ID 查询 asmr_download_sessions 耗时 3693ms；17:18:43 查询操作幂等键耗时 2361ms。
- 应用主循环同期多次停顿 2～6 秒；重命名 async 路由存在直接调用同步数据库操作的代码，数据库慢会放大 HTTP 主循环阻塞。
- 17:18:14 aria2 进程快照为 D (disk sleep)，wchan=wait_on_page_bit_killable，同时 Dirty 约 587MiB；这是当时 I/O 等待线索。
- 数据库 fsync=on、synchronous_commit=on，数据库挂载在 volume1。不能因为库存所在 volume4 使用率 99% 就直接认定为数据库慢的根因。
- 事后 PostgreSQL 未见锁等待，系统事后采样也未持续饱和；这些只能证明采样时状态，不能排除故障期间锁或存储延迟。

现有证据不足以把底层慢提交归因到某块磁盘故障、DSM 特定任务或单一进程。没有故障瞬间的 PostgreSQL wait event 与逐盘延迟连续采样。可以确认的是：整体数据库迟缓叠加低效统计查询，触发 1.5 秒超时后反复整笔回滚，造成索引队头长期不前进。

## 具体修复范围（本轮未实施）

1. 目录统计按 parent_path 的真实存储约束构造可使用现有索引的条件，单独处理根目录和 NULL 语义；不要只增加超时阈值。
2. 快速路径反复超时必须有可观测的有界处理，避免永久重试同一整笔事务；保证连续水位与事务原子性，不能简单吞掉失败放行后续 seq。
3. 同库/跨库路径变更重新计算受影响的 RJ 派生字段，并同步派生 RJ 索引；保留子目录自身独立 RJ 语义，不能全子树一刀切覆盖。
4. 同步数据库调用移出 async 路由的事件循环，覆盖 prepare、filesystem_started、finalize 等完整链路。
5. 修复后只对两个已确认目录及其派生索引做受控纠正；当前数据尚未改动，不需要全库重建来掩盖缺陷。

## 本地证据清单

以下文件在 .codex 忽略目录中，不含数据库认证输出：

- production-app-20261022.log：应用日志截取。
- production-index-20261022.log：容器状态与 stdout 日志。
- incident-db-1022.txt、incident-detail-1022.txt：账本、操作、遮罩、路径与 RJ 字段。
- incident-prod-source-1022.txt、incident-runtime-1022.txt：生产源码与 SHA-256；运行态诊断 HTTP 被门禁以 401 拒绝，未绕过门禁，不能将其视为成功的运行态诊断。
- incident-pglog-1022.txt：慢提交及 SQL 日志。
- incident-pg-errors-1022.txt：22 次超时的完整 SQL，以及数据库相关设置。
- incident-plan-1022.txt：两种 parent_path 谓词的只读计划与现有索引定义。
- incident-finalcheck-1022.txt：17:34:32 最后复核。
