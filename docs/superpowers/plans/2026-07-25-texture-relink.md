# テクスチャ再リンク機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BOOTHで購入したアバターのFBX/Blendインポート時に欠落するテクスチャ画像を、ユーザーが指定したフォルダから検索して自動的に再リンクする新規feature `texture_relink` を `avatar_mesh_toolkit` に追加する。

**Architecture:** 既存の `features/<name>/` 4ファイル構成（properties/operators/panel/utils）を踏襲した独立featureとして実装する。他featureへの依存はない。マッチングは「完全一致→拡張子/大小文字/重複サフィックス違いを許容した名前一致→部分一致」の3段階フォールバックで判定し、同レベルで複数候補がある場合は自動選択せずレポートに一覧表示する。

**Tech Stack:** Python 3（Blender内蔵）、`bpy`、標準ライブラリのみ（`os`, `re`）。

## Global Constraints

- 対応バージョン: Blender 3.6以降（`bl_info["blender"] = (3, 6, 0)`、既存のまま変更しない）。開発機の実機検証は `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`（5.2 LTS）を使う。
- **自動テストフレームワーク（pytest等）は導入しない。** `bpy` はBlender実機以外でimportできないため（`CLAUDE.md` に明記）、全ての動作確認は `blender.exe --background --python <script>` によるheadless実行で行う。Blender起動はコストが高いため、関数単位でテストを分割せず、1ファイルの検証スクリプトにアサーションをまとめて実行する。
- コーディング規約（既存踏襲）: Operatorクラス `OBJECT_OT_amt_*` / `bl_idname: object.amt_*`、PropertyGroup/UIList等の型 `AMT_*`、Scene上のプロパティ `bpy.types.Scene.amt_<feature>`。UI文字列（`name`/`description`/`bl_label`/レポート）は日本語。
- `core.report` は既にトップレベル `_modules` の先頭で登録済み。texture_relinkはそれより後であればどこに追加してもよい（他featureへの依存なし）。
- 破壊的操作（メッシュ/データ削除）ではないため、`invoke_props_dialog` による確認ダイアログは不要。`bl_options = {'REGISTER', 'UNDO'}` のみで良い。
- `bl_info["version"]` と `CHANGELOG.md` は機能追加時に手動で揃える（`CLAUDE.md` の既存指示）。
- テスト用一時ファイルは `C:\Users\nunif\AppData\Local\Temp\amt_texture_relink_test\` 配下に作成し、検証完了後に削除する（リポジトリにコミットしない）。

---

### Task 1: `features/texture_relink/utils.py` — マッチングロジックと再リンク処理

**Files:**
- Create: `avatar_mesh_toolkit/features/texture_relink/utils.py`

**Interfaces:**
- Consumes: なし（bpy標準API、標準ライブラリのみ）
- Produces:
  - `IMAGE_EXTENSIONS: set[str]`
  - `LEVEL_EXACT = 1`, `LEVEL_NAME = 2`, `LEVEL_PARTIAL = 3`
  - `collect_missing_images(images) -> list[bpy.types.Image]`
  - `find_candidate_files(directory: str) -> list[str]`
  - `match_level(image_name: str, candidate_path: str) -> int | None`
  - `find_best_matches(image_name: str, candidates: list[str]) -> tuple[int | None, list[str]]`
  - `relink_missing_textures(images, directory: str) -> dict` — キーは `'relinked'`（`list[tuple[Image, str]]`）、`'ambiguous'`（`list[tuple[Image, list[str]]]`）、`'not_found'`（`list[Image]`）。`directory` が存在しないディレクトリの場合 `ValueError` を送出。

- [ ] **Step 1: `utils.py` を実装する**

```python
"""features/texture_relink 用の純ロジック。bpy.types クラスは定義しないが、
collect_missing_images() と relink_missing_textures() は bpy.data.images / bpy.path を
直接扱うため、このモジュール自体は Blender 実機以外では import できない。
"""

