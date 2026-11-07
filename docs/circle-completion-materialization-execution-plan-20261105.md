# 社团补全性能优化执行计划

日期：2026-11-05。性质：实施前的代码与线上证据审查，不代表已经实现或部署。

## 1. 执行结论

采用 PostgreSQL 普通表维护社团补全读模型：事实变更与待处理记录同事务提交，后台按社团合并、按受影响作品及关联组更新，页面只做本地查询和当前页展示。保留现有筛选、特典归组、多语言作品、拥有状态和下载选择语义。不新增数据库、消息队列或搜索服务。

实施顺序固定为：失效归因与封面事件治理 → 可靠队列及读模型 → 全来源增量接入 → 完整读取接口与前端迁移 → 回填和灰度 → 退役旧投影。观测和新模型开发可以并行，不以“先等一天日志”作为开发前置条件。

沿用 GPT v4 与 Claude 完善稿的主干，但必须修正以下设计：

1. 时间变化统一由持久化到期调度发布新版本，不能同时使用静态摘要、按 revision 缓存，以及查询时临时修改时间布尔值。
2. 队列去重之外必须有社团单调序号、条件 ACK 和租约 fencing，避免处理中再次变更被删除、旧 worker 覆盖新结果。
3. 全量构建以一致快照和截点发布；不等待队列完全清空，避免持续变更使社团永久 building。
4. 普通图片缓存变化停止触发业务重算；特典封面结论参与剪枝和代表选择，结论变化仍必须传播。
5. 不只迁移 `/works`、`/summary`、`/work-codes`，还要迁移特典编号、RJ 定位及左侧统计的对应读取。
6. 发布通知使用 PostgreSQL outbox，复用现有 Redis/SSE 通道发送，不能把“提交后广播”视为可靠交付。

## 2. 当前线上证据与优先级

本次只读验证：SSH 主机名严格为 `Elena`；容器 `elena39-kikoerumanager` 为 running / healthy，镜像为 `elena39/kikoerumanager:hotfix-20261105-162746-a19a9a92a098`，启动时间为 2026-11-05 08:30:52 UTC。`docker top` 看到一个 `python -m app.main` 应用进程。跨实例租约属于正确性要求，不能把当前慢请求归因于多个应用 worker。

以下为本次重新读取 `/app/data/app.log` 保存的真实请求，时间按日志本地时间列出：

| 时间 | 请求 | HTTP 总耗时 | state | 投影行构建 | 投影批写 | commit | 字幕装饰 | 投影行数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16:46:05 | RG41088，缺失，列表，50 条 | 5203 ms | 1273 ms | 1755 ms | 718 ms | 89 ms | 51 ms | 1725 |
| 16:47:11 | RG41088，已拥有，列表，100 条 | 5354 ms | 1425 ms | 1771 ms | 881 ms | 280 ms | 51 ms | 1725 |
| 16:47:37 | RG41088，同上 | 5464 ms | 1410 ms | 1855 ms | 863 ms | 441 ms | 50 ms | 1725 |
| 16:46:39 | RG70169，缺失，列表，50 条 | 1609 ms | 426 ms | 541 ms | 198 ms | 182 ms | 27 ms | 605 |
| 16:47:19 / 42 | RG58328，已拥有，列表，100 条 | 1065 / 1053 ms | 540 / 488 ms | 164 / 164 ms | 75 / 68 ms | 96 / 137 ms | 10 / 10 ms | 171 |

这些阶段存在嵌套，不能全部相加。它们证明请求仍在承担整社团计算和持久化，而不是证明每一毫秒的 CPU、磁盘或数据库等待归因。

RG41088 的 16:46 请求还显示：advisory lock 等待约 0.98 ms，来源装饰 53 ms，当前页复制 52 ms，页缓存写入 45 ms，响应编码 12 ms，gzip 8 ms，547661 字节压缩为 24159 字节。因此优先移走整社团计算及重复 payload 写入；不先换序列化库、加数据库连接或调整 gzip。当前字幕约 50 ms，必须复用已上线的字幕目标摘要和路径索引，不再从零重做字幕优化。

GPT 原调查中投影记录的版本为 `v220 → v221 → v226`，该段资源版本及库存摘要未变化，说明这几次存在社团视图版本失效；本次重新确认了相应时间的慢请求，但没有重新执行那组数据库查询。失效调用方尚无日志证明，不能把封面事件风暴写成已经证实的事故原因。全库存摘要进入资源键是另外一个由代码确认的无关社团失效风险。

