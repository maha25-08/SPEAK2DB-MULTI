import ast
import py_compile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
APP_PATH = REPO_ROOT / "app.py"


class TestAppStudentFilterSyntax(unittest.TestCase):
    def test_app_py_compiles(self):
        py_compile.compile(str(APP_PATH), doraise=True)

    def test_apply_student_filters_is_defined_with_expected_parameters(self):
        module = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        functions = {
            node.name: node for node in module.body if isinstance(node, ast.FunctionDef)
        }

        self.assertIn("_apply_student_filters", functions)
        function = functions["_apply_student_filters"]
        self.assertEqual(
            [arg.arg for arg in function.args.args],
            ["sql_query", "sid", "has_where", "sq_lower", "q_lower"],
        )
