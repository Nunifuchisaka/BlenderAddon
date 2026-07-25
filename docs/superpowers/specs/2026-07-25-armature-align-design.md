# アーマチュア位置合わせ機能 設計

## 背景・目的

同一アバターの別バージョン（例: 素足版とハイヒール版）のArmatureを重ねて比較・作業したいことがある。これらはボーン構成が同じでも、レストポーズにおける各ボーンの配置が異なる（ハイヒール版はヒール高の分だけ全身が持ち上がっている）。

このとき、両方のArmatureオブジェクトの `location` が `(0, 0, 0)` であっても、実際のボーン位置は一致しない。オブジェクトのTransform値を見比べても差が現れないため、目視で数値を合わせることができない。

そこで、**指定したボーン（既定ではHips）のレストポーズ・ワールド座標が完全に一致するように、対象Armatureオブジェクトを平行移動する**機能を、`NuniAvatarToolkit` に新規feature `armature_align` として追加する。

### 対象範囲

- 対象は「同じアバターの別バージョン同士」のように、ボーン構成が共通で配置だけが違うArmature。
- 位置（平行移動）のみを一致させる。回転・スケールは変更しない。
- レストポーズ（Edit Modeでのボーン配置）を基準とする。現在のポーズ（Pose Modeでの変形後位置）は見ない。

## 機能概要

1. サイドバー「Avatar Toolkit」タブに新規パネル「アーマチュア位置合わせ」を追加する。
2. ユーザーが「基準Armature」「基準ボーン」「対象Armature」「対象ボーン」を指定する。
3. 「位置を合わせる」を実行すると、対象Armatureオブジェクト全体が平行移動し、指定ボーンのワールド座標が基準側と一致する。
4. 結果（移動量、警告）を既存の `core/report.py` パターンでレポート表示する。

## アーキテクチャ

既存 `features/<name>/` の4ファイル構成（properties/operators/panel/utils）を踏襲する。他featureへの依存はなく独立して動作する。

### `properties.py` — `AMT_ArmatureAlignProperties`

- `reference_object: PointerProperty(type=bpy.types.Object, name="基準Armature", poll=_armature_object_poll)`
  - `poll` は `obj.type == 'ARMATURE'` のみ通す。
- `reference_bone: StringProperty(name="基準ボーン")`
  - パネル側では `layout.prop_search(props, "reference_bone", reference_object.data, "bones")` で選択させる。
- `target_object: PointerProperty(type=bpy.types.Object, name="対象Armature", poll=_armature_object_poll)`
- `target_bone: StringProperty(name="対象ボーン")`
- `report_lines: CollectionProperty(type=AMT_ReportLine)` / `report_active_index: IntProperty()`

`reference_object` / `target_object` にはそれぞれ `update` コールバックを設定し、オブジェクトが変更されたとき、対応するボーン名プロパティに Hips 相当のボーンを自動設定する（後述の `find_hips_bone`）。既にユーザーが選んだボーン名が新しいオブジェクトにも存在する場合は上書きしない。

`register()` で `bpy.types.Scene.amt_armature_align` に `PointerProperty` として生やす。`unregister()` で `del`。

### `utils.py` — 純ロジック（bpy.typesクラスを含まない）

- `find_hips_bone(armature_data) -> str`
  - `armature_data.bones` を走査し、名前を小文字化して `"hips"` を含む最初のボーン名を返す。見つからなければ空文字列を返す。
  - 完全一致（`"hips"`）を含有一致より優先する。`"Hips"` と `"Hips_end"` が両方ある場合に前者を選ぶため。
- `get_bone_rest_world_head(obj, bone_name) -> Vector`
  - `obj.matrix_world @ obj.data.bones[bone_name].head_local` を返す。
  - `head_local` はレストポーズにおけるArmatureオブジェクト空間の座標。これに `matrix_world` を掛けることでワールド座標になり、オブジェクトの `location` が `(0,0,0)` でもボーン配置の差が正しく現れる。
  - `bone_name` が存在しない場合は `KeyError` ではなく `ValueError` を投げる（呼び出し側で日本語メッセージに変換するため）。
- `compute_alignment_delta(reference_object, reference_bone, target_object, target_bone) -> Vector`
  - `get_bone_rest_world_head(reference_object, reference_bone) - get_bone_rest_world_head(target_object, target_bone)` を返す。
- `find_orphan_armature_meshes(target_object) -> list[str]`
  - シーン内の全メッシュオブジェクトを走査し、「`target_object` を参照するArmatureモディファイアを持つが、`target_object` の子孫ではない」ものの名前一覧を返す。
  - 親子関係の判定は `obj.parent` を遡って `target_object` に到達するかで行う。
  - この機能はArmatureオブジェクトだけを動かすため、これらのメッシュは移動後もその場に取り残される。警告としてレポートに出すために使う。
- `apply_alignment(target_object, delta) -> None`
  - ```python
    mw = target_object.matrix_world.copy()
    mw.translation += delta
    target_object.matrix_world = mw
    ```
  - `matrix_world` への代入は、対象が別オブジェクトに親付けされていても親の逆行列を考慮して正しくローカル値に変換される。`location` を直接加算する方式だと親の回転・スケールがある場合にワールド座標としてズレるため、この方式を採る。

### `operators.py` — `OBJECT_OT_amt_align_armature`