注意：旧投影 head 的 `row_count` 来自 `summary.total_works`，不能拿它与 1725 条变体行直接等同，也不能用 `1725 / 5` 推定真实作品实体数。慢请求日志有阈值，不能据此算总体 P95、均值或缓存命中率。

## 3. 当前代码决定的改动边界

| 已核对位置 | 当前行为 | 本次实施要求 |
| --- | --- | --- |
| `circle_completion_service.py::_completion_resource_version_tag` | 读取全部 `LibraryIndexStatus` 并参与资源版本摘要 | 新读路径删除该依赖；必须先接齐库存事件，不能直接删键 |
| `_list_circle_completion_works_sync` | 列表投影未命中时，构建完整 state、资源/字幕装饰、发布整社团投影，再分页 | 迁移后请求不得触发这些步骤；卡片也迁移，卡片当前虽不首次发布投影，仍有全量动态计算 |
| `circle_completion_projection.py::build_projection_rows` | list 与四个 card 变体，多次整集合 deepcopy，重复 payload | 实体 payload 一份，展示分组只存轻索引；不以按需生成旧变体作为最终架构 |
| `_build_completion_view_state_uncached` / `_completion_prune_bonus_items` | 特典封面事实参与剪枝与代表选择 | 保留业务结论；图片缓存和业务封面结论分开处理 |
| `_schedule_circle_cover_cache` / `invalidate_completion_cover_cache` / cover fetch route | 后台与接口都可能让整个社团失效 | 按结论差异入队，普通图片成功不抬业务版本 |
| `circle_subtitle_repair_service.py` | 已有持久化目标摘要、索引版本和批量路径查询 | 复用；保留每库存位置分别判定音频与字幕的语义 |
| `library_index/snapshot_store.py` | `_refresh_rj_entries_in_session` 已收集旧、新路径关联 RJ，事务内失效字幕目标 | 扩展这条提交链；不是重新发明库存全盘扫描 |
| `ResourceSourceService._save` / `flush_notifications` | 先 commit，500 ms 合并后失效缓存 | dirty 必须在同一 Session、同一事实事务内写；通知合并不能承担可靠性 |
| `list_circle_completion_work_codes` | 先构建 state，且可能异步补精确发售日和读取探测完成日期 | 编号查询改读模型；精确日期修复在后台持久化后再更新模型，保留特典操作需要的日期与完成态 |
| `locate_circle_completion_work` | 构建 state 后全量筛选、排序、归组、遍历定位 | 与列表共用同一 SQL 选择关系和顺序；定位子特典后返回父组所在页 |
| `search_circles` / `list_recent_indexes` | 左侧还有独立统计和 48 小时新作计算 | 名称发现和最近索引记录仍读 catalog，补全状态统计统一读已发布 head |
| `realtime_event_service.py::broadcast_event` | 写 Redis 后本地广播，异常只记录；不与业务数据库提交原子 | 新发布使用小型 PG outbox，再调用现有事件通道 |
| `CircleCompletion.vue` | API `items` 被映射为 `detail.works`，已有取消请求和刷新合并 | 保留实际响应字段，扩展 revision/status 和新事件，不照抄 `rows` 契约 |

## 4. 读模型结构

新增 Alembic 迁移和独立 repository / materializer 模块，避免继续把调度、SQL 和所有业务规则塞进现有大 service。建议模块：`circle_completion_read_model.py`、`circle_completion_materializer.py`、`circle_completion_change_service.py`。名称在实现时统一，职责不混用。

