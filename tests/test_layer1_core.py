from collections.abc import Sequence

from pydantic import BaseModel

from auto_skill_pruner.hook_monitor import HookTelemetryMonitor
from auto_skill_pruner.models import (
    Component,
    EvaluationScore,
    SystemState,
    TestCase,
)
from auto_skill_pruner.oracle import (
    compose_validators,
    create_ast_quality_validator,
    create_json_schema_validator,
    create_regex_validator,
    evaluate_system,
)


class SampleSchema(BaseModel):
    answer: str
    confidence: int


def test_system_state_prioritizes_how_to_and_larger_tokens() -> None:
    """旧モデル向けの思考手順強制(HOW_TO)から優先的に削る順序保証を検証する。"""
    comp_spec = Component(
        id="spec_1",
        kind="SKILL",
        category="WHAT_SPEC",
        content="Domain rule A" * 10,
    )
    comp_howto_small = Component(
        id="howto_small",
        kind="SKILL",
        category="HOW_TO",
        content="Think step by step",
    )
    comp_howto_large = Component(
        id="howto_large",
        kind="SKILL",
        category="HOW_TO",
        content="Always write 5 paragraphs of chain of thought before answering." * 5,
    )
    state = SystemState([comp_spec, comp_howto_small, comp_howto_large])
    ordered_ids = [c.id for c in state.active_components]
    assert ordered_ids == ["howto_large", "howto_small", "spec_1"]


def test_deterministic_validators_json_regex_and_ast() -> None:
    """LLMの主観を排した決定論的オラクル(Schema, Regex, AST)の合否判定を検証する。"""
    json_val = create_json_schema_validator(SampleSchema)
    assert json_val('{"answer": "ok", "confidence": 95}') is True
    assert json_val('{"answer": "ok", "confidence": "not_an_int"}') is False

    regex_val = create_regex_validator(
        required_patterns=[r"^def\s+\w+"],
        forbidden_patterns=[r"TODO", r"print\("],
    )
    assert regex_val("def calc(x: int) -> int:\n    return x + 1\n") is True
    assert regex_val("def calc(x: int) -> int:\n    print(x)\n    return x\n") is False

    ast_val = create_ast_quality_validator(max_func_lines=5, max_args=2)
    valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    missing_type_code = "def add(a, b):\n    return a + b\n"
    too_many_args_code = "def add(a: int, b: int, c: int) -> int:\n    return a + b + c\n"
    assert ast_val(valid_code) is True
    assert ast_val(missing_type_code) is False
    assert ast_val(too_many_args_code) is False

    combined = compose_validators([regex_val, ast_val])
    assert combined(valid_code) is True
    assert combined(missing_type_code) is False


def test_evaluate_system_calculates_exact_pass_rate_and_tokens() -> None:
    """テストスイート全体の通過率と有効トークン数が決定論的に算出されることを検証する。"""
    c1 = Component("s1", "SKILL", "WHAT_SPEC", "include_magic_token")
    cases = [
        TestCase("tc1", "q1", lambda out: "MAGIC" in out),
        TestCase("tc2", "q2", lambda out: "q2" in out),
    ]

    def fake_pipeline(comps: Sequence[Component], prompt: str) -> str:
        has_s1 = any(c.id == "s1" for c in comps)
        prefix = "MAGIC:" if has_s1 else "PLAIN:"
        return f"{prefix}{prompt}"

    score_with = evaluate_system([c1], cases, fake_pipeline)
    score_without = evaluate_system([], cases, fake_pipeline)

    assert score_with.pass_rate == 1.0
    assert score_without.pass_rate == 0.5
    assert score_with.active_tokens > score_without.active_tokens
    assert EvaluationScore(1.0, 2, 2, 10).is_acceptable_against(score_with) is True
    assert score_without.is_acceptable_against(score_with) is False


def test_hook_telemetry_monitor_detects_natural_death() -> None:
    """直近N回の推論でexcept補正が一度も発火しないHOOKを自然死として検出できることを検証する。"""
    monitor = HookTelemetryMonitor(window_size=10)
    comp_dead_hook = Component("hook_json_fix", "HOOK", "HOW_TO", "fix trailing comma")
    comp_active_hook = Component("hook_date_norm", "HOOK", "WHAT_SPEC", "normalize date")
    comp_skill = Component("skill_core", "SKILL", "WHAT_SPEC", "domain spec")

    def strict_parse(text: str) -> str:
        if text.endswith(",}"):
            raise ValueError("Trailing comma")
        return text

    def fallback_fix(text: str) -> str:
        return text.replace(",}", "}")

    for _ in range(10):
        res = monitor.execute_hook("hook_json_fix", strict_parse, fallback_fix, '{"a": 1}')
        assert res == '{"a": 1}'

    for i in range(10):
        raw = '{"a": 1,}' if i == 3 else '{"a": 1}'
        monitor.execute_hook("hook_date_norm", strict_parse, fallback_fix, raw)

    assert monitor.get_trigger_count("hook_json_fix") == 0
    assert monitor.get_trigger_count("hook_date_norm") == 1

    dead_ids = monitor.find_naturally_dead_hooks(min_observations=5)
    assert dead_ids == ["hook_json_fix"]

    remaining = monitor.prune_dead_hooks(
        [comp_dead_hook, comp_active_hook, comp_skill],
        min_observations=5,
    )
    assert [c.id for c in remaining] == ["hook_date_norm", "skill_core"]