import os
import re

import bpy

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tiff', '.tif', '.exr', '.hdr'}

_DUPLICATE_SUFFIX_RE = re.compile(r'\.\d{3}$')

LEVEL_EXACT = 1
LEVEL_NAME = 2
LEVEL_PARTIAL = 3


def collect_missing_images(images):
    """images: bpy.data.images 等の Image イテラブル。
    source == 'FILE' かつパッキングされておらず、実ファイルが存在しない画像を返す。"""
    missing = []
    for image in images:
        if image.source != 'FILE':
            continue
        if image.packed_file is not None:
            continue
        if not image.filepath:
            continue
        if not os.path.exists(bpy.path.abspath(image.filepath)):
            missing.append(image)
    return missing


def find_candidate_files(directory):
    """directory 配下を再帰的に探索し、画像拡張子のファイルパス一覧を返す。"""
    candidates = []
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS:
                candidates.append(os.path.join(root, filename))
    return candidates


def _strip_duplicate_suffix(name):
    """Blenderが重複時に付与する '.001' 等の末尾サフィックスを除去する。"""
    return _DUPLICATE_SUFFIX_RE.sub('', name)


def match_level(image_name, candidate_path):
    """image_name (bpy.types.Image.name) と candidate_path の一致レベルを判定する。
    LEVEL_EXACT: ファイル名+拡張子が完全一致(大文字小文字区別)。
    LEVEL_NAME: 拡張子違い/大文字小文字/Blenderの重複サフィックスを無視して名前が一致。
    LEVEL_PARTIAL: 正規化した名前の一方がもう一方を含む(前方一致・含含一致)。
    一致しない場合は None。"""
    candidate_filename = os.path.basename(candidate_path)

    if image_name == candidate_filename:
        return LEVEL_EXACT

    # Blenderは重複インポート時 "TX_Body_A.png.001" のように元の拡張子の後ろに
    # 連番を付与するため、拡張子分離の前にこのサフィックスを剥がす必要がある。
    normalized_image_name = _strip_duplicate_suffix(image_name)
    image_stem = os.path.splitext(normalized_image_name)[0].lower()
    candidate_stem = os.path.splitext(candidate_filename)[0].lower()

    if not image_stem:
        return None

    if image_stem == candidate_stem:
        return LEVEL_NAME

    if image_stem in candidate_stem or candidate_stem in image_stem:
        return LEVEL_PARTIAL

    return None


def find_best_matches(image_name, candidates):
    """candidates の中から image_name に対する最良レベルの一致を全て集めて返す。
    戻り値: (level, [candidate_path, ...])。一致が無ければ (None, [])。"""
    best_level = None
    best_matches = []
    for candidate_path in candidates:
        level = match_level(image_name, candidate_path)
        if level is None:
            continue
        if best_level is None or level < best_level:
            best_level = level
            best_matches = [candidate_path]
        elif level == best_level:
            best_matches.append(candidate_path)
    return best_level, best_matches


def relink_missing_textures(images, directory):
    """images 内の欠落画像を directory 配下から検索して再リンクする。
    directory は絶対パスの既存ディレクトリであること(呼び出し側で bpy.path.abspath 済みを渡す)。"""
    if not directory or not os.path.isdir(directory):
        raise ValueError(f"検索フォルダが存在しません: {directory}")

    candidates = find_candidate_files(directory)

    relinked = []
    ambiguous = []
    not_found = []

    for image in collect_missing_images(images):
        level, matches = find_best_matches(image.name, candidates)
        if level is None:
            not_found.append(image)
        elif len(matches) == 1:
            new_path = matches[0]
            image.filepath = new_path
            image.reload()
            relinked.append((image, new_path))
        else:
            ambiguous.append((image, matches))

    return {'relinked': relinked, 'ambiguous': ambiguous, 'not_found': not_found}