| 表 / 职责 | 关键字段与约束 |
| --- | --- |
| `circle_completion_heads`，已发布状态 | `circle_id` 主键；`active_generation`、单调 `revision`、`applied_seq`、`as_of`、`next_transition_at`、基础统计/变体统计、语义摘要、发布时间 |
| `circle_completion_controls`，调度状态 | `circle_id` 主键；`requested_seq`、`full_requested_seq`、`lease_token`、`lease_until`、`attempts`、`next_retry_at`、`last_error`；与展示 revision 分离 |
| `circle_completion_work_states`，作品实体 | 物理主键 `(circle_id, generation, canonical_rjcode)`；一份 payload、独立 compare_payload；拥有、来源、字幕、特典、新作、发售、搜索与排序用轻列 |
| `circle_completion_work_aliases`，反向映射 | generation 下原始/展示/已验证关联 RJ → canonical、社团；支持变更定位、编号查询和跨社团影响查找 |
| `circle_completion_groups`，展示单元 | `(circle_id, generation, variant, group_key)`；根实体键、排序键、组级检索信息/标签；不存完整实体 payload |
| `circle_completion_group_members`，成员映射 | 组键、canonical、成员顺序、展示角色；支持父子与多个展示成员，禁止用全列表 position 作为实体身份 |
| `circle_completion_cover_facts`，参与业务的封面结论 | RJ 主键；card/list 各自验证结论、合成结论、检查时间及待完成验证标记；只覆盖参与特典业务判断的作品，图片字节仍存现有目录 |
| `circle_completion_dirty`，合并变更 | `(circle_id, source_rjcode)` 主键；`last_seq`、reasons、首次/最近入队时间；全量请求记在 controls，不依赖虚构 RJ |
| `circle_completion_publish_outbox`，发布通知 | `(circle_id, revision)` 唯一；event_id、payload、发送状态/重试时间；不保存完整作品数据 |

`canonical_rjcode` 是业务归一键，并非永远不变的身份。归一关系重挂时删除旧实体键及索引、插入新键，并处理两边关联组；可保留源 `CircleWork.id` 用于追踪。生产关系事实只接受现有 verified canonical evidence；不能凭标题、语言或封面相似合并创作者自行发布的多语言原作。

全量重建产生新 generation；增量只更新当前 generation 的受影响实体及组。旧 generation 异步分批清理，保留量和清理间隔有上限。禁止对每次单作品变化复制一整代数据。

首次保留主键、外键所需索引、RJ 反向映射、现有搜索/标签所需的 trigram 与 GIN；常用排序索引根据实际 `EXPLAIN (ANALYZE, BUFFERS)` 加。轻列必须足以完成统计，不重新取出全体 JSON 跑 Python 摘要。

基础 summary 在发布事务中聚合，与实体及 revision 一起提交。`filtered_count`、当前筛选下被覆盖的 `missing_count`、分组后的 `total` / `page_count` 属于查询结果，按现有语义从轻列/分组关系计算，不能拿静态 head summary 覆盖所有查询。`include_dl_only` 等影响摘要的参数必须有对应聚合口径。

## 5. 变更协议：同事务、不丢更新、不让旧 worker 发布

### 5.1 事实事务

所有事实写入采用 `enqueue_in_session(db, circle_ids, source_rjcodes, reason)`，这个函数不能自己 commit，也不能从提交后的 SSE 反向推断事实。

同一事务内：写事实 → 确定变更前后受影响社团/RJ → 按 circle_id 固定顺序锁定 controls → 每个社团将 `requested_seq` 加一 → upsert dirty.last_seq 与 reasons → 一起提交。批量写入每社团每事务只申请一次序号，禁止逐文件加一次。固定锁顺序避免跨社团事务互锁，不在持锁时做网络或全量计算。

使用社团行上事务内递增的序号，不能仅使用全局 sequence 的 `max(id)` 作为已提交截点，因为序号分配顺序不等于事务提交顺序。

### 5.2 worker

1. 用短事务 `FOR UPDATE SKIP LOCKED` 领取社团控制行，增加 fencing token，设租约后提交。默认只有一个后台构建 worker，不在查询线程计算；租约按社团，不按 RJ 并发争抢同一社团。
2. 在 PostgreSQL 一致的 `REPEATABLE READ` 源快照里读取本次 `captured_seq`、dirty 和业务事实，固定 `as_of`。不得混用多个 READ COMMITTED 查询或不同版本 Redis 事实拼成所谓一致快照。现有构建器需要改成可接受 Session/预取事实的纯计算步骤，不能直接原样调用会自行开 Session 的整套读 service。
3. 增量集合由旧已发布关系和新事实共同扩展：变化 RJ、归一关联、特典父子、代表选择组，以及关系解除前的成员。先求闭包，再只加载这些实体。反向映射必须查出所有社团，不能取第一个匹配；解除关系前需记录旧社团/旧键。
4. 计算在数据库写事务外完成；源快照事务有超时和规模边界，不能在其中抓 DLsite、扫描文件或等待图片下载。全量可在读快照期间向隔离 generation 分批写 staging，但保持源数据同一快照。
5. 发布短事务锁 controls，验证当前 token、有效租约和预期 active_generation / revision；检查不通过则放弃结果。更新实体、alias、受影响 groups/members、轻列汇总、head revision/as_of、下一个时间到期点、outbox，并条件 ACK。
6. ACK 只删除 `last_seq <= captured_seq` 的 dirty；较大序号必须保留。设置 applied_seq 至本次截点。即使处理中有新变更，也可发布本次一致结果并标 stale，随后继续追赶。不能要求 requested_seq 没变化才永远重试。
7. 没有展示/摘要语义差异时只推进处理截点和调度状态，不增加展示 revision，不发送无效页面刷新。

