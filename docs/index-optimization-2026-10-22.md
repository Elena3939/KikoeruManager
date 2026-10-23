# 17:19 索引堵塞的优化方案与实现

## 已定位的问题

事故证据见 `production-index-incident-2026-10-22-1719.md`。目录未丢失；改名后路径已更新，但索引 RJ 字段仍保留旧号。目录统计查询对 `parent_path` 使用 `COALESCE`，无法直接利用现有父目录联合索引；快路径超时未记入账本，导致同一序号不断回滚重试。同期慢提交与 I/O 等待另有存储因素，底层原因尚未确认。

## 优化顺序与落地范围

1. **减少查询候选行**：定点目录统计采用裸 `parent_path` 等值查询；非空子树采用裸列范围查询。根目录单独生成 `NULL / 空串` 兼容谓词，避免通用预编译计划受带参数 OR 条件干扰。全 generation 聚合中的 `COALESCE` 分组保持原语义，不新增数据库索引或迁移。
2. **保证改名后的搜索正确性**：同库单条 UPDATE、跨库 INSERT SELECT 和 Python 路径转换都按新名称、新相对路径、新绝对路径的顺序重算 RJ。SQL 与 Python 使用共享正则。去号会清除继承的旧号，文件名自身的独立作品号保留。派生 RJ 表继续由原事务同步，移动不触发目录重扫。
3. **抑制回滚重试放大**：同库快路径超时回滚后调用既有失败账本机制，记录次数、错误和下次执行时间；跨库回滚后重新取得各库队头租约，再按围栏记录退避。仍按连续序号推进，不跳过事件、不提前删除 pending masks；达到既有 10 次上限时显式 blocked，可用既有重试入口恢复。保留 auto_circle_group 分块检查点和原有慢扫描暂态超时策略。
4. **隔离主循环等待**：单条和批量重命名的库定义读取、目录类型检查、prepare、filesystem_started、finalize、失败补偿、审计写入均移入线程，保留原执行顺序和响应字段。

## 验证与边界

- 使用本机 PostgreSQL 测试库；新增同库/跨库改号、去号、独立 RJ、派生搜索、根目录 NULL 父路径回归。
- 超时注入发生在执行写操作之后，验证整笔回滚、遮罩保留、账本退避以及恢复后完成；跨库验证两库账本和数据原子性。
- 单条/批量改名在线程中模拟数据库等待，验证事件循环仍能运行并解除等待。
- 首轮索引全套与浏览 API：141 通过、2 失败。失败为 `test_local_inventory_reads_prefer_usable_index_snapshot`（删除后测试期待立即入账，与当前排队行为不一致）和 `test_index_replace_many_records_one_ledger_envelope`（手工构造的 LibraryManager 缺少 `_index_mutation_pending_replaces`）。二者位于已有工作区改动的相关测试/服务；本任务未修改 LibraryManager，不扩大到其它业务改动。
- 最终执行索引全套、浏览 API 与新增线程边界测试：**145 通过、2 失败，83.80 秒**；失败仍为上述两项。所有库存索引测试与本次新增回归均通过，`py_compile`、`git diff --check` 通过。详细日志保存在忽略目录 `.codex/index-optimization-final.log`。
- 仓库要求的 `test_library_manager_index_integration.py` 当前不存在，已执行实际存在的 `test_library_index_*.py`。
- 修改后已重新查询 CodeGraph 反向调用：移动入口、mutation service 与 generation/self_mutation/mutation/browser 测试均纳入验证。图谱未随本次源码更新，关系为修改前快照，不能代表最新调用图。

## 生产应用边界

本次仅本地实现和验证，未部署、未重启、未修改生产数据。生产两个已存在的旧 RJ 字段不会被本地修复自动纠正；发布后需通过既有 mutation/reconcile 链路针对两个目录纠正，并核对新旧号搜索、派生 RJ 表、目录统计、水位和遮罩。无需全库重建。

当前没有生产修复后的耗时数据，不将事故中的 EXPLAIN 估计成本比例宣称为实际性能提升倍数。上线后应对比目录统计执行时间、statement timeout 次数、队头等待、水位差及 COMMIT 延迟；底层慢提交仍需独立查明。