```

- [ ] **Step 2: テスト用フォルダとダミーファイルを作成する**

Run (Bash):
```bash
mkdir -p "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test/candidates"
cd "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test/candidates"
printf 'dummy' > "TX_Body_A.png"
printf 'dummy' > "tx_face_a.jpg"
printf 'dummy' > "TX_Hair_A.png"
printf 'dummy' > "Cloth_Tops_A.png"
printf 'dummy' > "Face_Option_A_v1.png"
printf 'dummy' > "Face_Option_A_v2.png"
```

用意したファイルと想定するテストケースの対応:
| ファイル | 対応する画像名 | 想定レベル |
|---|---|---|
| `TX_Body_A.png` | `TX_Body_A.png` | LEVEL_EXACT |
| `tx_face_a.jpg` | `TX_Face_A.png` | LEVEL_NAME(拡張子違い+大小文字違い) |
| `TX_Hair_A.png` | `TX_Hair_A.png.001` | LEVEL_NAME(重複サフィックス除去後) |
| `Cloth_Tops_A.png` | `TX_Cloth_Tops_A.png` | LEVEL_PARTIAL |
| `Face_Option_A_v1.png` / `_v2.png` | `TX_Face_Option_A.png` | LEVEL_PARTIAL が2件(曖昧) |

- [ ] **Step 3: 検証スクリプトを作成する**

Write to `C:\Users\nunif\AppData\Local\Temp\amt_texture_relink_test\verify_utils.py`:

```python
import sys
sys.path.insert(0, r"E:\git\BlenderAddon\avatar_mesh_toolkit\features\texture_relink")
import utils

TEST_DIR = r"C:\Users\nunif\AppData\Local\Temp\amt_texture_relink_test\candidates"

candidates = utils.find_candidate_files(TEST_DIR)
print("CANDIDATES_COUNT:", len(candidates))
assert len(candidates) == 6, f"expected 6 candidate files, got {len(candidates)}: {candidates}"

assert utils.match_level("TX_Body_A.png", TEST_DIR + r"\TX_Body_A.png") == utils.LEVEL_EXACT
assert utils.match_level("TX_Face_A.png", TEST_DIR + r"\tx_face_a.jpg") == utils.LEVEL_NAME
assert utils.match_level("TX_Hair_A.png.001", TEST_DIR + r"\TX_Hair_A.png") == utils.LEVEL_NAME
assert utils.match_level("TX_Cloth_Tops_A.png", TEST_DIR + r"\Cloth_Tops_A.png") == utils.LEVEL_PARTIAL
assert utils.match_level("TX_NoMatch_A.png", TEST_DIR + r"\TX_Body_A.png") is None
print("MATCH_LEVEL_OK")

level, matches = utils.find_best_matches("TX_Face_Option_A.png", candidates)
print("AMBIGUOUS_LEVEL:", level, "MATCHES:", matches)
assert level == utils.LEVEL_PARTIAL
assert len(matches) == 2
print("FIND_BEST_MATCHES_OK")

import bpy

img_missing = bpy.data.images.new("TX_Body_A.png", 1, 1)
img_missing.source = 'FILE'
img_missing.filepath = r"C:\amt_nonexistent_folder\TX_Body_A.png"

img_packed = bpy.data.images.new("packed_dummy.png", 1, 1)
img_packed.pack()

missing = utils.collect_missing_images(bpy.data.images)
missing_names = [i.name for i in missing]
print("MISSING_NAMES:", missing_names)
assert "TX_Body_A.png" in missing_names
assert "packed_dummy.png" not in missing_names
print("COLLECT_MISSING_IMAGES_OK")

result = utils.relink_missing_textures(bpy.data.images, TEST_DIR)
relinked_names = [i.name for i, _ in result['relinked']]
print("RELINKED:", relinked_names)
assert "TX_Body_A.png" in relinked_names
assert img_missing.filepath.endswith("TX_Body_A.png")
print("RELINK_MISSING_TEXTURES_OK")

