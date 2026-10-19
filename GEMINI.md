## Gemini Added Memories

# 厳守

- 回答や出力、プラン、タスクなどは全て日本語を使うこと
- コメント、仕様書などは「何をした」ではなく、**「なぜそうした」**を書く
- 自明なコードコメントは書かない、不要な空白は削除、新規ファイル末尾には改行を入れる

# スキル活用方針（獲得と淘汰の非対称ループ）

複雑なタスクや特定のドメイン作業を行う際は、以下の専門スキルを有効化して使用すること。また、モデルの世代交代時は `auto-skill-pruner` によって不要・有害化した `HOW_TO` スキルや自然死した `HOOK` を決定論的に削ぎ落とすこと。

1. **`python-polars-expert`**: Pythonicな実装（1関数30行・引数4個・ネスト2階層・型ヒント100%）、Polars Lazyチェーン、`uv` パッケージ管理。
2. **`hypothesis-driven-editor`**: 物理的仮説ログの義務化と、LowからHigh（局所から構造）への段階的アプローチをコード・ファイル編集およびデバッグ全般に強制する手法。
3. **`auto-skill-pruner`**: LLMにメタ認知をさせず、外部の決定論的テストスイートと `ddmin` アルゴリズムのみを審判として、不要・有害な SKILL や自然死した HOOK を機械的に削ぎ落とす自動枝刈り基盤。

# 運用ガイドライン (CLAUDE.md 準拠)

- **技術スタック**: Pythonは `uv` 管理を徹底。
  - パッケージのインストール、スクリプトの実行、仮想環境の作成など、すべてのPython操作において **`pip` や `python -m venv` を直接使わず、常に `uv` をデフォルトで使用すること**（例: `uv pip install`, `uv run`, `uv venv`, `uv init`）。
- **リスク判定**:
  - 🟢 通常: テスト追加・ドキュメント修正・新規ファイル
  - 🟡 標準: 既存コード修正・設定変更（revert可能）
  - 🟠 強化: 複数機能に影響・API変更 → 影響分析必須
  - 🔴 最高: DB変更・cron変更・デプロイ → Worktreeまたは隔離環境を検討
- **変更管理**: 大幅な変更前には `git add` で現状を保存し、変更後は `git diff HEAD` で自己レビューを行う。

# 知識ベース (Knowledge Base / WHAT_SPEC)

設計や実装の根拠が必要な場合、以下の専門知識をオンデマンドで参照すること。

- **`knowledge/ipa/`**: システム設計、セキュリティ（AU）、DB、NW等の公的基準。
- **`knowledge/ux-psychology/`**: 43のUX心理学法則。UI/UX設計の論理的根拠。
- **`knowledge/python3/`**: Pythonの基本構文、OOP、標準ライブラリ、ベストプラクティス。
- **`knowledge/math/`**, **`knowledge/stats/`**: アルゴリズム、データ分析の数学的・統計的根拠。
- **`knowledge/ds-expert/`**, **`knowledge/ds-advanced/`**: 高度なデータ分析、モデリング、データエンジニアリング。
- **`knowledge/practices/`**: コーディングスタイル、テスト、セキュリティ、ワークフローのベストプラクティス。
- **`knowledge/e-cert/`**: 認証・認可、電子証明書等のセキュリティ知識。

# GitHub Operations

- GitHubのリソース操作は、`gh` コマンド（GitHub CLI）を優先的に使用する。
