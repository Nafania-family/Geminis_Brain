from collections.abc import Sequence

from auto_skill_pruner.hook_monitor import HookTelemetryMonitor
from auto_skill_pruner.models import Component, ComponentCategory, TestCase
from auto_skill_pruner.pruner import PruningConfig, prune_skills_and_hooks


def test_shortcut_all_off_when_base_model_passes_100_percent() -> None:
    """素のモデルで全テストを100%通過する場合、個別検証を待たずに全SKILL/HOOKが廃止されることを検証する。"""
    skills = [
        Component(f"skill_{i}", "SKILL", "HOW_TO", f"redundant instruction {i}")
        for i in range(10)
    ]
    cases = [TestCase("tc1", "input_1", lambda out: out == "clean:input_1")]
    call_count = 0

    def perfect_base_model(comps: Sequence[Component], payload: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"clean:{payload}"

    report = prune_skills_and_hooks(skills, cases, perfect_base_model)
    assert report.surviving_components == []
    assert report.final_score.pass_rate == 1.0
    assert call_count <= 2


def test_negative_interaction_boosts_baseline_and_keeps_essential_spec() -> None:
    """旧モデル用の有害なHOW_TOを削除してベースラインを上方修正し、必須WHAT_SPECを維持することを検証する。"""
    harmful_howto = Component(
        "legacy_cot_constraint",
        "SKILL",
        "HOW_TO",
        "Force rigid step-by-step format that breaks modern reasoning",
    )
    useless_howto = Component(
        "polite_greeting",
        "SKILL",
        "HOW_TO",
        "Be polite in internal thoughts",
    )
    essential_spec = Component(
        "domain_tax_spec",
        "SKILL",
        "WHAT_SPEC",
        "Apply 8% reduced tax rate for food items",
    )
    useless_spec = Component(
        "obsolete_v1_spec",
        "SKILL",
        "WHAT_SPEC",
        "Unused legacy constant",
    )

    cases = [
        TestCase("tc_reasoning", "complex_math", lambda out: "REASONING_OK" in out),
        TestCase("tc_domain", "food_tax", lambda out: "TAX_8_PERCENT" in out),
    ]

    def simulated_new_model(comps: Sequence[Component], payload: str) -> str:
        ids = {c.id for c in comps}
        tokens: list[str] = []
        if "legacy_cot_constraint" not in ids:
            tokens.append("REASONING_OK")
        if "domain_tax_spec" in ids:
            tokens.append("TAX_8_PERCENT")
        return f"{payload}:{'|'.join(tokens)}"

    initial = [useless_spec, essential_spec, useless_howto, harmful_howto]
    report = prune_skills_and_hooks(
        initial,
        cases,
        simulated_new_model,
        PruningConfig(strategy="linear"),
    )

    surviving_ids = [c.id for c in report.surviving_components]
    assert surviving_ids == ["domain_tax_spec"]
    assert report.initial_score.pass_rate == 0.5
    assert report.final_score.pass_rate == 1.0
    assert report.tokens_saved > 0


def test_co_dependent_group_bundle_pruning_and_dead_hooks() -> None:
    """共依存するSKILLとHOOKのペア(group_id)が一括削除され、自然死HOOKも事前除去されることを検証する。"""
    xml_skill = Component(
        "force_xml_tag",
        "SKILL",
        "HOW_TO",
        "Wrap output in <legacy_xml>",
        group_id="xml_bundle",
    )
    xml_hook = Component(
        "parse_xml_tag",
        "HOOK",
        "HOW_TO",
        "Require <legacy_xml> tag or fail",
        group_id="xml_bundle",
    )
    dead_hook = Component("dead_regex_hook", "HOOK", "HOW_TO", "Never triggered fallback")
    core_spec = Component("core_json_spec", "SKILL", "WHAT_SPEC", "Output valid JSON")

    monitor = HookTelemetryMonitor(window_size=20)
    for _ in range(10):
        monitor.record_execution("dead_regex_hook", triggered_fallback=False)

    cases = [TestCase("tc1", "req", lambda out: out == "VALID_JSON")]

    def bundle_pipeline(comps: Sequence[Component], payload: str) -> str:
        ids = {c.id for c in comps}
        if ("force_xml_tag" in ids) != ("parse_xml_tag" in ids):
            return "BROKEN_MISMATCH"
        if "core_json_spec" not in ids:
            return "MISSING_SPEC"
        return "VALID_JSON"

    cfg = PruningConfig(
        strategy="linear",
        hook_monitor=monitor,
        min_hook_observations=5,
    )
    report = prune_skills_and_hooks(
        [xml_skill, xml_hook, dead_hook, core_spec],
        cases,
        bundle_pipeline,
        cfg,
    )
    assert [c.id for c in report.surviving_components] == ["core_json_spec"]
    assert any(log.outcome == "DEAD_HOOK" for log in report.step_logs)


def test_ddmin_logarithmic_pruning_and_idempotency() -> None:
    """大量のSKILL群に対してddminチャンク枝刈りが少ない評価回数で極小集合へ収束し冪等であることを検証する。"""
    components: list[Component] = []
    for i in range(32):
        cat: ComponentCategory = "HOW_TO" if i < 16 else "WHAT_SPEC"
        components.append(Component(f"comp_{i:02d}", "SKILL", cat, f"Rule content {i}"))

    essential_ids = {"comp_05", "comp_27"}
    cases = [
        TestCase("tc_a", "a", lambda out: "HAS_05" in out),
        TestCase("tc_b", "b", lambda out: "HAS_27" in out),
    ]

    def large_pipeline(comps: Sequence[Component], payload: str) -> str:
        ids = {c.id for c in comps}
        flags = []
        if "comp_05" in ids:
            flags.append("HAS_05")
        if "comp_27" in ids:
            flags.append("HAS_27")
        return "|".join(flags)

    report_ddmin = prune_skills_and_hooks(
        components,
        cases,
        large_pipeline,
        PruningConfig(strategy="ddmin"),
    )
    surviving_ids = {c.id for c in report_ddmin.surviving_components}
    assert surviving_ids == essential_ids
    assert report_ddmin.final_score.pass_rate == 1.0
    assert report_ddmin.evaluation_calls < len(components)

    report_second_pass = prune_skills_and_hooks(
        report_ddmin.surviving_components,
        cases,
        large_pipeline,
        PruningConfig(strategy="ddmin"),
    )
    assert [c.id for c in report_second_pass.surviving_components] == [
        c.id for c in report_ddmin.surviving_components
    ]
