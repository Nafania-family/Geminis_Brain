import logging
from collections import deque
from collections.abc import Callable, Sequence

from auto_skill_pruner.models import Component

logger = logging.getLogger(__name__)


class HookTelemetryMonitor:
    """本番推論におけるHOOKの補正発火回数を監視し、自然死したHOOKを機械的に特定する。

    なぜスライディングウィンドウ(deque)を使うか:
    新モデルへ切り替えた直近N回(例: 1000回)の推論結果のみを対象として発火回数ゼロを判定し、
    旧モデル時代の古い発火履歴が削除判定を阻害するのを防ぐため。
    """

    def __init__(self, window_size: int = 1000) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self._window_size = window_size
        self._history: dict[str, deque[bool]] = {}

    def record_execution(self, hook_id: str, triggered_fallback: bool) -> None:
        """HOOKが呼び出された際に、except補正ロジックが発火したかどうかを記録する。"""
        if hook_id not in self._history:
            self._history[hook_id] = deque(maxlen=self._window_size)
        self._history[hook_id].append(triggered_fallback)

    def execute_hook(
        self,
        hook_id: str,
        primary_fn: Callable[[str], str],
        fallback_fn: Callable[[str], str],
        raw_output: str,
    ) -> str:
        """通常処理を優先実行し、例外時のみHOOK補正を発火させてテレメトリを自動収集するため。"""
        try:
            result = primary_fn(raw_output)
            self.record_execution(hook_id, triggered_fallback=False)
            return result
        except (ValueError, KeyError, TypeError, RuntimeError, LookupError):
            self.record_execution(hook_id, triggered_fallback=True)
            return fallback_fn(raw_output)

    def get_trigger_count(self, hook_id: str) -> int:
        """直近ウィンドウ内で当該HOOKの補正ロジックが発火した回数を返す。"""
        records = self._history.get(hook_id)
        if not records:
            return 0
        return sum(1 for triggered in records if triggered)

    def get_observation_count(self, hook_id: str) -> int:
        """直近ウィンドウ内で当該HOOKが観測された総推論回数を返す。"""
        records = self._history.get(hook_id)
        return len(records) if records else 0

    def find_naturally_dead_hooks(self, min_observations: int = 1000) -> list[str]:
        """十分な推論回数を経ても一度も発火しなかったHOOKを自然死として抽出するため。"""
        dead_hooks: list[str] = []
        for hook_id, records in sorted(self._history.items()):
            if len(records) >= min_observations and not any(records):
                dead_hooks.append(hook_id)
        return dead_hooks

    def prune_dead_hooks(
        self,
        components: Sequence[Component],
        min_observations: int = 1000,
    ) -> list[Component]:
        """アブレーションループを回す前に、自然死したHOOKを無条件で一括除去するため。"""
        dead_set = set(self.find_naturally_dead_hooks(min_observations=min_observations))
        if dead_set:
            logger.info("Pruning naturally dead hooks: %s", sorted(dead_set))
        return [c for c in components if not (c.kind == "HOOK" and c.id in dead_set)]
