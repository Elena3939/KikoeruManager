"""临时脚本：验证 lite + compact estimate。用完可删。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 让 backend 模块入口可用
import backend.app.core.activity_log_lite as lite_mod
import backend.app.core.activity_log_compactor as comp_mod

# 1) lite 一条数据
sample_row = {
    "id": "x1",
    "category": "asmr_sync",
    "action": "session_completed",
    "status": "success",
    "summary": "上传 12 个文件 / 3.2 GB / 平均 5 MB/s / 耗时 10m30s",
    "rjcode": "RJ123456",
    "task_id": "tid",
    "source_path": "/foo",
    "created_at": "2025-12-01T01:02:03",
    "batch_id": None,
    "session_key": "sess",
    "parent_id": None,
    "detail": {
        "success_count": 12,
        "failed_count": 0,
        "uploaded_count": 12,
        "uploaded_bytes": 3 * 1024**3 + 200 * 1024**2,
        "duration_ms": 10 * 60 * 1000 + 30 * 1000,
        "uploaded_files": [{"name": f"f{i}.wav"} for i in range(50)],
        "session_id": "sess",
    },
}
print("== lite item ==")
import json

print(json.dumps(lite_mod.build_lite_item(sample_row), ensure_ascii=False, indent=2))

# 2) estimate 一下数据库
print("\n== estimate ==")
print(json.dumps(comp_mod.estimate_compact_savings(older_than_days=30, sample_limit=200), ensure_ascii=False, indent=2))