try:
    utils.relink_missing_textures(bpy.data.images, r"C:\this_folder_does_not_exist_amt")
    raise SystemExit("expected ValueError was not raised")
except ValueError:
    print("VALUEERROR_ON_BAD_DIR_OK")

print("ALL_UTILS_TESTS_PASSED")
```

- [ ] **Step 4: Blenderのheadless実行で検証する**

Run (Bash):
```bash
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --python "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test/verify_utils.py"
```

Expected: 出力の中に `ALL_UTILS_TESTS_PASSED` が含まれ、`Error`や`Traceback`が出ていないこと。`AssertionError`が出た場合はどのアサーションで失敗したかを確認し、`utils.py`を修正して再実行する。

- [ ] **Step 5: テスト用ファイルを削除する**

Run (Bash):
```bash
rm -rf "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test"
```

- [ ] **Step 6: コミット**

```bash
git add avatar_mesh_toolkit/features/texture_relink/utils.py
git commit -m "Add texture_relink matching/relink logic"
```

---

### Task 2: `features/texture_relink/properties.py`

**Files:**
- Create: `avatar_mesh_toolkit/features/texture_relink/properties.py`

**Interfaces:**
- Consumes: `avatar_mesh_toolkit.core.report.AMT_ReportLine`（既存）
- Produces: `AMT_TextureRelinkProperties`（`bpy.types.Scene.amt_texture_relink` として登録される）。属性: `search_directory: str`, `report_lines: CollectionProperty`, `report_active_index: int`。`register()` / `unregister()`。

- [ ] **Step 1: `properties.py` を実装する**

```python
import bpy

from ...core.report import AMT_ReportLine


class AMT_TextureRelinkProperties(bpy.types.PropertyGroup):
    search_directory: bpy.props.StringProperty(
        name="検索フォルダ",
        description="欠落しているテクスチャ画像を探すフォルダを指定してください(サブフォルダも再帰的に検索します)",
        subtype='DIR_PATH',
    )
    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_TextureRelinkProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_texture_relink = bpy.props.PointerProperty(type=AMT_TextureRelinkProperties)


def unregister():
    del bpy.types.Scene.amt_texture_relink
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 2: 単体でregisterが通ることを確認する**

`properties.py` は `from ...core.report import AMT_ReportLine` という3階層の相対importを使っているため、ファイルパスを直接 `sys.path` に追加してモジュール単体でimportすると `ImportError: attempted relative import with no known parent package` になる。`features/texture_relink/__init__.py` はまだ存在しない(Task 5で作成)が、Python 3の名前空間パッケージ機能により、`avatar_mesh_toolkit` をトップからimportして `avatar_mesh_toolkit.features.texture_relink.properties` という完全修飾名でアクセスすれば、相対importも正しく解決される。

Write to `C:\Users\nunif\AppData\Local\Temp\amt_texture_relink_test2\verify_properties.py`（先に `mkdir -p "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test2"` を実行しておく）:

```python
import sys
sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy
from avatar_mesh_toolkit.core import report as core_report
from avatar_mesh_toolkit.features.texture_relink import properties

core_report.register()
properties.register()
print("REGISTER_OK")

scene = bpy.data.scenes[0]
assert hasattr(scene, "amt_texture_relink")
scene.amt_texture_relink.search_directory = r"C:\some\folder"
assert scene.amt_texture_relink.search_directory == r"C:\some\folder" or scene.amt_texture_relink.search_directory.endswith("some\\folder\\") or scene.amt_texture_relink.search_directory.endswith("some/folder/")
print("PROPERTY_ROUNDTRIP_OK")

properties.unregister()
core_report.unregister()
print("UNREGISTER_OK")
print("ALL_PROPERTIES_TESTS_PASSED")
```

Run (Bash):
```bash
mkdir -p "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test2"
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --python "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test2/verify_properties.py"
```

