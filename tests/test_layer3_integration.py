from collections.abc import Sequence
from pathlib import Path

import pytest

from auto_skill_pruner.analytics import (
    extract_negative_interaction_culprits,
    render_markdown_summary,
     steps_to_lazyframe,
    summarize_pruning_by_phase,
)
from auto_skill_pruner.cli import run_cli
from auto_skill_pruner.file_manager import (
    SkillFileTransaction,
    load_skills_from_directory,
    run_transactional_file_pruning,
)
from auto_skill_pruner.models import Component, TestCase
from auto_skill_pruner.pruner import PruningConfig, prune_skills_and_hooks


def _create_sample_skill_file(
    base_dir: Path,
    folder_name: str,
    category: str,
    body: str,
) -> Path:
    skill_dir = base_dir / folder_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    content = f"---\nname: {folder_name}\ncategory: {category}\n---\n\n{body}\n"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def test_polars_lazy_analytics_identifies_harmful_skills_and_summary() -> None:
    """PolarsのLazyチェーンにより、負の相互作用を起こした有害SKILLと削減統計が抽出されることを検証する。"""
    harmful = Component("bad_cot", "SKILL", "HOW_TO", "Confusing legacy rule " * 20)
    redundant = Component("extra_tip", "SKILL", "HOW_TO", "Redundant tip " * 10)
    essential = Component("strict_spec", "SKILL", "WHAT_SPEC", "Must include SPEC_OK")

    cases = [
        TestCase("t1", "x", lambda out: "SPEC_OK" in out),
        TestCase("t2", "y", lambda out: "CLEAN_REASONING" in out),
    ]

    def sim_runner(comps: Sequence[Component], payload: str) -> str:
        ids = {c.id for c in comps}
        parts = []
        if "strict_spec" in ids:
            parts.append("SPEC_OK")
        if "bad_cot" not in ids:
            parts.append("CLEAN_REASONING")
        return "|".join(parts)

    report = prune_skills_and_hooks(
        [harmful, redundant, essential],
        cases,
        sim_runner,
        PruningConfig(strategy="linear"),
    )

    lf = steps_to_lazyframe(report.step_logs)
    summary_df = summarize_pruning_by_phase(lf)
    culprits_df = extract_negative_interaction_culprits(lf)

    assert summary_df.height >= 1
    assert culprits_df.height == 1
    assert culprits_df["target_key"][0] == "bad_cot"
    assert culprits_df["score_gain"][0] == pytest.approx(0.5)

    md = render_markdown_summary(report)
    assert "bad_cot" in md
    assert "strict_spec" in md


def test_transactional_file_pruning_and_rollback_safety(tmp_path: Path) -> None:
    """実ファイルシステムのSKILL.md群に対する枝刈り・アーカイブ確定と、例外時の完全ロールバックを検証する。"""
    skills_root = tmp_path / "skills"
    archive_dir = tmp_path / "archived_skills"

    _create_sample_skill_file(skills_root, "how_to_think", "HOW_TO", "Step by step legacy constraint")
    _create_sample_skill_file(skills_root, "domain_rule", "WHAT_SPEC", "Essential domain schema")

    loaded = load_skills_from_directory(skills_root)
    assert len(loaded) == 2

    def crashing_runner(comps: Sequence[Component], payload: str) -> str:
        raise RuntimeError("Simulated API network failure during trial")

    cases = [TestCase("tc1", "in", lambda out: "DOMAIN_OK" in out)]

    with pytest.raises(RuntimeError, match="Simulated API network failure"):
        run_transactional_file_pruning(skills_root, archive_dir, cases, crashing_runner)

    assert (skills_root / "how_to_think" / "SKILL.md").exists()
    assert (skills_root / "domain_rule" / "SKILL.md").exists()

    def disk_aware_runner(comps: Sequence[Component], payload: str) -> str:
        existing_on_disk = {
            c.id for c in comps if c.file_path is not None and Path(c.file_path).exists()
        }
        if "how_to_think" in existing_on_disk:
            return "OVER_CONSTRAINED_ERROR"
        if "domain_rule" in existing_on_disk:
            return "DOMAIN_OK"
        return "EMPTY"

    report = run_transactional_file_pruning(
        skills_root,
        archive_dir,
        cases,
        disk_aware_runner,
    )
    assert [c.id for c in report.surviving_components] == ["domain_rule"]
    assert (skills_root / "domain_rule" / "SKILL.md").exists()
    assert not (skills_root / "how_to_think" / "SKILL.md").exists()
    assert (archive_dir / "how_to_think" / "SKILL.md").exists()


def test_skill_file_transaction_direct_restore(tmp_path: Path) -> None:
    """SkillFileTransactionの明示的な退避と復元がファイルを破損しないことを検証する。"""
    skills_root = tmp_path / "skills_tx"
    f_path = _create_sample_skill_file(skills_root, "temp_skill", "HOW_TO", "Temporary content")
    comps = load_skills_from_directory(skills_root)
    assert len(comps) == 1

    with SkillFileTransaction(skills_root) as tx:
        tx.sync_active_files([])
        assert not f_path.exists()
        tx.rollback_all()
        assert f_path.exists()


def test_cli_self_test_and_directory_execution(tmp_path: Path) -> None:
    """CLIエントリポイントがバッチ実行され、Markdownレポートを正常に出力することを検証する。"""
    report_path = tmp_path / "pruning_report.md"
    exit_code = run_cli(["--self-test", "--report-out", str(report_path)])
    assert exit_code == 0
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "自動枝刈り (Auto-Pruning) 監査レポート" in content
