---
name: auto-skill-pruner
category: HOW_TO
description: LLMにメタ認知をさせず、外部の決定論的テストのみをオラクル（審判）として、不要・有害なSKILLや自然死したHOOKをddminおよびwhile Trueループで機械的に削ぎ落とすスキル。モデル更新時やスキル肥大化時に使用する。
---

# Auto-Skill-Pruner (決定論的自動枝刈り・淘汰ゲート)

「LLMにプロンプトの要否を相談するのを一切禁じ、外部の決定論的テストスイートと `ddmin` アルゴリズムによって不要・有害な拘束具（SKILL/HOOK）を物理的に削ぎ落とす」

## 1. 鉄則（役割の完全分離）

1. **LLMによる自己評価（LLM-as-a-Judge）の完全禁止**:
   「このSKILLはもう不要か？」をLLMに尋ねてはなりません。LLMには対象タスクの実行（推論）のみを行わせ、採否判定は100%外部のPythonテストコード（Pydantic Schema、正規表現、Python AST解析、`pytest`）に委ねます。
2. **`HOW_TO`（思考手順の強制）からの優先削除**:
   モデルが進化した際、最初に陳腐化・有害化するのは `HOW_TO`（ステップバイステップの強制等）です。常に `HOW_TO` を先頭にソートしてアブレーション（切除実験）を開始し、`WHAT_SPEC`（ドメイン固有仕様）を後ろに配置します。
3. **パレート非退行条件（相殺退行の遮断）**:
   SKILLを抜いた試行スコア `trial_score` が採用されるには、全体の通過率が `baseline_score` 以上（`trial.pass_rate >= baseline.pass_rate`）であり、かつ**ベースラインで通過していた個別のテストケースが1つも退行していないこと（`baseline.passed_case_ids.issubset(trial.passed_case_ids)`）**を必須条件とします。邪魔なSKILLが消えて通過率が上がった場合は、`baseline_score` を即座に上方修正します。
4. **HOOKの自然死（Natural Death）観測**:
   出力補正用の `HOOK` にはスライディングウィンドウ（直近1000回）の発火カウンター（`HookTelemetryMonitor`）を設置し、`except` 補正ブロックの発火回数が `0` になった HOOK は無条件で廃止します。

## 2. 物理実行コマンド (`uv` 管理)

モデル更新時またはスキル棚卸し時は、以下のコマンドを実行して自動枝刈りと Polars Lazy 監査レポート出力を行います。

```bash
# 全テストスイートと自己AST品質ゲートの検証
uv run pytest -v

# 自動枝刈りループの実行とMarkdown監査レポート生成
uv run python -m auto_skill_pruner.cli --self-test --report-out reports/audit_report.md
```
