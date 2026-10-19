# Geminis_Brain (v2.0: Self-Evolving & Self-Pruning Agent Architecture)

LLMに自己言及（メタ認知）をさせず、**外部の決定論的テストスイートのみをオラクル（審判）**として、`SKILL` や `HOOK` を自律的に獲得・淘汰（新陳代謝）するエージェント脳フレームワークです。

---

## 1. なぜ「静的なスキル集」ではなく「再帰的自己最適化ループ」なのか

従来のエージェント設定集（第1世代）は、エラーや不適合が起きるたびにプロンプトルール（`SKILL`）や出力補正（`HOOK`）を**足し算（獲得）**し続ける構造でした。しかし、ベースとなるLLMが新世代へアップデートされると、以下の破綻（小説家のパラドックス）が生じます。

1. **負の相互作用（Over-constraining）**: 旧モデルの弱点を補うために書いた思考手順の強制（`HOW_TO` SKILL）が、新モデルの高度な推論を逆に阻害し、精度を低下させる。
2. **メタ認知の罠**: LLM自身に「このSKILLはもう不要か？」と尋ねると、賢いモデルほど「念のため残しておきましょう」と保守的な回答（ハルシネーション）をするため、自律的な削減ができない。

本リポジトリ（第2世代）は、**「LLMには作業（タスク実行）だけを行わせ、SKILL/HOOKの要否判定は外部の決定論的Pythonコードが下す」**という役割の完全分離により、この問題を解決します。

---

## 2. 全体アーキテクチャ（獲得と淘汰の非対称ループ）

```text
[初期状態: 全SKILL・HOOKのリスト (HOW_TO 優先ソート)]
       │
       ├─ 0-A. 本番テレメトリで発火回数 0 の「自然死HOOK」を事前一括除去
       ├─ 0-B. 全OFF（素のモデル）でテスト100%通過なら全廃止ショートカット (O(1))
       │
       ▼
┌─▶ while True: (ddmin チャンク分割 O(log N) ＋ 個別アブレーション)
│      │
│      ├─ 1. 削除候補のSKILL/HOOKチャンク（または共依存バンドル）を一時無効化
│      │     └─ 未検証候補がなくなれば break (1-Minimal 極小集合へ収束)
│      │
│      ├─ 2. 決定論的オラクル（Pydantic Schema / Regex / AST品質 / Pytest）で評価
│      │
│      ├─ [判定: PASS（既存通過ケースの退行ゼロ ＆ スコア維持・向上）]
│      │     ├─ 「不要または有害な拘束具」とみなしてアーカイブ確定
│      │     └─ スコアが向上した場合は baseline_score を上方修正（負の相互作用の解消）
│      │
│      └─ [判定: FAIL（テスト退行または精度低下）]
│            └─ 「まだ必要なドメイン知識/ガードレール」として100%即時ロールバック
└──────┘
       │
       ▼
[出力: 最小構成にダイエットされたSKILL・HOOK群 ＋ Polars Lazy 監査レポート]
```

---

## 3. リポジトリ構成

```text
Geminis_Brain/
├── GEMINI.md                     # グローバルエージェント規約
├── src/auto_skill_pruner/        # 【コア】決定論的自動枝刈りエンジン
│   ├── models.py                 # HOW_TO優先ソート・パレート非退行スコア比較
│   ├── oracle.py                 # Schema / Regex / Python AST 決定論的オラクルと複数回試行ガード
│   ├── pruner.py                 # Zellerのddmin対数圧縮ループ ＋ 線形while Trueループ
│   ├── hook_monitor.py           # スライディングウィンドウによるHOOK自然死観測モニター
│   ├── file_manager.py           # 実SKILL.md群のステージング退避と失敗時100%ロールバック
│   ├── analytics.py              # Polars LazyFrame メソッドチェーンによる有害SKILL特定と集計
│   └── cli.py                    # バッチ実行用 CLI エントリポイント
├── skills/                       # 【初期シードSKILL群】物理ゲートと静的機械ルール
│   ├── auto-skill-pruner/        # 自動枝刈りプロトコル定義
│   ├── hypothesis-driven-editor/ # 仮説ログゲートと3レイヤー段階的アプローチ
│   ├── python-polars-expert/     # 1関数30行・引数4個・ネスト2階層・Polars Lazy強制
│   ├── quality-guard/            # ISO9001 PDCAゲートと物理5Sクリーンアップ
│   ├── self-evolution/           # 不適合からの機械的ルール獲得とパターンカタログ
│   ├── task-tdd-expert/          # 実装前Web検索ゲートとTDDサイクル
│   ├── ux-designer/              # CSS変数強制・ARIA必須・破壊操作二重確認ガード
│   └── c-drive-cleanup/          # ストレージ・仮想ディスク物理圧縮
├── knowledge/                    # 【普遍的ドメイン知識 (WHAT_SPEC)】
│   ├── ipa/                      # システム設計・セキュリティ公的基準
│   ├── math/ , stats/            # 数理・統計モデル根拠
│   ├── python3/ , practices/     # 言語仕様・エンジニアリングプラクティス
│   ├── ds-expert/ , ds-advanced/ # データサイエンス・モデリング
│   ├── ux-psychology/            # 43のUX心理学法則
│   └── e-cert/                   # 認証・認可・電子証明書
└── tests/                        # 3層検証＋ドッグフーディングAST品質テストスイート
```

---

## 4. クイックスタート (`uv` 管理)

```bash
# 1. 全テストスイート（単体・統合・38スキルddmin検証・自己AST品質検証）の実行
uv run pytest -v

# 2. 厳格な型チェックと静的解析
uv run mypy --strict src tests
uv run ruff check src tests

# 3. 自動枝刈りセルフテストと監査レポート出力
uv run python -m auto_skill_pruner.cli --self-test --report-out reports/audit_report.md
```
