# activity_log_aggregator 快照 fixture

每个 scenario 由两个文件构成：

- `<name>.input.json`：原始 ActivityLog 行 dict 列表（to_dict 结果），按 `created_at` 倒序排列（和生产查询一致）
- `<name>.expected.json`：`merge_activity_rows` 在该输入上的输出（合并后供前端消费的 items）

测试运行方式：

```bash
# 普通回归（对比 expected）
pytest tests/test_activity_log_aggregator.py

# 首次添加 scenario 或故意更新基准时
UPDATE_SNAPSHOTS=1 pytest tests/test_activity_log_aggregator.py
```

在 PowerShell 上：

```powershell
$env:UPDATE_SNAPSHOTS = "1"; pytest tests/test_activity_log_aggregator.py; Remove-Item Env:UPDATE_SNAPSHOTS
```

## 添加新 scenario

1. 在本目录新增 `<name>.input.json`
2. 用 `UPDATE_SNAPSHOTS=1` 跑一次测试生成 `<name>.expected.json`
3. 人工检查 expected 是否符合预期，commit 两个文件
4. 后续改动算法如果合理地改了输出，再次用 `UPDATE_SNAPSHOTS=1` 更新基准，并在 PR 描述里说明 diff 原因

## 覆盖目标

Phase 4B 目标是在逐 domain 拆分 aggregator 之前把每个分支都用 fixture 钉死：

- [x] `smoke_empty`
- [x] `smoke_single_rename`
- [x] `auto_import_batch`
- [x] `subtitle_crawl_batch`
- [x] `filter_delete_batch`
- [x] `subtitle_pair_session`
- [x] `circle_completion_session`
- [x] `asmr_sync_session`
- [x] `process_existing_batch`
- [x] `mixed_categories`

所有主要 domain 均已在快照里钉死当前行为。后续按 domain 拆 aggregator 子模块时，每迁一个 domain 跑一次 `pytest tests/test_activity_log_aggregator.py` 即可字节级验证无回归。

## 历史遗留 bug 修复记录

- **synthetic auto_import / process_existing batch 曾经被静默丢弃**（Phase 4B 后置修复）：
  aggregator 对没有真实 `batch_start` 锚点但有 `batch_id` 的 import 行会构造 synthetic
  父行，但原本"append 到 rows"那一行被错写进了 delete batch loop 里，`category_key`
  是从前一 loop 泄漏的残留变量，条件永远不匹配；子行又已被加入
  `merged_import_batch_child_ids`，所以整个批次在输出里彻底消失。修复方式：把 append
  移回 import batch loop 的 `if child_rows:` 块末尾，并刷新 `auto_import_batch.expected.json`
  基准（由 `[]` 变为完整 synthetic batch + 3 子行）。

