---
name: task-tdd-expert
description: タスク管理、TDD、GitHub Flow、エラープロトコル、およびセキュリティを管理。具体性実装前のWeb検索物理ゲートを定義。詳細は references/workflow_details.md を参照。
---

# Task & TDD Expert (Web-Search First)

「我流の実装とお題目を排し、実装前に必ずWeb検索を実行して最新のベストプラクティスを強制する」

## 主要ワークフロー
1. **Web-Search Gate (実装前検索ゲート)**:
   具体的なコード実装、仕様設計、またはアルゴリズムの選定を行う前に、**必ず最低1回以上のWeb検索 (search_web) を実行**し、最新のベストプラクティス、ドキュメント、既存の解決策を確認・タスクログに記録しなければなりません。
2. **Task**: `tasks/` フォルダでの物理的な背景・目的・検索結果の管理。
3. **TDD**: テスト作成 (Red) -> 実装 (Green) -> リファクタ。
4. **Git**: feature ブランチ & 1機能1コミットの徹底。
5. **Security**: IPA セキュアコーディング準拠（入力検証、エラーの非開示、シークレット管理）。

## オンデマンド参照
具体的なコミット基準、IPA 規約、サブエージェント活用、およびWeb検索ゲートの詳細手順は以下を参照すること。
- [開発ワークフロー・詳細](references/workflow_details.md)
- [Web検索物理ゲート・手順詳細](references/workflow_details.md#1-実装前web検索物理ゲート-the-web-search-gate)