Expected: 出力に `ALL_PROPERTIES_TESTS_PASSED` が含まれる。`DIR_PATH`のsubtypeはBlenderが末尾にスラッシュを補完する場合があるため、上記の緩い比較で確認する。

- [ ] **Step 3: テスト用ファイルを削除してコミット**

```bash
rm -rf "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test2"
git add avatar_mesh_toolkit/features/texture_relink/properties.py
git commit -m "Add texture_relink properties"
```

---

### Task 3: `features/texture_relink/operators.py`

**Files:**
- Create: `avatar_mesh_toolkit/features/texture_relink/operators.py`

**Interfaces:**
- Consumes: `properties.AMT_TextureRelinkProperties`（Task 2）、`utils.collect_missing_images` / `utils.relink_missing_textures`（Task 1）、`avatar_mesh_toolkit.core.report.set_report_lines`（既存）
- Produces: `OBJECT_OT_amt_relink_textures`（`bl_idname = "object.amt_relink_textures"`）。`register()` / `unregister()`。

- [ ] **Step 1: `operators.py` を実装する**

```python
import os

import bpy

from ...core.report import set_report_lines
from . import utils


class OBJECT_OT_amt_relink_textures(bpy.types.Operator):
    bl_idname = "object.amt_relink_textures"
    bl_label = "欠落テクスチャを再リンク"
    bl_description = "検索フォルダの中から、欠落しているテクスチャ画像と同名/類似名のファイルを探して再リンクします"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_texture_relink
        return bool(props.search_directory)

    def execute(self, context):
        props = context.scene.amt_texture_relink

        if not utils.collect_missing_images(bpy.data.images):
            set_report_lines(props.report_lines, [('INFO', "欠落しているテクスチャはありません")])
            self.report({'INFO'}, "欠落しているテクスチャはありません")
            return {'FINISHED'}

        try:
            directory = bpy.path.abspath(props.search_directory)
            result = utils.relink_missing_textures(bpy.data.images, directory)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        lines = []
        for image, new_path in result['relinked']:
            lines.append(('INFO', f"{image.name}: '{new_path}' に再リンクしました"))
        for image, matches in result['ambiguous']:
            candidates_text = ", ".join(os.path.basename(m) for m in matches)
            lines.append(('WARNING', f"{image.name}: 候補が複数あるためスキップしました({candidates_text})"))
        for image in result['not_found']:
            lines.append(('WARNING', f"{image.name}: 一致するファイルが見つかりませんでした"))

        set_report_lines(props.report_lines, lines)
        self.report(
            {'INFO'},
            f"再リンク {len(result['relinked'])} 件、保留 {len(result['ambiguous'])} 件、"
            f"見つからず {len(result['not_found'])} 件",
        )
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_relink_textures,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 2: テスト用フォルダとダミーファイルを再作成する**

Run (Bash):
```bash
mkdir -p "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test3/candidates"
printf 'dummy' > "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test3/candidates/TX_Body_A.png"
```

- [ ] **Step 3: 検証スクリプトを作成する**

`operators.py` も `from ...core.report import set_report_lines` / `from . import utils` という相対importを使うため、Task 2と同様に `avatar_mesh_toolkit` をトップからimportし、完全修飾名でアクセスする。

Write to `C:\Users\nunif\AppData\Local\Temp\amt_texture_relink_test3\verify_operators.py`:

```python
import sys
sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy
from avatar_mesh_toolkit.core import report as core_report
from avatar_mesh_toolkit.features.texture_relink import properties
from avatar_mesh_toolkit.features.texture_relink import operators

core_report.register()
properties.register()
operators.register()
print("REGISTER_OK")

scene = bpy.data.scenes[0]
props = scene.amt_texture_relink

# poll() should be False with an empty search_directory
props.search_directory = ""
assert bpy.ops.object.amt_relink_textures.poll() is False
print("POLL_EMPTY_DIR_OK")

props.search_directory = r"C:\Users\nunif\AppData\Local\Temp\amt_texture_relink_test3\candidates"
assert bpy.ops.object.amt_relink_textures.poll() is True
print("POLL_WITH_DIR_OK")

