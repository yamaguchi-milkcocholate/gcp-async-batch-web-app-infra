# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GCPを使用した非同期バッチ処理Webアプリケーションのインフラストラクチャプロジェクト。PDF一括解析システムを対象に、Streamlit フロントエンド、Cloud Run バッチワーカー、Pub/Sub、Redis、Cloud Storage を組み合わせた長時間処理可能なアーキテクチャを構築する。

## Development Protocol: Spec-Driven Development (SDD)

**このプロジェクトでは、実装に先立って必ず仕様を定義する SDD (Spec-Driven Development) を採用している。**

### 必須ルール

1. **Spec First**: いきなりコードを書かず、まず `docs/03_specs/{spec-name}.md` に仕様を定義する
2. **Context Loading**: 実装開始前に以下を必ず読み込む
   - `docs/01_guidelines/` - 開発ガイドライン
   - `docs/02_architecture/` - アーキテクチャ設計
   - `docs/03_specs/` - 対象機能の仕様書
3. **Plan before Implementation**: 仕様に基づいた実装計画を提示してから実装を開始する
4. **Atomic Implementation**: 大規模な実装を避け、仕様内のタスク単位でインクリメンタルに実装・テストを繰り返す

### 仕様書の必須項目

各 `.md` 仕様書には以下を含める:

- **Project Vision**: 解決する課題と提供する価値
- **Input/Output**: データ形式、ソース、出力先
- **Infrastructure**: 使用するGCPリソースと共通基盤ノード

## Architecture

### System Components

- **Frontend**: Streamlit (Cloud Run) - ファイルアップロード、進捗表示
- **Message Broker**: Cloud Pub/Sub - 非同期実行トリガー
- **Batch Worker**: Python Processor (Cloud Run Jobs) - PDF解析処理
- **State Store**: Cloud Memorystore for Redis - 進捗ステータス共有
- **Object Storage**: Cloud Storage - PDFと結果ファイル一時保管（24時間TTL）

### Environment Abstraction

ストレージ操作は環境変数 `STORAGE_TYPE` で切り替える抽象化レイヤーを使用:

- **LOCAL**: ローカルファイルシステム (`./local_storage`) を使用、エミュレータ不要
- **GCP**: `google-cloud-storage` ライブラリで実際のGCSにアクセス

### Local Development (Docker Compose)

```
- app: Streamlit (localhost:8501, Hot Reload対応)
- worker: Python解析処理コンテナ
- redis: redis:7-alpine (データ永続化オフ)
- pubsub: Pub/Subエミュレータ (localhost:8085, PUBSUB_EMULATOR_HOST設定必須)
- storage: ./local_storage をボリュームマウント
```

## Infrastructure Management (Terraform)

- **必須**: すべてのGCPリソースはTerraformで管理、手動設定禁止
- **State管理**: 本番環境ではCloud Storageバックエンドを使用
- **モジュール化**: Cloud Run、Pub/Sub、Redis、GCSをモジュールとして定義
- **環境分離**: `environments/dev` と `environments/prod` で変数を分離、または tfvars で切り替え
- **TTL設定**: GCSライフサイクルルール（24時間削除）は `lifecycle_rule` ブロックで定義

### GCP Component Requirements

- **Cloud Run / Cloud Run Jobs**: タイムアウト1800秒(30分)以上、メモリ2GiB以上
- **Cloud Storage**: Lifecycle Management Rule `Age: 1` (1日経過で削除)
- **Cloud Memorystore (Redis)**: 最小サイズ（ステータス管理のみ）
- **IAP**: Google Workspace認証をフロントエンドに適用

## Python Coding Standards

### Package Management

- **ツール**: `uv` を必須使用
- **構成**: `apps/{app_name}/` ごとに `pyproject.toml` を配置し依存関係を隔離
- **共有ロジック**: `shared/python/` に配置し editable install または PYTHONPATH で参照

### Implementation Style

- **非同期ファースト**: API連携、DB操作は `asyncio` 使用、HTTPクライアントは `httpx` (requests非推奨)
- **厳格な型ヒント**: `typing` 活用、`Any` を極力避け、`mypy --strict` または `Pyright` 最高強度でエラーなし
- **データバリデーション**: 外部APIレスポンスは `Pydantic` モデルでパース

### Logic Design

- **冪等性**: 途中エラーでも再実行で正常終了する設計（動画生成・SNS投稿等）
- **ロギング**: `loguru` 使用、構造化ログ出力、判断理由をデバッグログに残す
- **設定管理**: `pydantic-settings` で `.env` 読み込み、型チェック、デフォルト値自動化
- **エラーハンドリング**: 外部LLM APIのタイムアウト・レートリミット想定、`tenacity` でリトライ戦略実装

### Code Quality

- **ドキュメント**: Google Style Docstring、AIへの指示内容やプロンプト意図をコメントに残す
- **静的解析**: `ruff` でLintとFormat、PR作成前に必ず実行

## Data Structure (Redis)

Key format: `job:{job_id}`

```json
{
  "status": "processing",
  "progress": 45,
  "message": "Page 5/12 analyzing...",
  "result_url": "",
  "error_msg": "",
  "updated_at": "2026-02-12T05:43:00Z"
}
```

## Important Considerations

- **セキュリティ**: データは24時間TTLで自動削除
- **UX**: 最大30分の待機時間中、リアルタイム進捗表示
- **スケーラビリティ**: Pub/Subキューイングで同時アップロード負荷制御
- **リトライ**: Pub/Subデッドレターポリシーで失敗処理の再試行検討
