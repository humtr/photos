from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT_GUI = Path(__file__).resolve().parents[1] / "photo_organizer_app.py"


def call_names(node: ast.AST) -> list[str]:
    return [
        ast.unparse(item.func)
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
    ]


def is_plan_mismatch_guard(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and ast.unparse(node.test) == "gui_pairs != service_pairs"
    )


class RootGuiServiceBoundaryTests(unittest.TestCase):
    def test_execution_uses_service_and_has_no_direct_mutation_calls(self) -> None:
        source = ROOT_GUI.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = set(call_names(tree))
        worker = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_service_execute_worker"
        )
        worker_source = ast.unparse(worker)
        mismatch_guards = [node for node in ast.walk(worker) if is_plan_mismatch_guard(node)]
        self.assertEqual(len(mismatch_guards), 1)
        mismatch_guard = mismatch_guards[0]
        self.assertIsInstance(mismatch_guard.body[-1], ast.Return)

        enclosing_bodies = [
            value
            for node in ast.walk(worker)
            for _field, value in ast.iter_fields(node)
            if isinstance(value, list) and mismatch_guard in value
        ]
        self.assertEqual(len(enclosing_bodies), 1)
        enclosing_body = enclosing_bodies[0]
        guard_index = enclosing_body.index(mismatch_guard)
        after_guard_calls = [
            call
            for statement in enclosing_body[guard_index + 1 :]
            for call in call_names(statement)
        ]
        required_after_guard_calls = [
            "service.dry_run_plan",
            "service.approve_plan",
            "service.can_execute",
            "service.execute_plan",
        ]

        self.assertIn("PhotoOrganizerService", source)
        positions = [after_guard_calls.index(call) for call in required_after_guard_calls]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("progress_callback=lambda payload:", worker_source)
        self.assertIn("self._service_progress_message(payload)", worker_source)
        self.assertIn("progress_callback=dry_run_progress", worker_source)
        self.assertNotIn("service.execute_plan", call_names(mismatch_guard))
        self.assertIn("self.after", worker_source)
        self.assertNotIn("import sqlite3", source)
        self.assertNotIn("shutil.move", calls)
        self.assertNotIn("os.remove", calls)
        self.assertNotIn("os.rename", calls)
        self.assertNotIn("os.replace", calls)
        self.assertFalse(any(call.endswith(".unlink") for call in calls))
        self.assertFalse(any(call.endswith(".rename") for call in calls))

    def test_service_failure_helper_includes_recovery_hint(self) -> None:
        source = ROOT_GUI.read_text(encoding="utf-8")
        tree = ast.parse(source)
        helper = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_service_data"
        )
        helper_source = ast.unparse(helper)

        self.assertIn("next_safe_action", helper_source)
        self.assertIn("warnings", helper_source)
        self.assertIn("다음 안전 조치", helper_source)
        self.assertIn("raise RuntimeError(detail)", helper_source)

    def test_service_progress_helper_formats_counts(self) -> None:
        source = ROOT_GUI.read_text(encoding="utf-8")
        tree = ast.parse(source)
        helper = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_service_progress_message"
        )
        helper_source = ast.unparse(helper)

        self.assertIn("hash_missing", helper_source)
        self.assertIn("analysis", helper_source)
        self.assertIn("sample_dry_run", helper_source)
        self.assertIn("스캔 완료", helper_source)
        self.assertIn("검증 중", helper_source)
        self.assertIn("실행 가능", helper_source)
        self.assertIn("execute_plan", helper_source)
        self.assertIn("resume_batch", helper_source)
        self.assertIn("진행 중", helper_source)

    def test_service_progress_helper_formats_stage_transitions(self) -> None:
        source = ROOT_GUI.read_text(encoding="utf-8")
        tree = ast.parse(source)
        helper = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_service_progress_message"
        )
        module = ast.fix_missing_locations(ast.Module(body=[helper], type_ignores=[]))
        namespace: dict[str, object] = {}
        exec(compile(module, str(ROOT_GUI), "exec"), namespace, namespace)
        progress_message = namespace["_service_progress_message"]

        self.assertEqual(progress_message({"operation": "analysis", "phase": "starting"}), "분석 시작")
        self.assertEqual(
            progress_message({"operation": "analysis", "phase": "scanned", "scanned": 7}),
            "분석 스캔 완료: 7개 파일",
        )
        self.assertEqual(
            progress_message({"operation": "sample_dry_run", "phase": "manifest_written", "candidate_count": 3}),
            "사전 점검 후보 명세 작성: 3건",
        )
        self.assertEqual(
            progress_message(
                {
                    "operation": "dry_run_plan",
                    "phase": "completed",
                    "action_count": 2,
                    "execute_allowed": True,
                }
            ),
            "사전 점검 완료: 2개 검토, 실행 가능 True",
        )


if __name__ == "__main__":
    unittest.main()
