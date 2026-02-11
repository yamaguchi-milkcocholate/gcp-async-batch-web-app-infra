# Spec-Driven Development (SDD) Protocol

開発は、実装（コード）に先立ち、厳密な仕様（スペック）を定義することを絶対原則とする。これにより、AIアシスタントとの協働精度を最大化し、手戻りを最小化（省エネ）する。

---

## 🔄 SDD ライフサイクル詳細

### Phase 1: Spec (定義)

- **Output**: `docs/03_specs/{spec-name}.md`
- **Action**:
  - 山口の「才能（ロジック）」を言語化し、入出力、成功定義、バイアス判定基準を明文化する。
  - Claude Code 等に対し「この spec.md を正として、以降の実装を行え」と命じるための「正解データ」を作成する。
- **Checkpoint**: 「この仕様書だけで、背景を知らないエンジニア（またはAI）が実装を開始できるか？」

### Phase 2: Implement (実装)

- **Input**: `docs/03_specs/{spec-name}.md`
- **Action**:
  - 仕様書をもとにして実装作業を行う。

---

## 🛠 AI協働ガイドライン (AI-Agentic Workflow)

AIアシスタント（Claude Code / Cursor）を「Logic Factory 工員」として機能させるための指示要領。

1. **Context Loading**:
   実装開始前に必ず [`docs/01_guidelines/`](../01_guidelines/) と [`docs/02_architecture/`](../02_architecture/) を読み込ませ、規約を遵守させる。
2. **Spec First**:
   「いきなりコードを書かず、まずは `.md`の設計書 に基づいた実装計画（Plan）を提示せよ」と指示する。
3. **Atomic Implementation**:
   大規模な実装は避け、spec 内のタスク単位でインクリメンタルに実装・テストを繰り返させる。

---

## 📏 仕様書の必須項目 (spec.md Template)

各プロジェクトの `.md`の設計書 は以下の項目を網羅しなければならない。

- **Project Vision**: 何を解決し、どのような価値（バイアス検知等）を提供するか。
- **Input/Output**: 扱うデータの形式、ソース、出力先。
- **Infrastructure**: 使用する共通基盤のノード、GCP の特定リソース。
