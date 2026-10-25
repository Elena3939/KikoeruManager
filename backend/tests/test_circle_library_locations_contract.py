"""隔离路由依赖，验证定位查询不会走扫盘或字幕子树读取。"""
import ast
import json
from pathlib import Path
import re
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class CircleLibraryLocationsTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parents[1] / "app/api/routes.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                    and item.name == "circle_completion_library_locations")
        node.decorator_list = []
        self.manager = Mock()
        namespace = {
            "re": re, "HTTPException": HTTPException, "JSONResponse": JSONResponse,
            "get_library_manager": lambda: self.manager,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
        self.locate = namespace[node.name]

    def test_exact_language_and_current_index_without_subtitle_walk(self):
        self.manager.find_rj_in_ready_index.side_effect = [
            {"RJ10002": [{"rjcode": "RJ10002", "library_id": "local", "path": "/旧位置"}]},
            {"RJ10002": [{"rjcode": "RJ10002", "library_id": "local", "path": "/新位置"}]},
        ]
        first = self.locate("rj10002")
        second = self.locate("RJ10002")
        self.assertEqual(json.loads(first.body)["locations"][0]["path"], "/旧位置")
        self.assertEqual(json.loads(second.body)["locations"][0]["path"], "/新位置")
        self.assertEqual(second.headers["cache-control"], "no-store")
        for call in self.manager.find_rj_in_ready_index.call_args_list:
            self.assertEqual(call.args, (["RJ10002"],))
            self.assertEqual(call.kwargs, {"include_subtitle_state": False})
        self.manager.find_rj_in_libraries.assert_not_called()

    def test_missing_version_does_not_use_other_language(self):
        self.manager.find_rj_in_ready_index.return_value = {"RJ10000": [{"path": "/原作"}]}
        self.assertEqual(json.loads(self.locate("RJ10002").body)["locations"], [])

    def test_invalid_code_does_not_query_index(self):
        with self.assertRaises(HTTPException) as caught:
            self.locate("RJ10002/../../")
        self.assertEqual(caught.exception.status_code, 400)
        self.manager.find_rj_in_ready_index.assert_not_called()

    def test_descendants_and_duplicates_collapse_to_work_root(self):
        paths = [
            "/库存/RJ10002/wav",
            "/库存/RJ10002/台词",
            "/库存/RJ10002",
            "/库存/RJ10002/",
            "/库存/RJ10002/台词/文本",
            "/库存/RJ10002-另一份",
        ]
        self.manager.find_rj_in_ready_index.return_value = {
            "RJ10002": [
                {"rjcode": "RJ10002", "library_id": "local", "path": path}
                for path in paths
            ],
        }
        locations = json.loads(self.locate("RJ10002").body)["locations"]
        self.assertEqual([item["path"] for item in locations],
                         ["/库存/RJ10002", "/库存/RJ10002-另一份"])

    def test_same_path_in_different_libraries_remains_independent(self):
        self.manager.find_rj_in_ready_index.return_value = {
            "RJ10002": [
                {"rjcode": "RJ10002", "library_id": library, "path": "/库存/RJ10002"}
                for library in ("local", "archive")
            ],
        }
        self.assertEqual(len(json.loads(self.locate("RJ10002").body)["locations"]), 2)

    def test_windows_case_and_separators_do_not_create_extra_locations(self):
        self.manager.find_rj_in_ready_index.return_value = {
            "RJ10002": [
                {"rjcode": "RJ10002", "library_id": "local", "path": path}
                for path in ("D:\\ASMR\\RJ10002\\wav", "d:/asmr/RJ10002", "D:/ASMR/rj10002/")
            ],
        }
        locations = json.loads(self.locate("RJ10002").body)["locations"]
        self.assertEqual([item["path"] for item in locations], ["d:/asmr/RJ10002"])


if __name__ == "__main__":
    unittest.main()
