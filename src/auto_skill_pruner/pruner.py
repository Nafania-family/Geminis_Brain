import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from auto_skill_pruner.hook_monitor import HookTelemetryMonitor
from auto_skill_pruner.models import (
    Component,
    EvaluationScore,
    PruningOutcome,
    PruningStepLog,
    SystemState,
    TestCase,
)
from auto_skill_pruner.oracle import PipelineRunner, evaluate_system

logger = logging.getLogger(__name__)

PruningStrategy = Literal["auto", "linear", "ddmin"]
PruningUnit = tuple[Component, ...]


@dataclass(frozen=True)
class PruningConfig:
    """枝刈りアルゴリズムの戦略・閾値・HOOK監視設定を保持する。"""

    strategy: PruningStrategy = "auto"
    ddmin_threshold: int = 8
    hook_monitor: HookTelemetryMonitor | None = None
    min_hook_observations: int = 1000
    on_trial_callback: " TrialCallback | None" = None


TrialCallback = object


@dataclass(frozen=True)
class PruningReport:
    """自動枝刈りループの最終結果と監査メトリクスを保持する。"""

    surviving_components: list[Component]
    pruned_components: list[Component]
    initial_score: EvaluationScore
    final_score: EvaluationScore
    step_logs: list[PruningStepLog]
    evaluation_calls: int

    @property
    def tokens_saved(self) -> int:
        """枝刈りによって削減された総推定トークン数を返す。"""
        return max(0, self.initial_score.active_tokens - self.final_score.active_tokens)


@dataclass
class _PruningContext:
    """ループ実行中の状態・ベースライン・メモ化キャッシュを一元管理する内部コンテキスト。"""

    state: SystemState
    test_cases: Sequence[TestCase]
    pipeline_runner: PipelineRunner
    baseline_score: EvaluationScore
    cache: dict[frozenset[str], EvaluationScore] = field(default_factory=dict)
    evaluation_calls: int = 0

    def evaluate(self, components: Sequence[Component]) -> EvaluationScore:
        """同一構成の重複推論を防ぐため、コンポーネントID集合でメモ化してオラクルを呼び出す。"""
        key = frozenset(c.id for c in components)
        if key not in self.cache:
            self.evaluation_calls += 1
            self.cache[key] = evaluate_system(
                components,
                self.test_cases,
                self.pipeline_runner,
            )
        return self.cache[key]

    def record_step(
        self,
        phase: str,
        target_comps: Sequence[Component],
        trial_score: EvaluationScore,
        outcome: PruningOutcome,
    ) -> None:
        """事後のPolars分析のため、各試行のスコア推移と削減トークン数を記録する。"""
        tokens_delta = trial_score.active_tokens - self.baseline_score.active_tokens
        log_entry = PruningStepLog(
            step_index=len(self.state.step_logs) + 1,
            phase=phase,
            target_ids=tuple(c.id for c in target_comps),
            categories=tuple(c.category for c in target_comps),
            baseline_pass_rate=self.baseline_score.pass_rate,
            trial_pass_rate=trial_score.pass_rate,
            tokens_delta=tokens_delta,
            outcome=outcome,
        )
        self.state.step_logs.append(log_entry)


def _group_into_units(components: Sequence[Component]) -> list[PruningUnit]:
    """共依存するSKILLとHOOK(同一group_id)が別々に抜かれて偽陰性になるのを防ぐためバンドル化する。"""
    units: list[PruningUnit] = []
    seen_groups: set[str] = set()
    for comp in components:
        if comp.group_id is None:
            units.append((comp,))
        elif comp.group_id not in seen_groups:
            seen_groups.add(comp.group_id)
            bundle = tuple(c for c in components if c.group_id == comp.group_id)
            units.append(bundle)
    return units


def _flatten_units(units: Sequence[PruningUnit]) -> list[Component]:
    """バンドル単位のリストを評価用のフラットなComponentリストへ展開する。"""
    return [comp for unit in units for comp in unit]


def _unit_key(unit: PruningUnit) -> str:
    """バンドル単位を一意に識別するキー文字列を生成する。"""
    return "|".join(c.id for c in unit)


def _split_units(units: Sequence[PruningUnit], n: int) -> list[list[PruningUnit]]:
    """ddminアルゴリズムに基づき、要素群をほぼ均等なn個のチャンクに分割する。"""
    chunks: list[list[PruningUnit]] = []
    start = 0
    total = len(units)
    for i in range(n):
        size = (total - start) // (n - i)
        chunks.append(list(units[start : start + size]))
        start += size
    return [chunk for chunk in chunks if chunk]


def _try_ddmin_complement_step(
    ctx: _PruningContext,
    units: list[PruningUnit],
    chunks: Sequence[Sequence[PruningUnit]],
) -> list[PruningUnit] | None:
    """各チャンクを抜いた補集合を順に検証し、ベースライン以上なら塊ごと削除確定する。"""
    for chunk in chunks:
        dropped_keys = {_unit_key(u) for u in chunk}
        complement_units = [u for u in units if _unit_key(u) not in dropped_keys]
        trial_comps = _flatten_units(complement_units)
        dropped_comps = _flatten_units(chunk)
        trial_score = ctx.evaluate(trial_comps)

        if trial_score.is_acceptable_against(ctx.baseline_score):
            ctx.record_step("ddmin", dropped_comps, trial_score, "PRUNED")
            ctx.state.active_components = trial_comps
            if trial_score.pass_rate > ctx.baseline_score.pass_rate:
                ctx.baseline_score = trial_score
            return complement_units

        ctx.record_step("ddmin", dropped_comps, trial_score, "KEPT")
    return None