- `bl_idname = "object.amt_align_armature"`, `bl_options = {'REGISTER', 'UNDO'}`
- `poll()`: `reference_object` と `target_object` の両方が設定されていることをチェック。
- `execute()`:
  - `props = context.scene.amt_armature_align`
  - 以下を検証し、該当すれば `self.report({'ERROR'}, ...)` → `{'CANCELLED'}`:
    - 基準と対象に同じオブジェクトが指定されている → 「基準Armatureと対象Armatureに同じオブジェクトが指定されています」
    - `reference_bone` または `target_bone` が空 → 「ボーンを指定してください」
    - 指定ボーン名が該当Armatureに存在しない → 「ボーン『<名前>』が見つかりません」
    - 対象Armatureが編集不可（`target_object.library is not None` または `target_object.override_library is not None`）→ 「対象Armatureはリンクされているため移動できません」
  - `compute_alignment_delta(...)` で差分を求める。
  - 差分の長さが `1e-6` 未満なら移動を行わず、「既に一致しています」を `INFO` レベルでレポートして `{'FINISHED'}` を返す。
  - `apply_alignment(...)` を実行する。
  - レポート行を組み立て `set_report_lines(props.report_lines, lines)`:
    - `INFO`: 基準「<オブジェクト名> / <ボーン名>」、対象「<オブジェクト名> / <ボーン名>」
    - `INFO`: 移動量 `X=..., Y=..., Z=...`（小数第4位まで）
    - `find_orphan_armature_meshes(target_object)` が空でなければ `WARNING`: 「次のメッシュは対象Armatureの子ではないため移動していません: <名前一覧>」
- 確認ダイアログ（`invoke_props_dialog`）は不要。オブジェクトのTransformを変更するのみで、メッシュ・ボーン・ウェイトのいずれも破壊しない。`'UNDO'` によりCtrl+Zで元に戻せる。

### `panel.py`

- `bl_space_type='VIEW_3D'`, `bl_region_type='UI'`, `bl_category=TOOLKIT_CATEGORY`（`core/ui.py` からimport）
- `bl_label = "アーマチュア位置合わせ"`, `bl_order = 6`（既存パネルは 0〜5 を使用済み。`texture_relink` が 5 なのでその次）。
- `bl_idname = "VIEW3D_PT_amt_armature_align"`
- `draw()`:
  - `layout.prop(props, "reference_object")`、`reference_object` が設定されていれば `layout.prop_search(props, "reference_bone", props.reference_object.data, "bones")`
  - 同様に `target_object` / `target_bone`
  - 実行ボタン `layout.operator("object.amt_align_armature")`
  - `report_lines` を `AMT_UL_report_lines` で一覧表示（既存パターン踏襲）

### `__init__.py` 登録

- feature 側の `__init__.py` は `_modules = (properties, operators, panel)` を順／逆順に register/unregister する既存パターン。
- トップレベル `_modules` タプルの末尾に `armature_align` を追加する。他featureへの依存がないため位置に制約はないが、`core_report` より後であればよい。

## 設計判断の記録

- **ボーン名を "Hips" 固定にしない理由**: VRM等で日本語名（「腰」）や独自命名のリグが存在する。自動探索を初期値として提供しつつ、UIで選び直せるようにする。
- **レストポーズを基準にする理由**: 別バージョン同士の「基本体型の差」を揃えるのが目的であり、一時的なポーズの影響を受けるべきではない。
- **回転を合わせない理由**: 同一アバターの別バージョン同士ではボーンの向きが既に一致しているため不要。回転を含めるとArmature全体が傾く事故が起きうる。
- **XYZ全軸を合わせる理由**: 「Hipsが完全に重なる」という要件に忠実。ハイヒール差分の場合、X/Yの差は元々ほぼ0なので実害がない。
- **子メッシュを追わない理由**: VRChat/VRMアバターの通常構成ではメッシュがArmatureに親付けされており、Armatureを動かせば自動で追従する。親付けされていないメッシュまで探して動かすと、意図しないオブジェクトを動かす事故のリスクがある。取り残しは警告として可視化するに留める。

## エラーハンドリング

| 状況 | 挙動 |
|---|---|
| 基準/対象Armatureが未指定 | `poll()` でボタンをグレーアウト |
| 基準と対象が同一オブジェクト | 実行時エラー（`{'CANCELLED'}`） |
| ボーン名が空 | 実行時エラー |
| 指定ボーン名がArmatureに存在しない | 実行時エラー |
| 対象Armatureがライブラリリンク | 実行時エラー |
| 移動量が実質0 | エラーではなく「既に一致しています」をレポート |
| 取り残されるメッシュがある | 移動は実行し、警告としてレポートに列挙 |

## テスト方針

- 自動テストは無し（プロジェクト全体方針、`bpy` はBlender実機でのみ動作）。
- Blender実機（3.6+）で以下を確認する:
  - 素足版/ハイヒール版のように両方の `location` が `(0,0,0)` で、Hipsのレスト位置だけZ方向に違うArmature同士で、対象が正しくZ方向に移動しHipsが重なること。
  - 対象Armatureに親付けされたメッシュが一緒に移動すること。
  - オブジェクト選択時にHips相当のボーンが自動で選ばれること（`"Hips"`, `"hips"` の両方）。
  - 同一オブジェクト指定・ボーン名不正時にエラーが表示され、Transformが変更されないこと。
  - 既に一致している状態で実行したとき、「既に一致しています」が表示されること。
  - 親付けされていないがArmatureモディファイアで紐づくメッシュがある場合に、警告がレポートされること。
  - 実行後 Ctrl+Z で元の位置に戻ること。

## スコープ外

- 回転・スケールの一致は行わない。
- 複数ボーンを使った最小二乗フィッティング等の高度な位置合わせは行わない。
- ボーン構成が異なるArmature間でのリターゲット・ボーン名マッピングは行わない。
- レストポーズ（Edit Modeのボーン配置）自体の書き換えは行わない。既存のウェイト付けとの整合性を崩さないため、あくまでオブジェクトのTransformのみを変更する。
- 対象Armatureの子でないメッシュの移動は行わない（警告表示のみ）。
