import ast
import logging
import re
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ValidationError

from auto_skill_pruner.models import Component, EvaluationScore, TestCase

logger = logging.getLogger(__name__)

PipelineRunner = Callable[[Sequence[Component], str], str]
ValidatorFn = Callable[[str], bool]


def create_json_schema_validator(model_cls: type[BaseModel]) -> ValidatorFn:
    """LLMの曖昧な自己採点を排し、Pydanticスキーマ適合性のみで構造化出力を厳密判定するため。"""

    def _validate(output: str) -> bool:
        try:
            model_cls.model_validate_json(output)
            return True
        except ValidationError:
            return False

    return _validate


def create_regex_validator(
    required_patterns: Sequence[str] = (),
    forbidden_patterns: Sequence[str] = (),
) -> ValidatorFn:
    """正規表現による必須構文の確認とNGワードの機械的排除を一括で行うため。"""
    req_compiled = [re.compile(p, re.MULTILINE) for p in required_patterns]
    forb_compiled = [re.compile(p, re.MULTILINE) for p in forbidden_patterns]

    def _validate(output: str) -> bool:
        has_all_required = all(r.search(output) is not None for r in req_compiled)
        has_no_forbidden = all(f.search(output) is None for f in forb_compiled)
        return has_all_required and has_no_forbidden

    return _validate


def _is_function_compliant(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    max_func_lines: int,
    max_args: int,
) -> bool:
    """生成コード内の個別関数が行数上限・引数上限・型ヒント100%を満たすかASTで機械検証するため。"""
    args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    if len(args) > max_args or node.returns is None:
        return False
    if any(arg.annotation is None for arg in args):
        return False
    start_line = node.lineno
    end_line = node.end_lineno or start_line
    return (end_line - start_line + 1) <= max_func_lines


def create_ast_quality_validator(
    max_func_lines: int = 30,
    max_args: int = 4,
) -> ValidatorFn:
    """生成されたPythonコードの構文正当性と静的品質規約をAST解析で決定論的に検査するため。"""

    def _validate(output: str) -> bool:
        try:
            tree = ast.parse(output)
        except SyntaxError:
            return False
        funcs = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        return all(_is_function_compliant(f, max_func_lines, max_args) for f in funcs)

    return _validate


def compose_validators(validators: Sequence[ValidatorFn]) -> ValidatorFn:
    """複数の決定論的検証器を単一のオラクル関数として合成できるようにするため。"""

    def _validate(output: str) -> bool:
        return all(v(output) for v in validators)

    return _validate


def evaluate_system(
    active_components: Sequence[Component],
    test_cases: Sequence[TestCase],
    pipeline_runner: PipelineRunner,
) -> EvaluationScore:
    """指定されたSKILL/HOOK群のみで推論を実行し、外部検証器の通過率とトークン数を算出するため。"""
    active_tokens = sum(c.token_estimate for c in active_components)
    if not test_cases:
        return EvaluationScore(1.0, 0, 0, active_tokens)

    passed = 0
    for case in test_cases:
        output = pipeline_runner(active_components, case.input_payload)
        if case.deterministic_validator(output):
            passed += 1

    pass_rate = passed / len(test_cases)
    logger.debug(
        "Evaluated %d components: pass_rate=%.4f (%d/%d), tokens=%d",
        len(active_components),
        pass_rate,
        passed,
        len(test_cases),
        active_tokens,
    )
    return EvaluationScore(pass_rate, passed, len(test_cases), active_tokens)