img_missing = bpy.data.images.new("TX_Body_A.png", 1, 1)
img_missing.source = 'FILE'
img_missing.filepath = r"C:\amt_nonexistent_folder\TX_Body_A.png"

result = bpy.ops.object.amt_relink_textures()
print("OPERATOR_RESULT:", result)
assert result == {'FINISHED'}
assert img_missing.filepath.endswith("TX_Body_A.png") and "amt_nonexistent_folder" not in img_missing.filepath
print("RELINK_VIA_OPERATOR_OK")

assert len(props.report_lines) >= 1
print("REPORT_LINES:", [(l.level, l.text) for l in props.report_lines])
print("REPORT_LINES_POPULATED_OK")

operators.unregister()
properties.unregister()
core_report.unregister()
print("ALL_OPERATORS_TESTS_PASSED")
```

- [ ] **Step 4: Blenderのheadless実行で検証する**

Run (Bash):
```bash
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --python "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test3/verify_operators.py"
```

Expected: 出力に `ALL_OPERATORS_TESTS_PASSED` が含まれる。`bpy.ops.object.amt_relink_textures.poll()` が `--background` モードのcontextで正しく評価できない場合（`context.scene`が取得できない等のエラー）は、`bpy.context.scene = bpy.data.scenes[0]` を明示するか、`operators.OBJECT_OT_amt_relink_textures.poll(bpy.context)` のようにクラスメソッドを直接呼ぶ形に検証スクリプトを調整すること。

- [ ] **Step 5: テスト用ファイルを削除してコミット**

```bash
rm -rf "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test3"
git add avatar_mesh_toolkit/features/texture_relink/operators.py
git commit -m "Add texture_relink operator"
```

---

### Task 4: `features/texture_relink/panel.py`

**Files:**
- Create: `avatar_mesh_toolkit/features/texture_relink/panel.py`

**Interfaces:**
- Consumes: `avatar_mesh_toolkit.core.ui.TOOLKIT_CATEGORY`（既存）、`properties.AMT_TextureRelinkProperties`（Task 2）、`operators.OBJECT_OT_amt_relink_textures`（Task 3、`bl_idname`文字列経由）、`core.report.AMT_UL_report_lines`（既存）
- Produces: `VIEW3D_PT_amt_texture_relink`。`register()` / `unregister()`。

- [ ] **Step 1: `panel.py` を実装する**

既存パネルの `bl_order` は `hidden_mesh=0`, `texture_bake=1`, `cleanup=2`, `merge=3`, `diagnostics=4` なので、末尾の `5` を割り当てる。

```python
import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_texture_relink(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "テクスチャ再リンク"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_texture_relink

        layout.prop(props, "search_directory")
        layout.operator("object.amt_relink_textures", icon='FILE_REFRESH')

        if len(props.report_lines) > 0:
            layout.separator()
            layout.template_list(
                "AMT_UL_report_lines", "",
                props, "report_lines",
                props, "report_active_index",
                rows=4,
            )


_classes = (VIEW3D_PT_amt_texture_relink,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 2: register()が構文エラーなく通ることを確認する**

このタスク単体でのheadless検証はTask 5（統合登録）で一括して行う。ここではPythonの構文チェックのみ行う。

Run (Bash):
```bash
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --python-expr "import py_compile; py_compile.compile(r'E:\git\BlenderAddon\avatar_mesh_toolkit\features\texture_relink\panel.py', doraise=True); print('COMPILE_OK')"
```

Expected: 出力に `COMPILE_OK` が含まれ、`SyntaxError`が出ないこと。

- [ ] **Step 3: コミット**

```bash
git add avatar_mesh_toolkit/features/texture_relink/panel.py
git commit -m "Add texture_relink panel"
```

---

### Task 5: feature登録 — `features/texture_relink/__init__.py` とトップレベル `__init__.py`

**Files:**
- Create: `avatar_mesh_toolkit/features/texture_relink/__init__.py`
- Modify: `avatar_mesh_toolkit/__init__.py`

**Interfaces:**
- Consumes: Task 2/3/4 の `properties` / `operators` / `panel` モジュール
- Produces: `avatar_mesh_toolkit.features.texture_relink.register()` / `.unregister()`。トップレベル `_modules` に `texture_relink` が追加される。

- [ ] **Step 1: `features/texture_relink/__init__.py` を作成する**

```python
from . import properties, operators, panel

_modules = (properties, operators, panel)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
```

- [ ] **Step 2: トップレベル `avatar_mesh_toolkit/__init__.py` を更新する**

現状（`avatar_mesh_toolkit/__init__.py:13-17`）:

```python
from .core import report as core_report
from .features import cleanup, diagnostics, hidden_mesh, merge, texture_bake

# core_report must register first: feature modules declare CollectionProperty(type=AMT_ReportLine).
_modules = (core_report, hidden_mesh, texture_bake, cleanup, merge, diagnostics)
```

これを以下に置き換える:

```python
from .core import report as core_report
from .features import cleanup, diagnostics, hidden_mesh, merge, texture_bake, texture_relink

# core_report must register first: feature modules declare CollectionProperty(type=AMT_ReportLine).
_modules = (core_report, hidden_mesh, texture_bake, cleanup, merge, diagnostics, texture_relink)
```

- [ ] **Step 3: アドオン全体のregister/unregisterサイクルをheadlessで検証する**

Write to `C:\Users\nunif\AppData\Local\Temp\amt_texture_relink_test5\verify_integration.py`（先に `mkdir -p "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test5"` を実行）:

```python
import sys
sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy
import avatar_mesh_toolkit

avatar_mesh_toolkit.register()
print("REGISTER_OK")

scene = bpy.data.scenes[0]
assert hasattr(scene, "amt_texture_relink")
print("SCENE_PROPERTY_OK")

assert hasattr(bpy.ops.object, "amt_relink_textures")
print("OPERATOR_REGISTERED_OK")

avatar_mesh_toolkit.unregister()
print("UNREGISTER_OK")

print("ALL_INTEGRATION_TESTS_PASSED")
```

Run (Bash):
```bash
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --python "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test5/verify_integration.py"
```

Expected: 出力に `ALL_INTEGRATION_TESTS_PASSED` が含まれ、`register()`/`unregister()`のどちらでも例外が出ないこと。既存の他feature（hidden_mesh, texture_bake等）のregisterが壊れていないことも、このスクリプトの`avatar_mesh_toolkit.register()`が例外なく完走する時点で確認できる。

- [ ] **Step 4: テスト用ファイルを削除してコミット**

```bash
rm -rf "/c/Users/nunif/AppData/Local/Temp/amt_texture_relink_test5"
git add avatar_mesh_toolkit/features/texture_relink/__init__.py avatar_mesh_toolkit/__init__.py
git commit -m "Register texture_relink feature"
```

---

### Task 6: バージョン・ドキュメント更新

**Files:**
- Modify: `avatar_mesh_toolkit/__init__.py`（`bl_info["version"]`、`avatar_mesh_toolkit/__init__.py:4`）
- Modify: `CHANGELOG.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: なし
- Produces: なし（ドキュメントのみ）

- [ ] **Step 1: `bl_info["version"]` を更新する**

`avatar_mesh_toolkit/__init__.py:4` の

```python
    "version": (1, 1, 0),
```

を

```python
    "version": (1, 2, 0),
```

に変更する。

- [ ] **Step 2: `CHANGELOG.md` に追記する**

`CHANGELOG.md` の先頭（`# Changelog` の直後、`## 1.1.0` の前）に以下を挿入する:

```markdown
## 1.2.0

- テクスチャ再リンク: 欠落しているテクスチャ画像(ファイルパスが見つからない状態)を、指定フォルダから検索して自動的に再リンクする機能を追加
  - 完全一致 → 拡張子/大文字小文字/Blenderの重複サフィックス(`.001`等)違いを許容した名前一致 → 部分一致、の3段階でマッチングし、同一レベルで複数候補がある場合は自動選択せず一覧表示
  - BOOTHで購入したアバターのFBX/Blendインポート時に、テクスチャパスのズレでビューポート上に紫/ピンク表示になるケースの解消を想定

```

- [ ] **Step 3: `README.md` に使い方セクションを追加する**

`README.md` の「## 各機能の使い方」内、「### 5. 統計/書き出し前チェック」セクション（`README.md:72-82`）の直後、「## 全般的な注意事項」（`README.md:84`）の前に以下を挿入する:

```markdown
### 6. テクスチャ再リンク

BOOTHで購入したアバターのFBX/Blendファイルを読み込んだ際、テクスチャ画像が見つからない(ビューポート上で紫/ピンク表示や欠落アイコンになる)ことがあります。この機能は、その欠落しているテクスチャ画像を、指定したフォルダから探して自動的に再リンクします。

1. 「検索フォルダ」に、テクスチャファイルが入っているフォルダを指定します(サブフォルダも再帰的に検索します)。
2. 「欠落テクスチャを再リンク」を実行します。
3. 結果が下部にレポート表示されます。画像ごとに「再リンクしました」「候補が複数あるためスキップしました」「見つかりませんでした」のいずれかが表示されます。

**マッチングの仕組み(優先順位順):**
1. 画像名とファイル名が完全に一致するもの。
2. 拡張子の違い・大文字小文字の違い・Blenderが付与する重複サフィックス(`.001`等)の違いを許容して名前が一致するもの。
3. 名前の一部が一致するもの(部分一致)。
4. 同じ一致レベルで候補が複数見つかった場合は、誤ったファイルを自動選択しないよう再リンクせず、レポートに候補を列挙します。手動で個別に対応してください。

**重要な注意点:**
- あくまでフォルダ内に実在するファイルとの再リンクのみを行います。テクスチャファイル自体が手元に存在しない場合はこの機能では解決できません。
- FBXインポート時にテクスチャノード自体が作成されなかった場合(画像データブロックがそもそも存在しない場合)は対象外です。

```

- [ ] **Step 4: コミット**

```bash
git add avatar_mesh_toolkit/__init__.py CHANGELOG.md README.md
git commit -m "Bump version to 1.2.0 and document texture-relink feature"
```

---

### Task 7: Blender GUIでの最終手動確認（管理人依頼）

このタスクはGUI操作を伴うため、技師（Bashのみ）では実行できない。管理人に以下の手順で確認を依頼する。

**Files:** なし（確認のみ）

- [ ] **Step 1: アドオンをBlenderにインストールする**

`編集 > プリファレンス > アドオン > インストール` から `avatar_mesh_toolkit` フォルダをZIP圧縮したものを選択し、有効化する（`README.md` の「インストール」節の手順通り）。既にインストール済みの場合は、一度無効化→再度有効化してリロードする。

- [ ] **Step 2: サイドバーに新規パネルが表示されることを確認する**

3Dビューポートのサイドバー(`N`キー)の「Avatar Toolkit」タブに「テクスチャ再リンク」パネルが追加されていることを確認する。

- [ ] **Step 3: 実際に欠落テクスチャがあるファイルで動作確認する**

テクスチャ本体が別フォルダにあるBlend/FBXファイル（Komane.blendは対象外 — テクスチャ本体が存在しないため）を用意し、「検索フォルダ」にテクスチャの実在するフォルダを指定して「欠落テクスチャを再リンク」を実行、ビューポート上のマテリアル表示が正常に戻ることを確認する。

- [ ] **Step 4: 結果を報告する**

期待通りに動作しない場合は、レポート欄の表示内容とともに問題を報告する。
