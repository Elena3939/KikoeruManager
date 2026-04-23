"""activity_log_aggregator 包入口。

对外仍然提供 ``from app.core.activity_log_aggregator import merge_activity_rows``
的 import 路径，内部实际按 Phase 4B 第 4 步拆分成：
- ``_helpers``：纯辅助函数
- ``_main``：orchestrator（主流程 pass 顺序）

未来的 per-domain 拆分（Phase 5+）也会在本包里逐步新增：
- ``domain_subtitle``
- ``domain_import_batch``
- ``domain_rename``
- ``domain_delete``
- ``domain_filter_delete``
- ``domain_circle``
- ``domain_asmr``
"""
from ._main import merge_activity_rows, merge_activity_rows_from_dicts

__all__ = ["merge_activity_rows", "merge_activity_rows_from_dicts"]