失败保留最后发布数据及待处理项，指数退避并暴露错误。超限进入 failed，不能删除任务；新的事实变更或显式重试可以重新调度。worker 关闭时停止领取，完成或回滚当前短发布事务，未完成租约可由后续实例回收。

### 5.3 全量切换

全量使用同一个社团租约，与该社团增量互斥。捕获源快照及 `captured_seq = S`，生成独立 generation；短发布事务一次切换 active_generation、summary、revision、applied_seq=S，保留 `last_seq>S` 的记录，然后增量追赶。

发布的含义是“完整代表源快照 S”，并不宣称“发布瞬间已处理所有新事实”。这使持续下载、资源探测和封面结论更新期间仍可完成切换。失败时当前 generation 不受影响；遗留 staging 按失效租约清理。

## 6. 事实来源接入表

| 来源 | 同事务接点与影响范围 | 禁止行为 |
| --- | --- | --- |
| CircleWork、目录索引、owned / canonical links、metadata | 各自事实写 Session；记录旧键、新键、旧/新社团；catalog 创建/删除/重命名同步维护 head/目录版本 | 只在 API 返回后通知，或只更新新 canonical |
| 库存普通增删移动 | `snapshot_store` 更新派生 RJ entries 与可见索引提交链；复用已有旧/新路径收集，扩展到所有会影响补全的原作/特典及 alias | 遍历整库、把所有社团标 dirty、仅匹配新文件名 RJ |
| 库存 generation 切换、库启停、可写配置变化 | 在可见索引代切换事务中保存旧/新受影响 RJ 或持久化扩展任务；后台按 RJ 与社团映射分批入队 | 先删全库存版本哈希，却没有替代通知；未可见索引就发布 owned |
| 字幕 | 复用现有 target snapshot 失效与重算；目标摘要实际提交后通知对应 RJ。索引无效阶段保留 pending 语义，不能把未知当无字幕 | 重新扫文件系统；用一个全局字幕布尔值覆盖多个库存位置 |
| 资源来源 | `ResourceSourceService._save` 同事务写 dirty，保留已有 500 ms 通知兼容层 | 用 timer 内存通知替代持久化变更 |
| 下载、解压、上传、入库 | 下载会话/真实 owned 记录提交时入队；文件位置状态以可见库存索引提交为准 | 按每个进度回调入队；仅因任务 completed 就声明索引已经收录 |
| 特典命中、无特典结论、父子关系、删除无封面特典 | 对应事实提交处写 dirty，包含受影响原作/特典与旧组 | 改日期 worker、range lease 或把失败写成 no_bonus |
| 精确发售日修复 | 官方日期修复完成后持久化 WorkMetadata，并在同事务传播变更 | 编号 GET 请求等待远端补日期；吞掉待修复状态 |
| 封面业务结论 | available / missing / unknown 的有效结论发生变化才入队；既有 DB 删除逻辑也要接入 | 普通 JPG 写磁盘或文件 mtime 变化就重建整个社团；403/429/超时写 missing |
| 时间到期 | 见下一节；到期调度在数据库内记 dirty | 依赖用户打开页面或全局日期缓存键 |

文件系统落盘和 PostgreSQL 不可能天然属于同一事务。这里保证的是“已接受且可见的索引/字幕摘要事实”和 dirty 原子；不能以任务结束通知跨越这个边界。封面如以文件缓存保存事实，需要先由验证任务落持久化业务结论/待处理记录，文件扫描本身不能充当可靠队列。

