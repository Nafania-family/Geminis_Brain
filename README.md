# auto-skill-pruner

LLMに自己言及（メタ認知）をさせず、外部の決定論的テストスイートのみをオラクル（審判）として、不要・有害な `SKILL` や `HOOK` を機械的に削ぎ落とす**自動枝刈り（Auto-Pruning）基盤**です。

## アーキテクチャの核（なぜこの設計か）

1. **決定論的オラクルとの完全分離 (`oracle.py`)**:
   LLMに「このSKILLは不要か？」と尋ねると保守的なハルシネーションが生じるため、LLMにはタスク推論のみを行わせ、Pydantic JSON Schema 検証・正規表現 NG ワード検査・Python AST 静的品質検査・任意テスト関数のみによって合否を判定します。
2. **負の相互作用の解消とパレート非退行保証 (`models.py`, `pruner.py`)**:
   旧モデル向けの思考手順強制（`HOW_TO`）から優先的にアブレーションを行い、それを抜いたことでスコアが向上した場合は `baseline_score` を即座に上方修正します。さらに、チャンク削除時に「テストAが直りテストBが壊れて平均点が相殺される」現象を防ぐため、`baseline.passed_case_ids.issubset(trial.passed_case_ids)` による個別テストケースの非退行（パレート優越）を強制します。
3. **Zeller の `ddmin` による $O(\log N)$ チャンク枝刈りと共依存バンドル (`pruner.py`)**:
   大量の SKILL 群に対し、分割数 $n=2$（前半50%・後半50%）から補集合検証を開始し、段階的に粒度を細かくする Delta Debugging (`ddmin`) と個別 `while True` ループを組み合わせ、1-Minimal（どの1要素を抜いてもスコアが落ちる極小集合）へ高速に収束させます。`group_id` を共有する共依存 SKILL/HOOK は同一バンドルとして一括着脱されます。
4. **HOOK の自然死（Natural Death）観測 (`hook_monitor.py`)**:
   直近 $N$ 回（デフォルト1000回）の推論で `except` 補正ロジックが一度も発火しなかった HOOK をスライディングウィンドウで検知し、テストを回す前に機械的に除外します。
5. **トランザクション・ロールバック保証 (`file_manager.py`) と Polars Lazy 監査 (`analytics.py`)**:
   実ディレクトリ上の `SKILL.md` を操作する際は一時ステージング領域へ退避し、テスト失敗時や例外発生時には `100%` 自動ロールバックします。全試行履歴は Polars の `LazyFrame` メソッドチェーンで集計され、Markdown 監査レポートとして出力されます。

## 実行方法 (`uv` 管理)

```bash
# 全テストスイート（単体・統合・実環境38スキル大規模検証・自己AST品質検証）の実行
uv run pytest -v

# 型チェックおよび静的解析
uv run mypy --strict src tests
uv run ruff check src tests

# CLI によるセルフテスト枝刈りと監査レポート生成
uv run python -m auto_skill_pruner.cli --self-test --report-out reports/audit_report.md
```
