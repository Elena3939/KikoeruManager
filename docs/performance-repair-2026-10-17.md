# 2026-10-17 性能修复记录

本批基于现有未提交工作区增量修改，未部署、未执行生产回填。修复行为与性能验收分开记录；本地测试通过不代表 NAS 上的延迟、帧率目标已经达成。

## 已落地的行为

### 运行响应性

- watcher 在专用后台线程完成递归注册，提供 starting/ready/failed/stopping 状态；初始化期间关闭会阻止监听器再次发布，移动/删除 dirty 记录仍进入原一致性协议。
- ASMR sessions 列表仅投影标量字段，不读取 selected_resources、selected_filters、statistics、failure_summary 四个大型 JSON 字段；详情仍使用详情接口。连接、查询、读取、转换和响应编码分段计时，完整 Session 生命周期在线程内。
- 心跳告警和线程栈分别限频，记录停顿标识和启动/运行阶段。

### 延迟归档

- 双份完整 SHA-256 校验移出 job 行锁；校验前后及最终事务内复核文件身份。
- 删除源仍在 job 行锁内，重新验证 owner/epoch、取消、published 阶段和清单一致性。目标必须已有持久化校验值。
- 删除源后提交前中断时保留 published 恢复依据；接管者重新验证目标再完成，不把缺失源直接视为成功。
- 文件系统 stat 与 unlink 不能组成原子事务；外部进程在这两个系统调用之间替换路径的极窄竞态仍是边界。目录 fsync 仍在删除临界区，真实慢盘尾延迟需要实测。

### 库存 missing RJ 维护

- 将全范围 SQL 正则改为锁外按主键有界读取目录候选，在 Python 提取 RJ；按 scope 与可见版本保留游标和无结果完成水位。
- 空候选批次仅复核读版本，不进入状态行写事务。确有候选时按 status、entry 顺序取锁，再核对 active generation、seq、revision 与 mask 可见性。
- 水位为有界的进程内状态，重启重新扫描；正常索引写入使水位失效，不提前暴露半成品。
- staging 合并按实际新增、更新和删除的合计量达到 5000 条才触发全表 ANALYZE/GIN 清理，不使用扫描总量判断；周期维护等待线程完成后再进入下一轮，保留跨进程维护 advisory 锁。
- 本批没有完成整个 reconcile 的统计/派生关联发布拆分；也没有取得生产 SQL 执行计划或 buffer 数据。

### 日统计

- UPSERT 改为 `activity_log_daily_stats.count + excluded.count`，保留 savepoint 隔离；聚合失败不回滚主日志。
- 新增 `backend/scripts/rebuild_activity_log_daily_stats.py`：默认只读核对，显式 `--apply` 才按绝对计数替换，重复执行不累加。
- 当前自动压缩仅裁 detail，不删除 activity_logs 事实；batch/session/task rollup 是可能重叠的展示投影，不再次相加。人工删除过的历史事实无法由此工具恢复。
- Writer 按日期获取共享事务 advisory lock，修复工具按相同顺序获取独占锁；修复后排队 Writer 正常增量，避免并发回填覆盖新记录。应用要求 READ COMMITTED。

在所有写入实例升级到包含共享锁的版本后，先核对目标闭区间日期，再按需应用。不要在新旧 Writer 混跑时并发回填。

```powershell
backend/venv/Scripts/python.exe backend/scripts/rebuild_activity_log_daily_stats.py --start 2026-10-12 --end 2026-10-17
backend/venv/Scripts/python.exe backend/scripts/rebuild_activity_log_daily_stats.py --start 2026-10-12 --end 2026-10-17 --apply
```

以上命令连接当前配置指向的数据库；本次未对生产执行。输出包含修复前/期望桶计数，不包含凭据。

### 社团后端

- 冷构建按规范化社团 ID 与版本合并，整体同时构建上限为 2；取消单个请求不会提前释放仍在工作的线程配额。
- 同步数据库、Redis 与作品计算离开事件循环；构建结束复查版本，失效期间产生的旧结果不写入新版本缓存。
- 筛选、排序、特典分组与汇总按 selection 缓存，翻页仅投影当前页并复制响应；metadata 候选使用 set 去重并保持原顺序。
- Redis 故障时使用实例独立命名域，恢复后补发失效版本，再复用共享缓存；释放构建租约使用 Lua 比较后删除。
- 每次版本读取通过一次 MGET 同时取得全局 epoch 与社团版本，保留状态获取前后的版本校验，减少重复 Redis 往返。
- 进程内同社团构建合并有并发回归；跨进程 Redis 争锁等待仍有上限，不能据此宣称跨实例严格单飞。线程隔离也不代表已经消除 CPU/GIL 竞争。

### 社团前端

