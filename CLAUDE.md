# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 概要

「Nuni Avatar Toolkit for Blender」（パッケージ名・モジュール名は `NuniAvatarToolkit`）は VRChat/VRM アバター向けメッシュ最適化のBlenderアドオン（純Python、`bpy`依存）。レガシー形式（`bl_info`）で配布する。ユーザー向けの機能説明・使い方は `README.md`、変更履歴は `CHANGELOG.md` を参照（ここでは繰り返さない）。

## ビルド・配布・テスト

- **配布ZIP**: `powershell -ExecutionPolicy Bypass -File tools/build-release.ps1` でリポジトリ直下に `NuniAvatarToolkit-<版数>.zip` を作る。PowerShell 7では `pwsh -File tools/build-release.ps1 -OutputDirectory <出力先>` も使用可。版数は `bl_info["version"]` から読み、`__pycache__`・`*.pyc`・休止中の `features/texture_bake/` は除外し、ルートのLICENSEを同梱する（ZIP内のトップは `NuniAvatarToolkit/`）。
- **unittest（Blender外で実行可）**: `cd tests && python -m unittest test_safety_utils test_bone_follow_utils`。各 feature の `utils.py` を単体ロードしてテストするため、`utils.py` から `core` などを相対 import しないこと。
- **スモークテスト（Blender背景モード）**: `blender --background --factory-startup --python-exit-code 1 --python tests/<名前>.py` で以下の4本を実行する。Windowsでは実行ファイルのフルパスを指定する。
  - `blender_hidden_mesh_smoke.py`（成功時に `BLENDER_HIDDEN_MESH_SMOKE_OK` を出力）
  - `blender_bone_follow_smoke.py`（同 `... smoke test passed`）
  - `blender_review_fixes_smoke.py`（同 `BLENDER_REVIEW_FIXES_SMOKE_OK`）
  - `blender_review_rest_smoke.py`（同 `BLENDER_REVIEW_REST_SMOKE_OK`）
- **リリース安全性の回帰テスト**: 同じコマンドで `blender_core_release_safety.py`、`blender_hidden_release_safety.py`、`blender_cleanup_release_safety.py`、`blender_cloth_release_safety.py`、`blender_bone_release_safety.py`、`blender_texture_diagnostics_release_safety.py`、`blender_release_lifecycle_smoke.py` の7本を実行する。4.2.0・4.3.2・5.2.0のLinux版で確認済み。最後のテストは一時ディレクトリを使いZIP導入・更新・登録解除を検証する。
- lint は無い。UIの見た目などテストで確かめられない部分は、Blender実機でアドオンを再読み込み（無効化→有効化、または再起動）して確認する（`bpy` はエディタ外で import 不可）。
- `bl_info["version"]` と `CHANGELOG.md` は機能追加時に手動で揃える。

## アーキテクチャ

### 登録の骨格

- トップ `__init__.py` の `register()`/`unregister()` が `_modules` を順に register する。**登録順が重要**: `core.report` を必ず最初に登録する（各featureの PropertyGroup が `CollectionProperty(type=AMT_ReportLine)` を宣言するため、その型が先に存在している必要がある）。`unregister` は逆順。
- 各 feature (`features/<name>/`) は自身の `__init__.py` で `_modules = (properties, operators, panel)` を同じ register ループで束ねる。この「_modules を順／逆順に回す」入れ子パターンが全階層で一貫している。

### feature パッケージの構成パターン

各 `features/<name>/` は原則 4ファイル。ただし状態を持たないfeatureは `properties.py` を持たない（例: `merge` は `(operators, panel)` のみ）。

- `properties.py` — `AMT_<Feature>Properties(PropertyGroup)` を定義し、`register()` 内で `bpy.types.Scene.amt_<feature>` に `PointerProperty` として生やす（`unregister()` で `del`）。UI状態・入力もここに置く。
- `operators.py` — `OBJECT_OT_amt_<action>(Operator)`。`bl_idname` は `object.amt_<action>`。
- `panel.py` — サイドバー "Avatar Toolkit" タブ内のパネル。タブ名は `core/ui.py` の `TOOLKIT_CATEGORY` 定数を必ず使う（ハードコードしない）。
- `utils.py` — そのfeature固有の純ロジック（`bpy.types` クラスを含まない）。

### core/ の役割分担（重要な区別）

- `core/report.py` は **例外的に** `bpy.types` クラス（`AMT_ReportLine`, `AMT_UL_report_lines`）を定義するので register が必要 → だからトップ `__init__.py` の `_modules` 先頭に入る。レポート表示は `set_report_lines(collection_prop, [(level, text), ...])` 経由で統一。
- それ以外の core モジュール（`mesh_eval.py`, `context_utils.py`, `object_polls.py`, `ui.py`, `uv_regions.py`）は **register しない**。feature から import される純ヘルパー/定数のみ。新規に共有コードを足すときは、`bpy.types` クラスを含むなら report と同じく登録対象に加える判断が必要。

### 命名規約（既存に合わせる）

- Operator クラス: `OBJECT_OT_amt_*` / `bl_idname`: `object.amt_*`
- PropertyGroup / UIList 等の型: `AMT_*`
- Scene 上のプロパティ: `bpy.types.Scene.amt_<feature>`
- UI文字列（`name`/`description`/`bl_label`/レポート）は日本語。

### feature 間のデータ受け渡し

feature どうしは互いに import しない。`hidden_mesh`（生産側）と `texture_bake`（消費側）は `core/uv_regions.py` を介してのみ連携する。解放UV領域は、メッシュのIDカスタムプロパティ（キー `FREED_UV_RECTS_KEY`）に**プレーンなJSON文字列**として保存され、save/reload・リネーム・複製に耐える。新たな feature 間連携もこの「core経由・JSON in custom property」パターンに倣う。

### 破壊的操作・実行時の慣習

- 削除系オペレータは `bl_options` に `'UNDO'` を含め、`invoke_props_dialog` で確認ダイアログを出してから `execute` する（`cleanup`/`hidden_mesh` の削除が手本）。
- 頂点数を変えるモディファイア対応は `core/mesh_eval.py` の `DEFORM_MODIFIER_TYPES` と `disable_non_deform_modifiers` に集約。編集モードでの面選択と1:1対応を保つため、deform系以外は一時無効化して評価する。
- 長時間処理はモーダルオペレータ（ESCキャンセル・進行表示）にする（`hidden_mesh` の面選択が手本）。
- モード復帰は `core/context_utils.reset_to_object_mode_with_active(context, obj)` を使う。
