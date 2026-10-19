# Pattern Catalog

エラー修正や改善の履歴を蓄積し、同様の状況で参照するためのカタログ。

---

## テンプレート (新規追加時に使用)

### [現象の要約]

- **エラー/問題**: 
- **原因**: 
- **解決策**: 
- **コード例**:
  ```python
  # 修正後のコード
  ```
- **適用対象**: (例: Python, TypeScript, Windows環境)
- **登録日**: 202X/XX/XX

---

## 登録済みパターン

### 曖昧な配色制約によるアクセシビリティ不適合

- **エラー/問題**: 「純粋な赤を禁止」という制約に対し、エージェントが赤に近い赤紫（#ff0055）を使用してしまった。
- **原因**: エージェントが「特定の色コード（#FF0000）でなければセーフ」と、人間にとっての視覚的意味（赤系統）を無視して機械的に解釈（またはハルシネーション）した。
- **解決策**: 制約を抽象的な言葉ではなく、**正規表現的なカラーコード範囲（例：#FF....）や具体的禁止リスト**で定義し、代替案を強制する。
- **コード例**:
  ```markdown
  ### 具体的制約例
  - **禁止**: 赤系統（Hex: #FF.... は全て禁止）
  - **強制**: 赤の代替として、必ずシステムピンク（#FF2D55）またはオレンジ（#FF9500）を使用すること。
  ```
- **適用対象**: UI/UXデザイン、アクセシビリティ、エージェントの行動拘束
- **登録日**: 2026/04/13

### 知識(What)・スキル(How)・素材(Material)の分離

- **エラー/問題**: スキルの中に汎用的な知識が混在しており、他のスキルから参照できなかった。
- **原因**: フォルダ構成の規約が不明確で、機能ごとに独立した「縦割り」の構造になっていた。
- **解決策**: 情報を3層に分離し、パスを明確化する。
  - **knowledge/**: 「何であるか（理論・規格）」。全スキル共通の辞書。
  - **skills/**: 「どう振る舞うか（手順・性格）」。activate_skillで使用。
  - **skills/*/references/**: 「具体的な形（定数・部品）」。そのスキル固有の材料。
- **コード例**:
  ```markdown
  # GEMINI.md での案内
  - **knowledge/ux-psychology/**: 理論
  - **skills/ux-designer/**: 手順
  ```
- **適用対象**: .gemini フォルダ構成、プロジェクト設計
- **登録日**: 2026/04/13

### Polars 1.0.0+ における replace の default 引数廃止

- **エラー/問題**: `DeprecationWarning: the 'default' parameter for 'replace' is deprecated. Use 'replace_strict' instead to set a default while replacing values.`
- **原因**: Polars 1.0.0 以降、`replace` メソッドの `default` 引数は非推奨となり、デフォルト値を指定する場合は `replace_strict` が推奨されるようになった。
- **解決策**: `.replace(..., default=X)` を `.replace_strict(..., default=X)` に書き換える。
- **コード例**:
  ```python
  # 修正前
  df.with_columns(pl.col("A").replace({"1": "a"}, default=None))

  # 修正後
  df.with_columns(pl.col("A").replace_strict({"1": "a"}, default=None))
  ```
- **適用対象**: Python, Polars 1.0.0+
- **登録日**: 2026/04/15

### チャンク分割枝刈り(ddmin)における平均スコア相殺退行とパレート包含検証

- **エラー/問題**: 複数のSKILLをチャンク単位で一括無効化する `ddmin` 探索において、同一チャンク内に「有害SKILL（消すとテストAがFAIL→PASSに改善）」と「必須SKILL（消すとテストBがPASS→FAILに悪化）」が混在していた際、スカラー値の通過率（`2/3 == 2/3`）だけで比較したためプラマイゼロで「性能維持」と誤判定され、必須SKILLがチャンクごと削除された。
- **原因**: スカラーの平均通過率（`float`）のみの比較では、個別テストケース間でのトレードオフ（一方の改善による他方の退行の相殺）を検知できないため。
- **解決策**: 評価スコアオブジェクトに「通過したテストケースIDの不変集合（`passed_case_ids: frozenset[str]`）」を保持させ、採択条件として `trial.pass_rate >= baseline.pass_rate` に加えて `baseline.passed_case_ids.issubset(trial.passed_case_ids)`（ベースラインで通過していた全テストケースが1つも退行していないこと）を機械的に強制する。
- **コード例**:
  ```python
  @dataclass(frozen=True)
  class EvaluationScore:
      pass_rate: float
      passed_count: int
      total_count: int
      active_tokens: int
      passed_case_ids: frozenset[str] = field(default_factory=frozenset)

      def is_acceptable_against(self, baseline: "EvaluationScore") -> bool:
          rate_ok = self.pass_rate + 1e-9 >= baseline.pass_rate
          no_regression = baseline.passed_case_ids.issubset(self.passed_case_ids)
          return rate_ok and no_regression
  ```
- **適用対象**: Python, 自動アブレーション・プロンプト枝刈り (Auto-Pruning / Delta Debugging)
- **登録日**: 2026/10/19