特典探测另有现存边界：`_upsert_cache_features_sync` 经 Redis dirty buffer 延迟写 PostgreSQL，`flush_bonus_probe_cache_dirty_once` 当前异常分支也会 ACK。新模型的事实提交点应是相应 PG upsert/作品级结论提交，而非 Redis 写成功；会影响展示的字段在该 PG Session 同写 dirty，只映射确有关联的社团，不能让批量候选缓存逐条唤醒全部社团。若这些消息承担模型事实传播，瞬态数据库失败必须保留重试，非法消息单独隔离；不能复用当前“失败也 ACK”分支作为可靠队列。探测扫描算法及候选调度不因本次重写。

最终逐个审计现有 `invalidate_completion_view_cache` 和 resource/cover invalidation 调用点，做“调用位置 → 事实事务 → reason → RJ/社团范围 → 回归用例”的清单。能够识别范围的必须增量；确实为整体规则或索引版本变化的才发全量请求，不能用所有未知调用都全量的方式结束迁移。

## 7. 时间与封面事件的具体决策

### 时间

保留邮件来源、专用 `email_watcher_first_seen_at`、release_date 等原始字段。沿用当前业务时区/48 小时边界语义，测试固定时钟覆盖首次出现、满 48 小时前后、跨午夜、模糊日期补全及时间回拨；不得用 updated_at 替代新作锚点。

发布时为相关作品计算下一个语义转换时间（新作窗口进入/退出、发售日转换等），head 保存最近 `next_transition_at`。后台按到期索引调度，事务内再次核对 head/revision，入队 reason=time；重启重新读取过期项，同一时间事件幂等。到期后全部受影响字段、tags、分组、统计一起发布新 revision。

到期已发生但 worker 尚未完成时，读取返回 stale，不能声称 ready 且时间字段绝对实时。建议时间调度 tick 1 秒，正常负载到期发布 P95 目标不超过 2 秒；这是待验收目标，不是已有测量结果。移除 `d{today}` 全局版本键后，缓存只依赖已发布 revision，状态字段单独读取，不缓存 pending 状态。

### 封面

普通封面下载成功且业务字段无变化：不进业务 dirty、不增加 revision，图片组件按原路径刷新。特典 unknown → confirmed available/missing 等影响剪枝或代表选择的结论变化：持久化后进 dirty，重新计算相关父子组。

现有 `cover_facts()` 来自图片目录名和 `.missing` 文件，不是 PG 事实。因此新增的封面事实表不是重复保存图片，而是使后台可在一致源快照中读取业务结论。合成规则保持当前语义：card/list 任一确认有图即 available，两者都确认 missing 才是 missing，其余 unknown。首次回填由后台从既有缓存导入，读取 API 不再 `refresh=True` 扫目录。

对参与业务的特典验证，在执行文件变更前持久化待完成检查标记，成功落盘/写 marker 后，同事务更新封面结论、清标记并 enqueue；中途退出由后台恢复待完成检查。缓存删除、强制重取及 marker 清理也必须经过这个结论更新入口。这样既不要求文件与 PG 伪原子，也不会因进程退出永久漏掉剪枝变化；普通图片下载不增加这套业务写入。

默认按社团静默窗口 500 ms 合并，首次入队后最多等待 2 秒即处理，防止持续事件无限推迟。单批 50 张图的验收分两种：普通图片缓存成功应为零次业务发布；同一窗口内 50 个有效特典结论合并处理。跨窗口持续到达可有多批，不能承诺“永远只发布一次”。

## 8. 全部读取与前端契约

### 查询

`/works` 使用单条 SQL 的 CTE：读 head/control → 选择 variant 与筛选关系 → 计数及稳定排序 → 计算合法页码 → 取当前页 group → join 当前页成员和实体 payload。排序必须加稳定 RJ/group tie-breaker。空页也返回 head、summary 和 total；保留现有请求超出末页时的页码收缩行为。

PostgreSQL 单语句快照保证返回的数据和 revision 一致，不加 `FOR SHARE` 读锁，不在开头/结尾重复读版本。行锁仅用于写入/调度协议。卡片归组、列表父子与比较页不能共用错误的 total 口径；动态筛选可能改变代表或成员时，在轻索引关系上还原现有筛选/归组顺序，再只读当前页 payload。不能简单用组 tags 的 OR/AND 代替现有作品级条件。

`/summary` 读 head 基础统计和所需轻量变体聚合；`/work-codes`、`/bonus-work-codes` 只取编号及动作需要的轻字段；`/work-location` 与分页使用相同选择关系，通过窗口行号找页，不读全社团 payload。编号操作仍保留 selected 原作、精确日期、已完成探测日期及可下载实际 RJ 的契约。

