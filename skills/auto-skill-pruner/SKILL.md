---
name: auto-skill-pruner
category: HOW_TO
description: 外部の決定論的テストをオラクル（審判）として、不要・有害なSKILLや未発火のHOOKをddminおよびwhile Trueループで機械的に削除するスキル。モデル更新時やスキル棚卸し時に使用する。
---

# Auto-Skill-Pruner (決定論的自動枝刈りゲート)

## 1. 判定原則（推論と評価の分離）

1. **LLMによる自己評価の禁止**:
   構成要素（`SKILL` / `HOOK`）の要否判定にLLMの主観的評価を使用しない。LLMは対象タスクの推論のみを実行し、合否判定は外部の決定論的検証コード（Pydantic Schema、正規表現、Python AST解析、`pytest`）のみで行う。
2. **`HOW_TO`（思考手順の指定）からの優先削除**:
   `HOW_TO` カテゴリの要素を `WHAT_SPEC`（ドメイン仕様）より先頭に配置してアブレーションを開始し、同一カテゴリ内では推定トークン消費量の大きい要素から順に検証する。
3. **パレート非退行条件**:
   要素を無効化した試行スコア `trial_score` の採択には、全体の通過率が `baseline_score` 以上（`trial.pass_rate >= baseline.pass_rate`）であり、かつベースラインで通過していた全テストケースが退行していないこと（`baseline.passed_case_ids.issubset(trial.passed_case_ids)`）を必須とする。削除により通過率が向上した場合は `baseline_score` を上方修正する。
4. **未発火 `HOOK` の事前除外**:
   直近 $N$ 回（デフォルト1000回）の推論において例外補正ブロックの発火回数が `0` である `HOOK` は、テストスイート実行前に除外する。

## 2. 実行コマンド (`uv`)

```bash
# 全テストスイートとAST品質ゲートの検証
uv run pytest -v

# 自動枝刈りの実行と監査レポート出力
uv run python -m auto_skill_pruner.cli --self-test --report-out reports/audit_report.md
```