def _run_ddmin_loop(ctx: _PruningContext) -> None:
    """Zellerのddminにより、前半50%/後半50%の2分割から段階的に粒度を細かくしてO(log N)で枝刈りする。"""
    units = _group_into_units(ctx.state.active_components)
    n = 2
    while len(units) >= 2:
        chunks = _split_units(units, min(n, len(units)))
        reduced = _try_ddmin_complement_step(ctx, units, chunks)
        if reduced is not None:
            units = reduced
            n = max(n - 1, 2)
            continue
        if n >= len(units):
            break
        n = min(len(units), n * 2)


def _run_linear_loop(ctx: _PruningContext) -> None:
    """HOW_TO優先順で1単位ずつアブレーションを行うwhile Trueループ。スコア向上時は再走査する。"""
    tested_keys: set[str] = set()
    while True:
        units = _group_into_units(ctx.state.active_components)
        candidates = [u for u in units if _unit_key(u) not in tested_keys]
        if not candidates:
            break

        target_unit = candidates[0]
        target_key = _unit_key(target_unit)
        tested_keys.add(target_key)
        trial_comps = _flatten_units([u for u in units if _unit_key(u) != target_key])
        trial_score = ctx.evaluate(trial_comps)

        if trial_score.is_acceptable_against(ctx.baseline_score):
            ctx.record_step("linear", target_unit, trial_score, "PRUNED")
            ctx.state.active_components = trial_comps
            if trial_score.pass_rate > ctx.baseline_score.pass_rate + 1e-9:
                ctx.baseline_score = trial_score
                tested_keys.clear()
        else:
            ctx.record_step("linear", target_unit, trial_score, "KEPT")


def _apply_dead_hook_prepruning(
    state: SystemState,
    config: PruningConfig,
    baseline_rate: float,
) -> None:
    """本番テレメトリで発火回数0のHOOKを、テストスイート実行前に機械的に除外するため。"""
    if config.hook_monitor is None:
        return
    dead_ids = set(
        config.hook_monitor.find_naturally_dead_hooks(config.min_hook_observations)
    )
    dead_comps = [c for c in state.active_components if c.kind == "HOOK" and c.id in dead_ids]
    if not dead_comps:
        return
    state.active_components = [
        c for c in state.active_components if not (c.kind == "HOOK" and c.id in dead_ids)
    ]
    tokens_removed = -sum(c.token_estimate for c in dead_comps)
    state.step_logs.append(
        PruningStepLog(
            step_index=len(state.step_logs) + 1,
            phase="pre_telemetry",
            target_ids=tuple(c.id for c in dead_comps),
            categories=tuple(c.category for c in dead_comps),
            baseline_pass_rate=baseline_rate,
            trial_pass_rate=baseline_rate,
            tokens_delta=tokens_removed,
            outcome="DEAD_HOOK",
        )
    )


def _try_empty_shortcut(
    ctx: _PruningContext,
    initial_components: Sequence[Component],
) -> PruningReport | None:
    """素のモデルで100%通過する場合に後続の評価を省略して即座に全廃止レポートを生成するため。"""
    empty_score = ctx.evaluate([])
    if empty_score.pass_rate < 1.0 - 1e-9 or not ctx.state.active_components:
        return None
    initial_tokens = sum(c.token_estimate for c in initial_components)
    total_cases = len(ctx.test_cases)
    initial_score = EvaluationScore(1.0, total_cases, total_cases, initial_tokens)
    ctx.baseline_score = initial_score
    ctx.record_step("shortcut", ctx.state.active_components, empty_score, "SHORTCUT_ALL_OFF")
    ctx.state.active_components = []
    return PruningReport(
        surviving_components=[],
        pruned_components=list(initial_components),
        initial_score=initial_score,
        final_score=empty_score,
        step_logs=ctx.state.step_logs,
        evaluation_calls=ctx.evaluation_calls,
    )


def prune_skills_and_hooks(
    initial_components: Sequence[Component],
    test_cases: Sequence[TestCase],
    pipeline_runner: PipelineRunner,
    config: PruningConfig | None = None,
) -> PruningReport:
    """外部の決定論的テストのみを審判として、不要または有害なSKILLとHOOKを機械的に削ぎ落とす。"""
    cfg = config or PruningConfig()
    state = SystemState(initial_components)
    ctx = _PruningContext(
        state=state,
        test_cases=test_cases,
        pipeline_runner=pipeline_runner,
        baseline_score=EvaluationScore(0.0, 0, len(test_cases), state.total_tokens),
    )
    _apply_dead_hook_prepruning(state, cfg, 0.0)
    shortcut_report = _try_empty_shortcut(ctx, initial_components)
    if shortcut_report is not None:
        return shortcut_report

    initial_score = ctx.evaluate(state.active_components)
    ctx.baseline_score = initial_score
    unit_count = len(_group_into_units(state.active_components))
    if cfg.strategy == "ddmin" or (cfg.strategy == "auto" and unit_count >= cfg.ddmin_threshold):
        _run_ddmin_loop(ctx)
    _run_linear_loop(ctx)

    surviving_ids = {c.id for c in state.active_components}
    pruned = [c for c in initial_components if c.id not in surviving_ids]
    return PruningReport(
        surviving_components=list(state.active_components),
        pruned_components=pruned,
        initial_score=initial_score,
        final_score=ctx.evaluate(state.active_components),
        step_logs=state.step_logs,
        evaluation_calls=ctx.evaluation_calls,
    )