精确日期尚未知时返回明确 pending；已有后台元数据补全任务负责获取。需要精确日期的特典探测动作等待该任务完成再启动，不能以缺日期静默漏扫，也不能让普通 GET 隐式发远端请求。

左侧 `/circles`、recent 的名称/最近访问或索引记录保留原目录职责；新作、拥有等补全统计 JOIN 已发布 head。详情旧接口仍有调用者时同样拆出读模型入口，不能留隐藏的全量构建路径。

新路径初始关闭整页 Redis JSON 缓存，保留 PostgreSQL 分页。需要缓存时必须实测证明有净收益，键为 `(schema_version, circle_id, generation, revision, normalized_query)`。读到 key 后再查数据的缓存策略必须保证只存对应版本的数据，不能用先读版本 A、后查出版本 B 的结果写 A 键。任何响应内 pending/status 不随旧页缓存冻结。

### 响应与交互

保留现有 `success`、`items`、顶层 summary 字段、`total/page/page_size/page_count` 和 `data_version`。新增 `materialization_status`、`revision`、`pending_changes`、`as_of`，避免复用容易与业务状态混淆的字段。`data_version` 在新路径稳定映射到 generation/revision，不再混入全库存摘要。

| 状态 | 有无已发布数据 | 页面行为 |
| --- | --- | --- |
| ready | 有，且已追平/未到期 | 正常显示 |
| stale | 有，存在待处理或已到期事件 | 保留当前作品，轻量更新提示 |
| building | 无 | HTTP 200、`items: []`、summary 明确未就绪，显示准备中，禁止当成“没有作品”或可执行空批次 |
| failed | 可能有 | 有数据则保留并提示更新失败；无数据则显示准备失败和重试入口 |

未初始化社团的读取只做幂等的高优先级 build 请求并立即返回，不等待构建。首次准备响应快，不等于首次数据已经在 200 ms 内准备好；上线前回填才减少真实等待。

发布事务同写 outbox；发送器提交后调用现有 `broadcast_event`，失败重试，允许重复。事件使用 `circle.completion.changed`，带 circle_id、revision/as_of、reason 和有上限的 RJ 摘要。发送成功后、ACK 前退出可能重发，前端按 revision 去重。

`CircleCompletion.vue` 保留现有 AbortController/request sequence，加入社团、查询签名及 revision 防护；合并事件刷新，收到更高版本且当前请求进行中时保留刷新需求。保持 tab、筛选、页码与滚动锚点；页码失效时按服务端收缩。新旧版本跨页时重新读取当前视图，旧响应不能覆盖新结果。

SSE 重连、页面恢复可见时核对当前社团 revision；building/stale 使用有上限的退避查询。ready 页面只在可见且需要校验时做低频轻量 revision 检查，处理客户端掉队/Redis 流裁剪；不恢复高频全页轮询。

## 9. 工作批次与退出条件

| 批次 | 可审阅的实际交付 | 完成条件 |
| --- | --- | --- |
| A：归因与事件治理 | 失效 API 增加明确 reason/source/RJ；封面业务结论去重；补构建内部计时；全量请求耗时直方图或无偏样本 | 能区分版本涨因；普通封面不引起业务版本变化；不破坏特典剪枝；已有字幕增量保持有效 |
| B：存储和发布协议 | 迁移、repository、dirty 同事务 API、lease/fencing、全量/增量 worker、time scheduler、outbox；读开关关闭 | 并发/崩溃/切代测试通过；队列不丢变更；没有半份发布 |
| C：来源与查询 | 完成全部来源接入清单；实体/关联组局部计算；所有读取端点及左侧统计迁移；前端状态和事件处理 | 新路径无远端请求、文件扫描和全量构建；固定快照新旧字段/顺序/数量一致 |
| D：完整发布、回填和灰度 | 完整镜像包含后端迁移及前端兼容；开关默认关闭；最近访问→较大社团→其余社团回填，单 worker 限速 | 回填进度可见；指定社团 ready；生产身份、迁移与健康确认后才开白名单 |
| E：扩大并退役 | 通过真实事件与性能矩阵后扩大白名单；后续独立迁移删除旧投影和旧版本键 | 实际库存变化、下载入库、资源、字幕、特典、时间到期均验收；对账零差异；回退窗口结束 |

