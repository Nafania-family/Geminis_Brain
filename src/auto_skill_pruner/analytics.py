from collections.abc import Sequence

import polars as pl

from auto_skill_pruner.models import PruningStepLog
from auto_skill_pruner.pruner import PruningReport

_STEP_SCHEMA: dict[str, pl.DataType] = {
    "step_index": pl.Int64(),
    "phase": pl.String(),
    "target_key": pl.String(),
    "primary_category": pl.String(),
    "baseline_pass_rate": pl.Float64(),
    "trial_pass_rate": pl.Float64(),
    "tokens_delta": pl.Int64(),
    "outcome": pl.String(),
}


def steps_to_lazyframe(step_logs: Sequence[PruningStepLog]) -> pl.LazyFrame:
    """Polarsのクエリプランナー最適化を効かせるため、ステップ履歴を直接LazyFrameへ変換する。"""
    rows = [
        {
            "step_index": log.step_index,
            "phase": log.phase,
            "target_key": "|".join(log.target_ids),
            "primary_category": log.categories[0] if log.categories else "UNKNOWN",
            "baseline_pass_rate": log.baseline_pass_rate,
            "trial_pass_rate": log.trial_pass_rate,
            "tokens_delta": log.tokens_delta,
            "outcome": log.outcome,
        }
        for log in step_logs
    ]
    return pl.LazyFrame(rows, schema=_STEP_SCHEMA)


def summarize_pruning_by_phase(lf: pl.LazyFrame) -> pl.DataFrame:
    """中間DataFrame代入を排し、単一Lazyチェーンでフェーズ・判定別のトークン削減量を集計するため。"""
    return (
        lf.with_columns(
            (pl.col("trial_pass_rate") - pl.col("baseline_pass_rate")).alias("score_gain"),
            (-pl.col("tokens_delta")).clip(lower_bound=0).alias("saved_tokens"),
        )
        .group_by("phase", "outcome")
        .agg(
            pl.len().alias("trial_count"),
            pl.col("saved_tokens").sum().alias("total_saved_tokens"),
            pl.col("score_gain").max().alias("max_score_gain"),
        )
        .sort("phase", "outcome")
        .collect()
    )


def extract_negative_interaction_culprits(lf: pl.LazyFrame) -> pl.DataFrame:
    """削除した瞬間にテスト通過率が跳ね上がった有害SKILL(負の相互作用の犯人)を特定するため。"""
    return (
        lf.with_columns(
            (pl.col("trial_pass_rate") - pl.col("baseline_pass_rate")).alias("score_gain"),
        )
        .filter((pl.col("outcome") == "PRUNED") & (pl.col("score_gain") > 1e-9))
        .select(
            "step_index",
            "phase",
            "target_key",
            "primary_category",
            "baseline_pass_rate",
            "trial_pass_rate",
            "score_gain",
        )
        .sort("score_gain", descending=True)
        .collect()
    )


def _format_component_bullets(components: Sequence[object], empty_label: str) -> list[str]:
    """コンポーネント一覧をMarkdown箇条書きリストへ整形する。"""
    from auto_skill_pruner.models import Component

    items = [c for c in components if isinstance(c, Component)]
    if not items:
        return [f"- {empty_label}"]
    return [f"- `{c.id}` [{c.kind}/{c.category}] ({c.token_estimate} tokens)" for c in items]


def render_markdown_summary(report: PruningReport) -> str:
    """バッチ実行後の監査用に、枝刈り前後の定量指標と有害SKILL一覧をMarkdown化する。"""
    culprits_df = extract_negative_interaction_culprits(steps_to_lazyframe(report.step_logs))
    culprit_lines = [
        f"- `{r['target_key']}` ({r['primary_category']}): "
        f"スコア {r['baseline_pass_rate']:.2f} -> {r['trial_pass_rate']:.2f}"
        for r in culprits_df.iter_rows(named=True)
    ] or ["- 該当なし"]
    total_cnt = len(report.surviving_components) + len(report.pruned_components)
    init_s, fin_s = report.initial_score, report.final_score
    lines = [
        "# 自動枝刈り (Auto-Pruning) 監査レポート\n\n## 1. サマリ指標",
        f"- **初期スコア**: {init_s.pass_rate:.2f} (要素数: {total_cnt})",
        f"- **最終スコア**: {fin_s.pass_rate:.2f} (生存要素数: {len(report.surviving_components)})",
        f"- **削減トークン数**: {report.tokens_saved} tokens ({init_s.active_tokens} -> {fin_s.active_tokens})",
        f"- **オラクル評価呼び出し回数**: {report.evaluation_calls} 回\n",
        "## 2. 負の相互作用を起こしていた有害要素 (削除によりスコア向上)",
        *culprit_lines,
        "\n## 3. 削除確定要素 (Pruned)",
        *_format_component_bullets(report.pruned_components, "なし"),
        "\n## 4. 最終維持要素 (Surviving Minimal Set)",
        *_format_component_bullets(report.surviving_components, "なし（全要素廃止）"),
        "",
    ]
    return "\n".join(lines)
