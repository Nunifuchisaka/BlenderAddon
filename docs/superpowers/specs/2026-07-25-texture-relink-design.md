# テクスチャ再リンク機能 設計

## 背景・目的

BOOTHで購入したVRChat/VRMアバターのFBX/Blendファイルを読み込むと、テクスチャ画像がマテリアルに正しく適用されず、ビューポート上で紫/ピンク表示や欠落アイコンになるケースがある。原因は多くの場合、FBX/Blendが記録している画像ファイルパスと、実際に配布物内に同梱されているテクスチャファイルの配置がズレていること（別サブフォルダにある等）。

これを解消するため、ユーザーが指定したフォルダ配下を検索し、欠落しているテクスチャ画像と同名（または類似名）のファイルを見つけて自動的に再リンクする機能を、`avatar_mesh_toolkit` に新規feature `texture_relink` として追加する。

### 調査で切り分けた前提

- テクスチャ本体がそもそも配布物に含まれていないケース（今回のテスト用ファイル `Komane.blend` はこれに該当）は、この機能では解決できない。パス再リンクはあくまで「ファイルは存在するが、Blenderが見つけられていない」ケースが対象。
- 対応範囲はKomane限定ではなく、BOOTH購入アバター全般で汎用的に使えることを目指す。

## 機能概要

1. サイドバー「Avatar Toolkit」タブに新規パネル「テクスチャ再リンク」を追加する。
2. ユーザーが「検索フォルダ」を指定する（Blenderのフォルダ選択ダイアログ）。
3. 「欠落テクスチャを再リンク」を実行すると、シーン内（`bpy.data.images`）の欠落画像を対象に、指定フォルダ配下を再帰的に検索し、マッチしたファイルへ `filepath` を更新・`reload()` する。
4. 結果を既存の `core/report.py` パターンでレポート表示する。

## アーキテクチャ

既存 `features/<name>/` の4ファイル構成（properties/operators/panel/utils）を踏襲する。他featureへの依存はなく独立して動作する。

### `properties.py` — `AMT_TextureRelinkProperties`

- `search_directory: StringProperty(name="検索フォルダ", subtype='DIR_PATH')`
  - このアドオンで初めて導入するファイルシステムパス系プロパティ。既存featureは全て `PointerProperty(type=bpy.types.Object/Image)` でBlenderデータブロックを直接参照する設計だったため、新しいUIパターンとなる。`layout.prop()` に渡すだけでBlender標準のフォルダ選択ダイアログ（📁アイコン）が使える。
- `report_lines: CollectionProperty(type=AMT_ReportLine)` / `report_active_index: IntProperty()`
  - 既存パターン通り。

`register()`で `bpy.types.Scene.amt_texture_relink` に `PointerProperty` として生やす。`unregister()`で `del`。

### `utils.py` — 純ロジック（bpy.typesクラスを含まない）

- `collect_missing_images(images: Iterable[Image]) -> list[Image]`
  - `image.source == 'FILE'` かつ `image.packed_file is None` かつ `not os.path.exists(bpy.path.abspath(image.filepath))` を満たす画像を抽出する。
- `find_candidate_files(directory: str) -> list[str]`
  - 指定フォルダ配下を `os.walk` で再帰探索し、Blenderがサポートする主要な画像拡張子（png, jpg/jpeg, tga, bmp, tiff, exr, hdr等）のファイルパス一覧を収集する。
- マッチング判定（欠落画像1件に対して、候補ファイル群から最良マッチを決定する）。優先順位は上から順に評価し、最初にヒットしたレベルを採用する:
  1. **完全一致**: ファイル名+拡張子が完全一致（大文字小文字区別）。
  2. **名前一致（拡張子違い許容）**: 拡張子を除いたファイル名部分を、大文字小文字を無視し、Blenderの重複サフィックス（`.001` 等、画像データブロック名の末尾に付与されるもの）を除去したうえで比較し、一致するもの。
  3. **部分一致**: 前方一致または含含一致（どちらかの文字列がもう一方に含まれる）。
  - 各レベルで候補が1件のみ見つかった場合はそれを採用する。同一レベル内に候補が複数ある場合は自動選択せず「保留（複数候補あり）」として扱い、候補ファイルパス一覧をレポートに残す。
  - どのレベルでも候補が見つからない場合は「見つからず」として扱う。
