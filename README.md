# Geminis_Brain

決定論的テストスイートをオラクル（審判）として、LLMエージェントの指示定義（`SKILL`）および入出力補正処理（`HOOK`）を機械的に選別・最小化するフレームワークです。

---

## 1. 解決する課題と設計原則

LLMパイプラインにプロンプト指示（`SKILL`）や出力補正（`HOOK`）を追加し続けると、モデルの更新時に「モデル単体で達成可能な冗長指示」や「推論を阻害する過拘束な指示」が残留し、精度の低下とトークン消費の増大を引き起こします。また、LLM自身にプロンプトの要否を判定させると、自己正当化バイアスにより不要な指示が維持されます。

本フレームワークは以下の3原則によって構成要素を自動最小化します。

1. **評価と推論の分離 ([`oracle.py`](src/auto_skill_pruner/oracle.py))**:
   LLMはタスクの推論実行のみを担当し、構成要素の要否判定は外部の決定論的検証器（Pydantic JSON Schema、正規表現、Python AST静的解析、`pytest`）のみが行います。
2. **パレート非退行を伴う `ddmin` 枝刈り ([`pruner.py`](src/auto_skill_pruner/pruner.py))**:
   思考手順を強制する `HOW_TO` カテゴリから優先的に無効化を試行します。大量の要素に対しては Delta Debugging (`ddmin`) により $O(\log N)$ でチャンク単位の削除を行い、既存通過テストケースの退行がゼロ（`baseline.passed_case_ids.issubset(trial.passed_case_ids)`）かつ通過率が維持・向上した構成のみを採択します。削除により通過率が向上した場合はベースラインを即座に上方修正します。
3. **未発火 `HOOK` の自動廃止 ([`hook_monitor.py`](src/auto_skill_pruner/hook_monitor.py))**:
   直近 $N$ 回の推論において例外補正（`except` ブロック）の発火回数が `0` である `HOOK` をスライディングウィンドウで検出し、アブレーション実行前に機械的に除外します。

---

## 2. アーキテクチャと処理フロー

```text
[入力: SKILL / HOOK 群 + 決定論的テストスイート]
       │
       ├─ 1. 直近N回の推論で発火回数 0 の HOOK を除外 (HookTelemetryMonitor)
       ├─ 2. 全要素OFF（素のモデル）で全テスト通過なら全要素を廃止 (O(1))
       │
       ▼
┌─▶ while True: (ddmin チャンク分割 + 個別アブレーション)
│      │
│      ├─ 対象チャンク（または同一 group_id の共依存バンドル）を一時無効化
│      ├─ 決定論的オラクル（Schema / Regex / AST / Pytest）で全テストケースを評価
│      │
│      ├─ [既存通過ケースの退行なし & 通過率がベースライン以上]
│      │     ├─ 対象要素の削除を確定
│      │     └─ 通過率が向上した場合は baseline_score を上方修正
│      │
│      └─ [テスト退行または通過率低下]
│            └─ 必須要素として元の状態へロールバック
└──────┘
       │
       ▼
[出力: 1-Minimal（極小）な SKILL / HOOK 集合 + Polars Lazy 監査レポート]
```

---

## 3. ディレクトリ構成

```text
.
├── GEMINI.md                     # エージェント実行規約
├── src/auto_skill_pruner/        # 自動枝刈りエンジン本体
│   ├── models.py                 # ドメインモデル・優先度ソート・パレート非退行判定
│   ├── oracle.py                 # Schema / Regex / Python AST オラクル・複数回試行検証
│   ├── pruner.py                 # ddmin チャンク枝刈り・線形 while True ループ
│   ├── hook_monitor.py           # スライディングウィンドウによる HOOK 発火監視
│   ├── file_manager.py           # SKILL.md 群のトランザクション退避と自動ロールバック
│   ├── analytics.py              # Polars LazyFrame による削減トークン・有害要素集計
│   └── cli.py                    # バッチ実行用 CLI
├── skills/                       # バリデーション・開発ワークフロー用 SKILL 定義
├── knowledge/                    # ドメイン仕様・公的基準リファレンス (WHAT_SPEC)
└── tests/                        # 単体・統合・AST品質検証テストスイート
```

---

## 4. 実行方法 (`uv`)

```bash
# 全テストスイート（単体・統合・38要素ddmin検証・AST品質検証）の実行
uv run pytest -v

# 型チェックおよび静的解析
uv run mypy --strict src tests
uv run ruff check src tests

# CLI による枝刈り検証と Markdown 監査レポート生成
uv run python -m auto_skill_pruner.cli --self-test --report-out reports/audit_report.md
```

---

## 5. Python API 使用例

```python
from collections.abc import Sequence
from auto_skill_pruner import (
    Component,
    PruningConfig,
    TestCase,
    prune_skills_and_hooks,
)

components = [
    Component("legacy_cot", "SKILL", "HOW_TO", "Force rigid step-by-step output"),
    Component("tax_spec", "SKILL", "WHAT_SPEC", "Apply 8% reduced tax rate for food"),
]

test_cases = [
    TestCase("tc_tax", "calc_food_tax", lambda out: "RATE_8" in out),
]

def run_pipeline(active: Sequence[Component], prompt: str) -> str:
    active_ids = {c.id for c in active}
    return "RATE_8" if "tax_spec" in active_ids else "UNKNOWN"

report = prune_skills_and_hooks(
    components,
    test_cases,
    run_pipeline,
    PruningConfig(strategy="auto", trials_per_case=1),
)
# report.surviving_components -> [Component(id='tax_spec', ...)]
```