批次 A 不同步优化旧架构全部 deepcopy 或另造按需变体系统，以免重复工程；仅处理明确无业务变化的失效和观测。B/C 开发不等待 A 收集满一天。代码审阅可按以上职责分批，提交必须另按用户授权执行。

在 `routes.py::startup_event` / `shutdown_event` 同步接入 worker 生命周期，复用现有资源预算服务并增加专用物化写维度。专用维度不是 CPU/磁盘隔离：初始全量 worker=1，限制单批行数、事务时长和 staging 清理；记录数据库池等待、WAL/事务耗时、积压和应用 loop 延迟。计算在线程执行但不宣称线程能隔离 GIL；如果背景构建影响读取 P95，先降低批次/并发并剖析，不能靠增加线程掩盖。

灰度使用运行时可改的模式配置和社团白名单，并维护配置模板、读写 API 和前端设置所需兼容。首批 RG41088、RG70169、RG58328 加一个经统计选出的特典密集社团。各社团只选择一条对外读路径；影子计算按低频抽样执行，不在每次 GET 双算。

新路径启用期间继续维护旧路径的失效标记，保证关开关不会读出积存旧缓存；不因此双写五份旧投影。回退开关可以临时恢复旧性能，但数据仍正确。新表保留以便修正后继续灰度；旧表删除放后续版本。

切回旧路径的配置处理还必须提升旧缓存 epoch / 清理对应 scope，使回退后的首读基于当前事实重建，覆盖中间期间未送达的旧失效通知；这次重建允许恢复旧延迟，但不能读旧投影冒充最新结果。

## 10. 验收与基准

所有目标是发布门槛，未执行前不写成已达成。新旧对照使用同一事实快照、相同 as_of、相同规则版本；旧基准使用无缓存纯构建，不复用可能同样陈旧的选择缓存。时间字段也必须精确一致，不能列为可随意忽略的差异。

| 类别 | 必须覆盖 | 判据 |
| --- | --- | --- |
| 原有语义 | 缺失/已拥有/比较；卡片/列表；include_dl_only；单项和组合筛选；排序/搜索；第二页/末页/空结果；定位父子特典；批量编号 | 字段、类型、顺序、分组、摘要和动作编号逐项一致；保留多语言原作和每位置字幕语义 |
| 稳定读性能 | RG41088、RG70169、RG58328、最大社团；page_size=50/100；典型搜索和排序；C1/C4 并发；正常下载背景 | 完整 HTTP 含 gzip 的 P95 ≤200 ms；无整页缓存时也测；每个报告矩阵单元至少 200 次，关键大社团 500 次，报告 P50/P95/P99、错误率和样本数 |
| 真正移出请求 | 稳定 GET、冷页参数、清空页缓存后的 GET | state 全构建、publish_projection、全目录扫描、远端请求次数均为 0；payload 读取规模只含当前页组及必要成员 |
| 更新时效 | 资源、字幕摘要、可见库存提交、owned、特典、时间变化分别测 | 初始工程目标：普通局部更新提交→发布 P95 ≤2 秒、提交→页面显示 P95 ≤3 秒（已连接可见页、无积压）；全量/积压单独报告，不混进稳定读 |
| 构建成本 | 三个样本社团和最大社团的首次/重建 | 报告总时长、实体行/轻索引行、payload 写字节、锁占用；相同快照与旧投影对比，不以转后台就宣称构建已加速 |
| 队列不丢更新 | 计算中同 RJ 再次变化、跨社团关联重挂、回滚、租约到期、旧 worker 复活 | 新序号保留、回滚不产生孤立 dirty、旧 token 无法发布 |
| 全量原子性 | staging 中途退出、连续变更、切换前后读、generation 清理 | 只见完整旧代或完整新代；持续变更不阻止全量发布，发布后追赶保留 |
| 时间正确 | 48h 前后、午夜、模糊发售日修复、停机跨过到期、时钟回拨 | tags、筛选、排序、摘要、列表一起变更，无永久陈旧 |
| 封面事件 | 普通封面 50 次写入；有效特典结论集中/跨窗口变化 | 前者业务发布为 0；后者按合并批次处理且最终等价，失败状态不误判 missing |
| 精确传播 | A 社团作品库存变化，无关联 B；generation 切换/库配置变化 | B revision 不变；有真实关联的所有社团更新；全库切代覆盖完整受影响集合 |
| 通知可靠 | 发布后发送前退出、发送后 ACK 前退出、Redis 短时失败、SSE 重连 | 最终可获新 revision；重复事件不反复刷新，准备中不会永远空白 |
| 背景负载 | 回填与正常下载/列表共存 | 无请求线程排队恶化、连接耗尽或持续增长的队列；最老项年龄和失败社团可见 |

