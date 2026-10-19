import logging
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType

from typing_extensions import Self

from auto_skill_pruner.models import Component, ComponentCategory, TestCase
from auto_skill_pruner.oracle import PipelineRunner
from auto_skill_pruner.pruner import (
    PruningConfig,
    PruningReport,
    prune_skills_and_hooks,
)

logger = logging.getLogger(__name__)

_HOW_TO_KEYWORDS = ("手順", "思考", "必ず", "強制", "step by step", "how_to", "chain of thought")


def _infer_category(content: str) -> ComponentCategory:
    """frontmatterの指定または思考手順強制キーワードの有無からHOW_TO/WHAT_SPECを決定論的に分類する。"""
    cat_match = re.search(r"^category:\s*(HOW_TO|WHAT_SPEC)\s*$", content, re.MULTILINE)
    if cat_match:
        val = cat_match.group(1)
        return "HOW_TO" if val == "HOW_TO" else "WHAT_SPEC"
    lowered = content.lower()
    if any(kw in lowered for kw in _HOW_TO_KEYWORDS):
        return "HOW_TO"
    return "WHAT_SPEC"


def load_skills_from_directory(skills_root: Path) -> list[Component]:
    """実ディレクトリ配下のSKILL.mdを走査し、ファイルパス紐付きのComponentリストを生成する。"""
    if not skills_root.exists():
        return []
    components: list[Component] = []
    for skill_file in sorted(skills_root.glob("*/SKILL.md")):
        skill_id = skill_file.parent.name
        content = skill_file.read_text(encoding="utf-8")
        category = _infer_category(content)
        components.append(
            Component(
                id=skill_id,
                kind="SKILL",
                category=category,
                content=content,
                file_path=str(skill_file.resolve()),
            )
        )
    return components


class SkillFileTransaction:
    """ファイルシステム上のSKILL無効化試行と、失敗・例外時の100%ロールバックを保証する。

    なぜステージング退避ディレクトリを使うか:
    アブレーション試行中にプロセス中断や例外が発生しても、元のSKILLファイルを失わず
    __exit__ で確実に元のパスへ復元できるようにするため。
    """

    def __init__(self, skills_root: Path) -> None:
        self._skills_root = skills_root.resolve()
        self._staging_dir = Path(tempfile.mkdtemp(prefix="skill_pruner_tx_"))
        self._tracked_files: dict[str, tuple[Path, Path]] = {}
        self._register_initial_files()

    def _register_initial_files(self) -> None:
        """トランザクション開始時点の全SKILL.mdをステージング領域へバックアップする。"""
        if not self._skills_root.exists():
            return
        for skill_file in sorted(self._skills_root.glob("*/SKILL.md")):
            skill_id = skill_file.parent.name
            backup_path = self._staging_dir / skill_id / "SKILL.md"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, backup_path)
            self._tracked_files[skill_id] = (skill_file.resolve(), backup_path)

    def sync_active_files(self, active_components: Sequence[Component]) -> None:
        """現在有効なSKILLのみをディスク上に存在させ、無効化対象を一時消去状態にする。"""
        active_ids = {c.id for c in active_components}
        for skill_id, (orig_path, backup_path) in self._tracked_files.items():
            if skill_id in active_ids and not orig_path.exists():
                orig_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, orig_path)
            if skill_id not in active_ids and orig_path.exists():
                orig_path.unlink()

    def rollback_all(self) -> None:
        """退避バックアップから全SKILL.mdを元のパスへ完全に復元する。"""
        for orig_path, backup_path in self._tracked_files.values():
            if backup_path.exists():
                orig_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, orig_path)

    def commit_pruned(self, pruned_components: Sequence[Component], archive_dir: Path) -> None:
        """まず全ファイルを復元した上で、削除確定したSKILLのみをアーカイブ先へ移動する。"""
        self.rollback_all()
        for comp in pruned_components:
            pair = self._tracked_files.get(comp.id)
            if pair is None:
                continue
            orig_path, backup_path = pair
            dest = archive_dir / comp.id / "SKILL.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, dest)
            if orig_path.exists():
                orig_path.unlink()

    def cleanup(self) -> None:
        """一時ステージングディレクトリを物理消去する。"""
        if self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            logger.warning("Exception detected during file pruning; rolling back all SKILL files.")
            self.rollback_all()
        self.cleanup()


def run_transactional_file_pruning(
    skills_root: Path,
    archive_dir: Path,
    test_cases: Sequence[TestCase],
    pipeline_runner: PipelineRunner,
) -> PruningReport:
    """実ディレクトリのSKILL群をディスク同期させながら枝刈りし、確定分をアーカイブへ移動する。"""
    initial_comps = load_skills_from_directory(skills_root)
    with SkillFileTransaction(skills_root) as tx:

        def synced_runner(comps: Sequence[Component], payload: str) -> str:
            tx.sync_active_files(comps)
            return pipeline_runner(comps, payload)

        report = prune_skills_and_hooks(
            initial_comps,
            test_cases,
            synced_runner,
            PruningConfig(strategy="auto"),
        )
        tx.commit_pruned(report.pruned_components, archive_dir)
        return report
