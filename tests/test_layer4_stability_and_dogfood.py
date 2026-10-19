import ast
from collections.abc import Sequence
from pathlib import Path

from auto_skill_pruner.models import Component, TestCase
from auto_skill_pruner.oracle import (
    create_ast_quality_validator,
    create_regex_validator,
)
from auto_skill_pruner.pruner import PruningConfig, prune_skills_and_hooks


def test_multi_trial_stability_prevents_flaky_skill_deletion() -> None:
    """推論に揺らぎがあり1回目だけ偶然成功しても、複数回試行(trials_per_case)により誤削除を防ぐことを検証する。"""
    critical_skill = Component(
        "critical_safety_guard",
        "SKILL",
        "WHAT_SPEC",
        "Ensure consistent output across all runs",
    )
    cases = [TestCase("tc_flaky", "input", lambda out: out == "STABLE_OK")]
    attempt_counter = 0

    def flaky_without_skill_runner(comps: Sequence[Component], payload: str) -> str:
        nonlocal attempt_counter
        if any(c.id == "critical_safety_guard" for c in comps):
            return "STABLE_OK"
        attempt_counter += 1
        return "STABLE_OK" if attempt_counter % 2 == 1 else "FLAKY_FAILURE"

    report = prune_skills_and_hooks(
        [critical_skill],
        cases,
        flaky_without_skill_runner,
        PruningConfig(strategy="linear", trials_per_case=3),
    )
    assert [c.id for c in report.surviving_components] == ["critical_safety_guard"]
    assert report.final_score.pass_rate == 1.0


def test_large_scale_ddmin_convergence() -> None:
    """38要素(HOW_TOとWHAT_SPECの混在および負の相互作用を含む)からddminで最小構成へ高速収束することを検証する。"""
    how_to_skills = [
        Component(f"howto_{i:02d}", "SKILL", "HOW_TO", f"Legacy reasoning step {i}" * 25)
        for i in range(20)
    ]
    spec_skills = [
        Component(f"spec_{i:02d}", "SKILL", "WHAT_SPEC", f"Domain specification {i}" * 15)
        for i in range(18)
    ]
    all_skills = [*how_to_skills, *spec_skills]

    cases = [
        TestCase("tc_spec_03", "q1", lambda out: "SPEC_03_OK" in out),
        TestCase("tc_spec_14", "q2", lambda out: "SPEC_14_OK" in out),
        TestCase("tc_no_interference", "q3", lambda out: "CONFLICT" not in out),
    ]

    def pipeline(comps: Sequence[Component], payload: str) -> str:
        ids = {c.id for c in comps}
        tokens: list[str] = []
        if "spec_03" in ids:
            tokens.append("SPEC_03_OK")
        if "spec_14" in ids:
            tokens.append("SPEC_14_OK")
        if "howto_00" in ids and "howto_01" in ids:
            tokens.append("CONFLICT")
        return "|".join(tokens)

    report = prune_skills_and_hooks(
        all_skills,
        cases,
        pipeline,
        PruningConfig(strategy="ddmin"),
    )
    surviving_ids = {c.id for c in report.surviving_components}
    assert surviving_ids == {"spec_03", "spec_14"}
    assert report.final_score.pass_rate == 1.0
    assert report.tokens_saved > 4000


def _max_control_nesting(node: ast.AST, current_depth: int = 0) -> int:
    """ASTノード内の制御構造(if/for/while/try/with)の最大ネスト階層を再帰計測する。"""
    control_types = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)
    next_depth = current_depth + (1 if isinstance(node, control_types) else 0)
    child_depths = [_max_control_nesting(child, next_depth) for child in ast.iter_child_nodes(node)]
    return max([next_depth, *child_depths])


def _count_non_comment_code_lines(func_node: ast.FunctionDef | ast.AsyncFunctionDef, source_lines: list[str]) -> int:
    """docstring・空行・コメント行を除いた関数の実効コード行数を計測する。"""
    start = func_node.lineno
    end = func_node.end_lineno or start
    doc_end = start - 1
    if (
        func_node.body
        and isinstance(func_node.body[0], ast.Expr)
        and isinstance(func_node.body[0].value, ast.Constant)
        and isinstance(func_node.body[0].value.value, str)
    ):
        doc_end = func_node.body[0].end_lineno or start

    count = 0
    for line_no in range(start, end + 1):
        if start < line_no <= doc_end:
            continue
        stripped = source_lines[line_no - 1].strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def test_dogfood_all_source_files_pass_static_quality_gates() -> None:
    """本パッケージ自身の全ソースコードが30行制限・引数4個制限・ネスト2階層制限・型ヒント100%・print禁止を満たすことを検証する。"""
    src_dir = Path(__file__).resolve().parent.parent / "src" / "auto_skill_pruner"
    py_files = sorted(src_dir.glob("*.py"))
    assert len(py_files) >= 5

    no_print_validator = create_regex_validator(forbidden_patterns=[r"\bprint\s*\("])
    ast_validator = create_ast_quality_validator(max_func_lines=45, max_args=4)

    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        source_lines = source.splitlines()
        assert no_print_validator(source) is True, f"Forbidden print() in {py_file.name}"
        assert ast_validator(source) is True, f"AST type/arg failure in {py_file.name}"

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                code_lines = _count_non_comment_code_lines(node, source_lines)
                assert code_lines <= 30, f"{py_file.name}:{node.name} has {code_lines} code lines (>30)"
                nesting = _max_control_nesting(node)
                assert nesting <= 2, f"{py_file.name}:{node.name} has nesting depth {nesting} (>2)"
