"""扫描 backend/app 下所有 db = SessionLocal() 块中是否存在跨越 await 的长事务。

输出格式：
  <file>:<line>  await_in_session=N  rows=R  <function_name>
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "app"

SESSION_OPEN_RE = re.compile(r"^(\s*)(?:db|session)\s*=\s*(?:SessionLocal\(\)|next\(get_db\(\)\))")
CLOSE_RE = re.compile(r"^\s*(?:db|session)\.close\(\)")
COMMIT_RE = re.compile(r"^\s*(?:db|session)\.commit\(\)")
AWAIT_RE = re.compile(r"\bawait\s+")

# 对哪些文件优先关注：长跑 service / 任务引擎
HIGH_PRIORITY_PREFIXES = (
    "app/core/",
    "app/api/routes.py",
)


def find_in_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    findings: list[dict] = []
    for i, line in enumerate(lines):
        m = SESSION_OPEN_RE.match(line)
        if not m:
            continue
        indent = m.group(1)
        # 找匹配的 db.close()
        end_line = None
        for j in range(i + 1, len(lines)):
            close_m = CLOSE_RE.match(lines[j])
            if close_m:
                # 必须 close 缩进至少和 db = ... 同级或更深
                close_indent = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
                if len(close_indent) >= len(indent):
                    end_line = j
                    break
            # 同级 db = SessionLocal() 也算下一段开始（兜底）
            if SESSION_OPEN_RE.match(lines[j]):
                next_indent = SESSION_OPEN_RE.match(lines[j]).group(1)
                if len(next_indent) <= len(indent):
                    end_line = j - 1
                    break
        if end_line is None:
            continue
        block = lines[i : end_line + 1]
        await_count = sum(1 for ln in block if AWAIT_RE.search(ln))
        if await_count == 0:
            continue
        # 找所属函数
        func_name = ""
        for k in range(i, -1, -1):
            fn = re.match(r"^\s*(?:async\s+)?def\s+(\w+)", lines[k])
            if fn:
                func_name = fn.group(1)
                break
        findings.append(
            {
                "file": str(path.relative_to(ROOT.parent)).replace("\\", "/"),
                "line": i + 1,
                "end_line": end_line + 1,
                "rows": end_line - i + 1,
                "await_count": await_count,
                "func": func_name,
            }
        )
    return findings


def main() -> None:
    all_findings: list[dict] = []
    for py in ROOT.rglob("*.py"):
        all_findings.extend(find_in_file(py))
    # 排序：rows 多的优先
    all_findings.sort(key=lambda f: (-f["await_count"], -f["rows"]))
    print(f"# Found {len(all_findings)} long-session-over-await blocks")
    print()
    for f in all_findings:
        marker = "★" if f["file"].startswith(HIGH_PRIORITY_PREFIXES[:1]) else " "
        print(
            f"{marker} {f['file']}:{f['line']}-{f['end_line']}  "
            f"await={f['await_count']:>3d}  rows={f['rows']:>4d}  {f['func']}"
        )


if __name__ == "__main__":
    main()
