"""AST 搬运入口检查。新增裸移动或复制后删源必须接入统一底层或登记具体理由。"""
import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools/file-move-exemptions.json"
NAMES = {"move", "rename", "replace", "copy", "copy2", "copyfile", "copytree", "unlink", "remove", "rmtree"}


def inventory(root=ROOT):
    found = []
    for path in sorted((root / "backend/app").rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    aliases[item.asname or item.name] = item.name
            elif isinstance(node, ast.ImportFrom) and node.module in ("os", "shutil"):
                for item in node.names:
                    aliases[item.asname or item.name] = node.module + "." + item.name

        def resolved(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return resolved(node.value) + "." + node.attr
            return ""

        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.scope = []

            def visit_ClassDef(self, node):
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def visit_FunctionDef(self, node):
                self.scope.append(node.name)
                def own_nodes(current):
                    yield current
                    for child in ast.iter_child_nodes(current):
                        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            yield from own_nodes(child)

                wrapped = []
                for n in own_nodes(node):
                    if isinstance(n, ast.Call):
                        offset = None
                        if resolved(n.func) == "asyncio.to_thread":
                            offset = 0
                        elif isinstance(n.func, ast.Attribute) and n.func.attr == "run_in_executor":
                            offset = 1
                        if offset is not None and len(n.args) > offset and resolved(n.args[offset]).rsplit(".", 1)[-1] in NAMES:
                            proxy = ast.Call(func=n.args[offset], args=n.args[offset + 1:], keywords=n.keywords)
                            ast.copy_location(proxy, n)
                            wrapped.append(proxy)
                calls = [n for n in own_nodes(node) if isinstance(n, ast.Call)
                         and resolved(n.func).rsplit(".", 1)[-1] in NAMES]
                calls.extend(wrapped)
                names = {resolved(n.func).rsplit(".", 1)[-1] for n in calls}
                paired = bool(any(resolved(n.func) in
                                  {"shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree"}
                                  for n in calls)
                              and names & {"unlink", "remove", "rmtree"})
                for call in calls:
                    expression = ast.get_source_segment(source, call.func)
                    qualified = resolved(call.func)
                    # replace() 也大量用于字符串；只纳入文件系统 API 及 Path 对象风格。
                    raw = qualified in ("os.rename", "os.replace", "shutil.move")
                    copying = qualified in {"shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree"}
                    path_method = isinstance(call.func, ast.Attribute) and call.func.attr in {
                        "rename", "replace"} and not raw and len(call.args) == 1
                    if raw or path_method or copying or paired:
                        key = "{}:{}:{}".format(path.relative_to(root).as_posix(),
                                                ".".join(self.scope), expression)
                        found.append({"key": key, "line": call.lineno,
                                      "source": ast.get_source_segment(source, call).splitlines()[0]})
                # 内层函数另行登记，避免与外层重复。
                def nested(current):
                    for child in ast.iter_child_nodes(current):
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            self.visit(child)
                        else:
                            nested(child)
                nested(node)
                self.scope.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

        Visitor().visit(tree)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    rows = inventory()
    if args.inventory:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    exemptions = json.loads(MANIFEST.read_text(encoding="utf-8"))
    missing = [row for row in rows if not exemptions.get(row["key"])]
    stale = sorted(set(exemptions) - {row["key"] for row in rows})
    if missing or stale:
        print(json.dumps({"unreviewed": missing, "stale": stale}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print("搬运入口检查通过：{} 处，均有逐入口审查记录".format(len(rows)))


if __name__ == "__main__":
    main()
