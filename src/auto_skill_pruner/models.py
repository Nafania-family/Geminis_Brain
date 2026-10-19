from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

ComponentKind = Literal["SKILL", "HOOK"]
ComponentCategory = Literal["HOW_TO", "WHAT_SPEC"]
PruningOutcome = Literal["PRUNED", "KEPT", "SHORTCUT_ALL_OFF", "DEAD_HOOK"]


@dataclass(frozen=True)
class Component:
    """SKILLとHOOKの属性および共依存グループを不変値として保持する。

    なぜ不変(frozen=True)にするか:
    アブレーション試行中のリスト操作で意図しない状態書き換えを防ぎ、
    構成集合(frozenset)のハッシュキーとしてメモ化キャッシュに利用するため。
    """

    id: str
    kind: ComponentKind
    category: ComponentCategory
    content: str
    group_id: str | None = None
    file_path: str | None = None

    @property
    def token_estimate(self) -> int:
        """外部トークナイザに依存せず決定論的にトークン消費量を近似するため、文字長ベースの概算を返す。"""
        return max(1, (len(self.content) + 3) // 4)


@dataclass(frozen=True)
class TestCase:
    """決定論的オラクルが使用する入力と検証関数のペアを保持する。"""

    __test__ = False

    id: str
    input_payload: str
    deterministic_validator: Callable[[str], bool]


@dataclass(frozen=True)
class EvaluationScore:
    """テスト通過率と通過ケース集合を保持し、退行を許さないパレート優越比較を提供する。

    なぜpassed_case_idsの包含関係(issubset)を検査するか:
    チャンク単位でSKILLを抜いた際、「邪魔なSKILLが消えてテストAが通るようになったが、
    同時に必須SKILLも消えてテストBが落ち、平均点が偶然同じになる」という相殺退行を防ぐため。
    """

    pass_rate: float
    passed_count: int
    total_count: int
    active_tokens: int
    passed_case_ids: frozenset[str] = field(default_factory=frozenset)

    def is_acceptable_against(self, baseline: "EvaluationScore") -> bool:
        """ベースラインで通過していた全テストケースを維持しつつ、通過率が同等以上かを判定する。"""
        rate_ok = self.pass_rate + 1e-9 >= baseline.pass_rate
        no_regression = baseline.passed_case_ids.issubset(self.passed_case_ids)
        return rate_ok and no_regression


@dataclass(frozen=True)
class PruningStepLog:
    """枝刈りループの各ステップをPolarsで事後集計するため、構造化レコードとして保持する。"""

    step_index: int
    phase: str
    target_ids: tuple[str, ...]
    categories: tuple[str, ...]
    baseline_pass_rate: float
    trial_pass_rate: float
    tokens_delta: int
    outcome: PruningOutcome


def _component_sort_key(comp: Component) -> tuple[int, int, str]:
    """新モデルの推論を阻害しやすいHOW_TOかつトークン消費の大きい要素から先に削るため優先度を算出する。"""
    category_rank = 0 if comp.category == "HOW_TO" else 1
    return (category_rank, -comp.token_estimate, comp.id)


@dataclass
class SystemState:
    """現在有効なコンポーネント群と枝刈り履歴を管理する。"""

    active_components: list[Component] = field(default_factory=list)
    step_logs: list[PruningStepLog] = field(default_factory=list)

    def __init__(self, components: Sequence[Component]) -> None:
        self.active_components = sorted(components, key=_component_sort_key)
        self.step_logs = []

    @property
    def total_tokens(self) -> int:
        """現在有効な全SKILL・HOOKの総推定トークン数を算出する。"""
        return sum(c.token_estimate for c in self.active_components)
