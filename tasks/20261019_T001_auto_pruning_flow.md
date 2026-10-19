# タスク管理・実装前Web検索ゲート記録 (20261019_T001)

## 1. 背景・目的
LLMのモデル更新に伴い、旧モデル向けに作成された思考手順の強制（`HOW_TO` SKILL）や出力補正（`HOOK`）が新モデルの推論能力を阻害する「負の相互作用」やトークン浪費を引き起こす問題を解決する。LLM自身の自己評価（メタ認知）を排除し、外部の決定論的テストスイートのみをオラクル（審判）として、`while True` ループおよび Delta Debugging (`ddmin`) によって不要な SKILL・HOOK を機械的に削ぎ落とす安定した自動枝刈り基盤（`auto-skill-pruner`）を実装する。

## 2. 実装前Web検索物理ゲート (The Web-Search Gate) 証拠記録

### ① 使用した検索クエリ
1. `"ddmin" "Delta Debugging" Zeller algorithm implementation python`
2. `LLM prompt ablation pruning automated evaluation deterministic testing`

### ② 参照した主要な公式ドキュメント・技術文献のURL
- **The Debugging Book - Delta Debugging (Andreas Zeller)**:
  `https://www.debuggingbook.org/html/DeltaDebugger.html`
- **Automated Prompt Ablation & Deterministic Evaluation Practices**:
  `https://www.deepeval.com/` / `https://www.evidentlyai.com/`

### ③ 採用する具体的なベストプラクティス（知見と採用理由）
1. **Zeller の `ddmin` アルゴリズムによる 1-Minimal（極小性）保証と $O(\log N)$ 圧縮**:
   - **採用理由**: 要素を1つずつ抜く線形探索 $O(N)$ では SKILL/HOOK 数が数十〜数百に達した際に評価コストが爆発するため。分割数 $n=2$（前半50%・後半50%）から開始し、単一チャンクでの通過確認（後半丸ごと廃棄）および補集合での通過確認を行い、削れない場合のみ $n = \min(2n, |C|)$ と粒度を細かくするアルゴリズムを採用することで、必須要素が少ない場合は $O(\log N)$ で一括廃棄し、最終的に「どの1要素を抜いてもスコアが落ちる」1-Minimal な極小集合へ収束させる。
2. **決定論的オラクルと辞書式スコア `(pass_rate, -token_cost)` の導入**:
   - **採用理由**: 確率的な揺らぎや同点判定時の曖昧さを排除するため。テスト通過率（`pass_rate`）がベースライン以上を維持し、かつトークン消費量が減少する構成を一意に採択する。また、邪魔な SKILL を削除して `pass_rate` が向上した際はベースラインを即座に上方修正（単調増加）し、システムの到達精度を引き上げる。
3. **冪等性 (`prune(prune(x)) == prune(x)`) とトランザクション・ロールバック**:
   - **採用理由**: 枝刈り処理の途中での例外発生やテスト失敗時に、スキルファイルやシステム状態が中途半端に破壊されるのを防ぐため。ファイルシステム上の操作には退避・復元（ロールバック）機構を備え、同じ入力とオラクルに対して常に同一の極小構成を返す決定論的冪等性を担保する。

## 3. 実装ステップ (TDD)
- [ ] Step 1 (🟢 Layer 1): ドメインモデル (`models.py`)、決定論的オラクル・バリデータ (`oracle.py`)、HOOK自然死モニター (`hook_monitor.py`) の単体テスト作成と実装
- [ ] Step 2 (🟡 Layer 2): `while True` 線形枝刈りおよび `ddmin` 高速チャンク枝刈りエンジン (`pruner.py`)、共依存バンドル制御、メモ化キャッシュの統合テスト作成と実装
- [ ] Step 3 (🟠 Layer 3): Polars Lazyチェーンによるテレメトリ分析 (`analytics.py`)、実ファイルシステムのトランザクション枝刈り (`file_manager.py`)、CLI エントリポイント (`cli.py`) のE2E検証
