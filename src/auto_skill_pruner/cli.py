import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from auto_skill_pruner.analytics import render_markdown_summary
from auto_skill_pruner.models import Component, TestCase
from auto_skill_pruner.pruner import (
    PruningConfig,
    PruningReport,
    prune_skills_and_hooks,
)

logger = logging.getLogger(__name__)


def _build_self_test_suite() -> tuple[list[Component], list[TestCase]]:
    """バッチパイプラインの健全性を単体検証するための決定論的テストフィクスチャを構築する。"""
    components = [
        Component("legacy_step_by_step", "SKILL", "HOW_TO", "Force verbose legacy CoT"),
        Component("redundant_greeting", "SKILL", "HOW_TO", "Start with polite greeting"),
        Component("obsolete_xml_skill", "SKILL", "HOW_TO", "Emit <old_tag>", group_id="legacy_xml"),
        Component("obsolete_xml_hook", "HOOK", "HOW_TO", "Parse <old_tag>", group_id="legacy_xml"),
        Component("strict_domain_schema", "SKILL", "WHAT_SPEC", "Include SCHEMA_V2_COMPLIANT"),
    ]
    cases = [
        TestCase("case_schema", "query_1", lambda out: "SCHEMA_V2_COMPLIANT" in out),
        TestCase("case_accuracy", "query_2", lambda out: "ACCURATE_RESULT" in out),
    ]
    return components, cases


def _simulated_self_test_pipeline(comps: Sequence[Component], payload: str) -> str:
    """セルフテスト用の決定論的モデル挙動シミュレータ。"""
    ids = {c.id for c in comps}
    if ("obsolete_xml_skill" in ids) != ("obsolete_xml_hook" in ids):
        return "BROKEN_XML_BUNDLE"
    tokens: list[str] = []
    if "strict_domain_schema" in ids:
        tokens.append("SCHEMA_V2_COMPLIANT")
    if "legacy_step_by_step" not in ids:
        tokens.append("ACCURATE_RESULT")
    return f"{payload}:{'|'.join(tokens)}"


def run_self_test_pruning() -> PruningReport:
    """セルフテストスイートに対して自動枝刈りを実行し、監査レポートを返す。"""
    components, cases = _build_self_test_suite()
    return prune_skills_and_hooks(
        components,
        cases,
        _simulated_self_test_pipeline,
        PruningConfig(strategy="auto", ddmin_threshold=4),
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """CLI引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="Deterministic Auto-Pruning loop for SKILL and HOOK components."
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in deterministic ablation self-test suite.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help="Path to write Markdown audit report.",
    )
    return parser.parse_args(argv)


def run_cli(argv: Sequence[str] | None = None) -> int:
    """バックグラウンドバッチから呼び出し可能なCLIメイン処理を実行する。"""
    args = _parse_args(argv)
    report = run_self_test_pruning()
    markdown = render_markdown_summary(report)
    if args.report_out is not None:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(markdown, encoding="utf-8")
    logger.info(
        "Auto-pruning finished: initial=%.2f, final=%.2f, surviving=%d, saved_tokens=%d",
        report.initial_score.pass_rate,
        report.final_score.pass_rate,
        len(report.surviving_components),
        report.tokens_saved,
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(run_cli())