- 路由目标优先加载，recent/libraries 不再形成作品首屏前置等待；迟到的 recent 不抢占当前目标。
- 外搜状态按 canonical key 独立保存，批次只合并变化，保留作品对象身份和取消/序号保护。
- 图片队列使用非深响应结构，RAF 合并状态发布，保持 8 并发并复用成功 URL；源 URL 变化重新排队。
- 移动 plain/桌面 virtual 与卡片/列表四分支均保留。

### 存储观测与日志轮转

- 新增手动只读 `GET /api/system/storage-observation?interval_seconds=1`，同步采样在线程池中执行；单进程同一时间只允许一份样本，采样间隔为 0.1–10 秒。
- 输出 PG 等待分布、WAL/checkpointer/bgwriter/IO、Redis persistence/fork、Linux 磁盘计数与 I/O pressure，以及现有资源预算和应用日志队列状态。各来源保留独立采样时间与实际间隔，不伪称原子快照。
- PG 使用独立短连接与连接/事务/语句超时，两次快照之间不持连接；Redis 使用诊断专用池、有限 socket 超时且不重试。输出字段白名单，不返回连接凭据、SQL 参数或查询正文。
- PG 18 的 `pg_stat_io` 按 backend_type/object/context 对齐累计差值；统计重置、Redis 实例变更或缺少基线时拒绝给出误导性增量。Windows 明确报告 Linux procfs 指标不可用。
- 修复应用日志备份数量为 0 时标准 handler 不截断、主日志继续增长的问题。默认 20MB、5 份备份保持现有配置；PG/Redis 守护进程日志轮转尚未修改。
- 复用既有归档和索引资源预算；前台请求触发后台动态让路及生产混合负载验收尚未完成。

### 百度预览取消

预览父协程取消时取消并等待所有子任务，包括信号量前排队的链接；保留现有总 deadline、单链接 deadline 和并发上限。同步 requests 在线程中已经发出的底层请求仍由其原有网络超时结束，不能把协程取消宣称为强制终止线程。HTTP 客户端断连是否触发上层协程取消需另行验收。

## 已完成验证

各模块使用独立 PostgreSQL 测试库和临时目录，避免 DROP/TRUNCATE 与其他代理互相干扰。

| 范围 | 结果 |
| --- | --- |
| 延迟归档 | 28 项通过；双连接验证哈希期间可 NOWAIT 取锁/续租，删除期间无法取得行锁 |
| runtime + ASMR + Redis | 首轮组合 68 项通过；补齐初始化期移动/删除场景后的 runtime 6 项单独通过，两个数量有重叠 |
| 日统计、日志服务、rollup、lite、aggregator、维护路由 | 91 项通过 |
| 百度服务与新增取消/deadline 场景 | 66 项通过 |
| HTTP 下载、百度账号接口、任务通知要求的补充回归 | 154 项通过 |
| 存储观测、应用日志与资源预算 | 24 项通过，包含真实本机 PG 18 只读短连接验证 |
| 社团前端定向回归 | 11 项通过 |
| 社团后端分页、特典及并发性能回归 | MGET 修改后最终 43 项通过，43.61 秒，退出码 0；覆盖构建期间循环推进、取消、失效、Redis 故障恢复与分页隔离 |
| 库存全部 6 份索引回归 | 91 项通过，包含 22 万条 staging 场景；639.17 秒 |
| 前端生产构建 | `npm --prefix frontend run build` 通过 |

旧日志回归中的 SQLite 建库和 sqlite_write 断言已改为 PostgreSQL 与 database_write；封面测试核对缺图先排队并返回 404、落地后返回 200，保持当前业务实现。

社团分页测试此前使用真实封面缓存并启动后台下载，会把外部 I/O 状态引入特典筛选断言。最终测试为每项分配独立临时封面目录并禁用该 fixture 的后台预热，保留原特典筛选断言；封面下载与确认缺图的独立测试继续执行。

定位时使用 CodeGraph，再核对当前源码；新增符号尚未全部进入索引，未重建图谱，不能把图谱调用关系当作全部改动的实时证明。

## 尚待验收与后续批次

- 固定 NAS/浏览器/数据集下的 100/1000/5000 作品、10/50/100 页大小、桌面/移动、明暗主题与后台混合负载矩阵。
- 浏览器滚动轨迹、组件更新次数、图片 decode/layout/paint、CPU/GIL profile；尚无可信线上 p95/p99 改善数字。
- NAS 同卷/跨卷、大文件、断电与真实慢盘 fsync；实际 PG blocker/wait_event、SQL 执行计划和 buffer。
- 重命名、扫描任务化、外部共享连接池和 HTTP 断连传播仍需分别实施/验证。
- 本文仅记录本批实际改动，不能把原有 fast-path、mask、dirty scope、下载进度或暗色样式列为新增成果。