复用现有 `test_circle_completion_paged_view.py`、`test_circle_completion_bonus_grouping.py`、字幕摘要及前端列表/视口测试，新增事务级 PostgreSQL 并发测试与有意义的故障注入；纯 mock 无法证明快照、条件 ACK 或 fencing 正确。

开发环境使用生产规模的脱敏数据或等价数据集做压力矩阵。线上依靠正常使用的无偏观测及获授权的真实功能验收；本次计划不授权生产压测或制造下载/删除任务。

低优先级对账以固定 source watermark/as_of 独立重建，对比实体、alias、组/成员、查询统计和序列化契约。发现差异记录具体 RJ/字段，按代码缺陷追查漏接或范围错误；不能长期依赖周期全量重刷维持正确性。稳定后的对账频率与批量有预算上限。

## 11. 发布约束与完成定义

新增表/迁移必须走 `tools/deploy-production-build.ps1` 完整镜像流程，不能用文件热补丁或 local-build 绕过。当前生产是 hotfix 镜像，不从镜像字符串猜 BaseTag；实施发布时读取实际基线、部署 manifest 和源码差异，保留并纳入已上线字幕迁移及其它并发改动。

批次 A 若独立发布且确实只有现有运行依赖内的 Python 改动，可使用仓库允许的多文件 local-build 流程，但必须重新核实生产基线；也可随完整镜像发布，不额外制造一次重启。新前端必须在白名单开启前随镜像可用。

发布前完成 diff 审查、迁移顺序/兼容验证、所需镜像构建和恢复方案；若基础镜像无法获取，停止切换，不直接修改运行容器表结构。发布仍遵守任务处理状态、生产身份、可恢复备份及保留最近三版等既有门禁。健康检查只证明存活，不替代回填、读取和真实变更验收。

最终完成条件：所有补全 GET 不再构建整社团；事实变更可靠增量传播；当前/跨页口径一致；完整性能矩阵达到门槛；真实业务事件和故障测试通过；更新 `docs/circle-completion-performance.md` 与 AGENTS 6.5，把“必须失效缓存”改成新的同事务变更协议；回退窗口后删除旧投影链。

实施中：本地已新增读模型迁移、事务内变更队列、后台物化和发布通知，并接入前端读取。库存索引变更已在同一事务按受影响 RJ 通知社团。真实 PostgreSQL 局部回归和前端构建已通过；分页、下载预览和旧缓存语义仍有回归失败需要逐项确认。库存配置变更传播、完整迁移演练、故障对账和生产规模性能矩阵尚未验收。未提交、未部署、未修改线上数据；不能视为发布完成。

## 12. 证据索引

- GPT 调查会话：`01a1a5b2-897d-7663-8fd7-a232b4d72be5`，含 v4 计划与上一轮线上投影版本调查。
- Claude 附件：`C:/Users/Elena/.codex/attachments/83b61c58-bf8b-40dd-b07c-71c8824f0fc2/已粘贴的文本.txt`。
- 本次重新读取的业务日志：`temp/circle-plan-app-evidence-20261105.log` 第 55–60 行；容器 stdout 另存 `temp/circle-plan-production-20261105.log`，stdout 访问记录不用于推定阶段耗时。
- 核心源码：`backend/app/core/circle_completion_service.py`（版本 402/423、失效 722、剪枝 2240、state 2961、summary 3085、分页 3342、编号 3532、定位 3810、封面 7540 附近、社团搜索 8948）；`circle_completion_projection.py`（构建 31、发布 78、查询 137）。行号为本次工作区快照，后续编辑可能移动。
- 已有索引：`backend/app/core/library_index/snapshot_store.py`（事务 638、RJ/字幕失效 906–1052）；`circle_subtitle_repair_service.py`（目标摘要 71、索引位置 155）；`resource_source_service.py`（保存 313、通知 344）。
- 前端与事件：`frontend/src/views/CircleCompletion.vue`（响应 items 映射 1957、事件 4580）；`backend/app/core/realtime_event_service.py`（广播 52）；`backend/app/api/routes.py`（启动 2641、停止 2775、读取路由 20952 起）。