- `relink_missing_textures(images, directory) -> RelinkResult`
  - 上記を組み合わせ、欠落画像ごとに判定を行い、採用が決まったものは `image.filepath = 採用パス` を設定して `image.reload()` を呼ぶ。
  - 戻り値は「再リンク成功」「保留（複数候補）」「見つからず」の3分類のリストで、それぞれ画像名・（保留の場合は）候補一覧を含む。
  - ここで例外は投げない（個々の画像の処理失敗は結果分類に含め、呼び出し側でレポート化する）。フォルダ自体が存在しない等の致命的な入力エラーのみ `ValueError` を投げる。

### `operators.py` — `OBJECT_OT_amt_relink_textures`

- `bl_idname = "object.amt_relink_textures"`, `bl_options = {'REGISTER', 'UNDO'}`
- `poll()`: `search_directory` が空でないことをチェック。
- `execute()`:
  - `props = context.scene.amt_texture_relink`
  - `utils.collect_missing_images(bpy.data.images)` が空なら `self.report({'INFO'}, "欠落しているテクスチャはありません")` として `{'FINISHED'}` を返す（レポート欄もその旨で更新）。
  - `utils.relink_missing_textures(...)` を呼び、結果を `lines = [(level, text), ...]` に変換して `set_report_lines(props.report_lines, lines)`。
  - 致命的エラー（フォルダ不正等）は `ValueError` を `except` で捕捉し `self.report({'ERROR'}, str(exc))` → `{'CANCELLED'}`。
- 確認ダイアログ（`invoke_props_dialog`）は不要。画像ファイルパスの参照先を変更するのみで、メッシュやマテリアルの構造を破壊しない操作のため。`filepath`変更・`reload()`はBlenderの通常のUndoスタックに乗る。

### `panel.py`

- `bl_space_type='VIEW_3D'`, `bl_region_type='UI'`, `bl_category=TOOLKIT_CATEGORY`（`core/ui.py` からimport）
- `draw()`: `layout.prop(props, "search_directory")` → 実行ボタン → `report_lines` を `AMT_UL_report_lines` で一覧表示（既存パターン踏襲）。

### `__init__.py` 登録

- トップレベル `_modules` タプルに `texture_relink` を追加する。他featureへの依存がないため挿入位置に制約はないが、`core_report` より後であればよい。既存の並び（`core_report, hidden_mesh, texture_bake, cleanup, merge, diagnostics`）の末尾に追加する。

## エラーハンドリング

- 検索フォルダが空文字列 → `poll()` でボタンをグレーアウトし実行させない。
- 検索フォルダのパスが存在しない → `execute()` 内で `ValueError` として捕捉し、オペレータレベルのエラー表示。
- 欠落画像が0件 → 正常系として「対象なし」のレポートを出す（エラー扱いしない）。

## テスト方針

- 自動テストは無し（プロジェクト全体方針、`bpy` はBlender実機でのみ動作）。
- Blender実機（5.0/5.2、開発機にインストール済み）で以下を確認する:
  - 欠落画像がある状態のBlendファイルに対し、テクスチャ本体が別フォルダに存在する状態を用意し、完全一致・拡張子違い・部分一致それぞれのケースで正しく再リンクされること。
  - 複数候補が同レベルで存在する場合に自動選択されず保留としてレポートされること。
  - 欠落画像が無い場合、フォルダが不正な場合のレポート表示。

## スコープ外

- 見つからないテクスチャファイルの生成・ダウンロード等は行わない（ローカルの既存ファイルとの再リンクのみ）。
- マテリアルノード自体が存在しない（FBXインポート時にテクスチャノードごと生成されなかった）ケースへの対応は今回の対象外。あくまで「画像データブロックは存在するがファイルパスが見つからない」ケースの再リンクに限定する。
