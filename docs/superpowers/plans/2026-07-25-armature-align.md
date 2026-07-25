# アーマチュア位置合わせ機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 指定したボーン(既定ではHips)のレストポーズ・ワールド座標が一致するように、対象Armatureオブジェクトを平行移動する新規feature `armature_align` を `NuniAvatarToolkit` に追加する。

**Architecture:** 既存 `features/<name>/` の4ファイル構成(properties/operators/panel/utils)を踏襲する独立featureとして実装する。ボーンのレストポーズ・ワールド座標は `armature_object.matrix_world @ armature_object.data.bones[name].head_local` で求め、対象Armatureオブジェクトの `matrix_world` を平行移動することで、`location` が `(0,0,0)` 同士でもボーン配置の差(例: ハイヒール差分)を正しく解消する。

**Tech Stack:** Python(Blender 3.6+ 内蔵 `bpy`)、既存の `core/report.py`(`AMT_ReportLine`/`set_report_lines`/`AMT_UL_report_lines`)パターン。

## Global Constraints

- 対象は「同じアバターの別バージョン同士」のように、ボーン構成が共通で配置だけが違うArmature。位置(平行移動)のみを一致させ、回転・スケールは変更しない。
- レストポーズ(Edit Modeでのボーン配置)を基準とする。現在のポーズ(Pose Mode)は見ない。
- Operator: `bl_idname = "object.amt_align_armature"`, `bl_options = {'REGISTER', 'UNDO'}`。確認ダイアログ(`invoke_props_dialog`)は不要(オブジェクトのTransformを変更するのみで、メッシュ・ボーン・ウェイトを破壊しないため)。
- Scene property: `bpy.types.Scene.amt_armature_align`。
- Panel: `bl_idname = "VIEW3D_PT_amt_armature_align"`, `bl_label = "アーマチュア位置合わせ"`, `bl_order = 6`, `bl_category` は `core/ui.py` の `TOOLKIT_CATEGORY` を使う。既存パネル(`hidden_mesh`を除く全て)にならい `bl_options = {'DEFAULT_CLOSED'}` を付ける。
- ボーン名は"Hips"固定にせず、UIで選び直せるようにする(VRM等の日本語命名リグに対応するため)。自動探索は完全一致("hips")を含有一致より優先する。
- 子メッシュ(Armatureモディファイアで紐づくが対象Armatureの子孫でないメッシュ)は移動しない。警告としてレポートに列挙するに留める。
- UI文字列(`name`/`description`/`bl_label`/レポート文言)は日本語。コード内コメント・docstringは既存の他feature(`texture_relink`等)に合わせて英語。
- 自動テストは無し(プロジェクト全体方針)。各タスクの検証はBlenderのheadless実行(`blender.exe --background --python <script>`)で行う。Blender実行ファイル: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`。
- エラーハンドリング(`operators.py`の`execute()`内でのチェック順序):
  1. 基準と対象に同じオブジェクトが指定されている → `{'ERROR'}` 「基準Armatureと対象Armatureに同じオブジェクトが指定されています」→ `{'CANCELLED'}`
  2. `reference_bone` または `target_bone` が空 → `{'ERROR'}` 「ボーンを指定してください」→ `{'CANCELLED'}`
  3. 対象Armatureが編集不可(`target_object.library is not None` または `target_object.override_library is not None`) → `{'ERROR'}` 「対象Armatureはリンクされているため移動できません」→ `{'CANCELLED'}`
  4. 指定ボーン名が該当Armatureに存在しない(`utils.compute_alignment_delta`が`ValueError`を送出) → `{'ERROR'}` にそのメッセージを使う → `{'CANCELLED'}`
  5. 移動量が実質0(`delta.length < 1e-6`) → エラーではなく`INFO`で「既に一致しています」をレポートして `{'FINISHED'}`

---

### Task 1: `armature_align/utils.py` 実装

**Files:**
- Create: `NuniAvatarToolkit/features/armature_align/utils.py`

**Interfaces:**
- Consumes: なし(このタスクは他タスクに依存しない)
- Produces:
  - `find_hips_bone(armature_data) -> str` — `armature_data`は`bpy.types.Armature`。見つからなければ`""`。
  - `get_bone_rest_world_head(obj, bone_name) -> mathutils.Vector` — `bone_name`が存在しない場合`ValueError`を送出。
  - `compute_alignment_delta(reference_object, reference_bone, target_object, target_bone) -> mathutils.Vector`
  - `find_orphan_armature_meshes(target_object) -> list[str]`
  - `apply_alignment(target_object, delta) -> None`

- [ ] **Step 1: `NuniAvatarToolkit/features/armature_align/utils.py` を作成する**

```python
"""Pure logic for features/armature_align. No bpy.types classes are defined here,
but the functions directly use bpy.types.Object/Armature data, so this module
cannot be imported outside Blender runtime.
"""

import bpy


def find_hips_bone(armature_data):
    """Search armature_data.bones for a bone name containing "hips" (case-insensitive).
    An exact match (case-insensitive equality to "hips") is preferred over a substring
    match, so "Hips" is chosen over "Hips_end" when both exist.
    Returns "" if no matching bone is found."""
    exact_match = ""
    partial_match = ""
    for bone in armature_data.bones:
        lower_name = bone.name.lower()
        if lower_name == "hips":
            exact_match = bone.name
            break
        if "hips" in lower_name and not partial_match:
            partial_match = bone.name
    return exact_match or partial_match


def get_bone_rest_world_head(obj, bone_name):
    """Return the world-space rest-pose head position of bone_name on obj (an Armature object).
    obj.data.bones[bone_name].head_local is in armature-object-local space at rest pose;
    multiplying by obj.matrix_world yields world coordinates even when obj.location is (0, 0, 0).
    Raises ValueError if bone_name does not exist on obj."""
    if bone_name not in obj.data.bones:
        raise ValueError(f"ボーン『{bone_name}』が見つかりません")
    bone = obj.data.bones[bone_name]
    return obj.matrix_world @ bone.head_local


def compute_alignment_delta(reference_object, reference_bone, target_object, target_bone):
    """Return the world-space translation vector that would move target_bone's rest head
    onto reference_bone's rest head."""
    reference_head = get_bone_rest_world_head(reference_object, reference_bone)
    target_head = get_bone_rest_world_head(target_object, target_bone)
    return reference_head - target_head


def find_orphan_armature_meshes(target_object):
    """Return names of mesh objects in the scene that have an Armature modifier referencing
    target_object, but are not descendants of target_object. These meshes will not follow
    target_object when it is moved, since only the armature object itself is translated."""
    orphans = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        references_target = any(
            mod.type == 'ARMATURE' and mod.object == target_object
            for mod in obj.modifiers
        )
        if not references_target:
            continue
        ancestor = obj.parent
        is_descendant = False
        while ancestor is not None:
            if ancestor == target_object:
                is_descendant = True
                break
            ancestor = ancestor.parent
        if not is_descendant:
            orphans.append(obj.name)
    return orphans


def apply_alignment(target_object, delta):
    """Translate target_object by delta in world space. Using matrix_world (rather than
    directly adding to target_object.location) correctly accounts for any parent's
    rotation/scale, so the requested world-space delta is achieved even when target_object
    is parented to another object."""
    mw = target_object.matrix_world.copy()
    mw.translation += delta
    target_object.matrix_world = mw
```

- [ ] **Step 2: 構文チェック**

Run: `python -m py_compile NuniAvatarToolkit/features/armature_align/utils.py`
Expected: エラーなく終了する(出力なし)。

- [ ] **Step 3: Blender headlessで検証する**

検証スクリプトを作成する(パスは任意のスクラッチ領域でよい、以下は例):

```python
import sys

sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy

from NuniAvatarToolkit.features.armature_align import utils

bpy.ops.wm.read_factory_settings(use_empty=True)

# 基準Armature: Hipsボーンの高さ1.0、オブジェクトlocationは(0,0,0)
bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
ref_arm = bpy.context.object
ref_arm.name = "RefArmature"
edit_bones = ref_arm.data.edit_bones
edit_bones.remove(edit_bones[0])
hips = edit_bones.new("Hips")
hips.head = (0, 0, 1.0)
hips.tail = (0, 0, 1.2)
bpy.ops.object.mode_set(mode='OBJECT')

# 対象Armature: Hipsボーンの高さ0.9(ハイヒール差分を模擬)、オブジェクトlocationも(0,0,0)
bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
tgt_arm = bpy.context.object
tgt_arm.name = "TargetArmature"
edit_bones2 = tgt_arm.data.edit_bones
edit_bones2.remove(edit_bones2[0])
hips2 = edit_bones2.new("Hips")
hips2.head = (0, 0, 0.9)
hips2.tail = (0, 0, 1.1)
bpy.ops.object.mode_set(mode='OBJECT')

assert utils.find_hips_bone(ref_arm.data) == "Hips", utils.find_hips_bone(ref_arm.data)

ref_head = utils.get_bone_rest_world_head(ref_arm, "Hips")
tgt_head = utils.get_bone_rest_world_head(tgt_arm, "Hips")
assert abs(ref_head.z - 1.0) < 1e-6, ref_head
assert abs(tgt_head.z - 0.9) < 1e-6, tgt_head
assert ref_arm.location.z == 0.0 and tgt_arm.location.z == 0.0

delta = utils.compute_alignment_delta(ref_arm, "Hips", tgt_arm, "Hips")
assert abs(delta.z - 0.1) < 1e-6, delta

try:
    utils.get_bone_rest_world_head(ref_arm, "NoSuchBone")
    raise AssertionError("ValueErrorが発生するはず")
except ValueError:
    pass

utils.apply_alignment(tgt_arm, delta)
new_head = utils.get_bone_rest_world_head(tgt_arm, "Hips")
assert abs(new_head.z - ref_head.z) < 1e-6, new_head
assert abs(tgt_arm.location.z - 0.1) < 1e-6, tgt_arm.location

assert utils.find_orphan_armature_meshes(tgt_arm) == []

bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
mod = cube.modifiers.new("Armature", 'ARMATURE')
mod.object = tgt_arm
orphans = utils.find_orphan_armature_meshes(tgt_arm)
assert orphans == [cube.name], orphans

cube.parent = tgt_arm
orphans2 = utils.find_orphan_armature_meshes(tgt_arm)
assert orphans2 == [], orphans2

print("TASK1_ARMATURE_ALIGN_VERIFY_OK")
```

このスクリプトをファイルに保存し、実行する。

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <保存したスクリプトのパス>`
Expected: 標準出力の末尾に `TASK1_ARMATURE_ALIGN_VERIFY_OK` が出力され、`AssertionError`等の例外が発生しないこと。

- [ ] **Step 4: Commit**

```bash
git add NuniAvatarToolkit/features/armature_align/utils.py
git commit -m "Add armature_align/utils.py with rest-pose bone alignment logic"
```

---

### Task 2: `armature_align/properties.py` 実装

**Files:**
- Create: `NuniAvatarToolkit/features/armature_align/properties.py`

**Interfaces:**
- Consumes: Task 1の `utils.find_hips_bone(armature_data) -> str`
- Produces:
  - `AMT_ArmatureAlignProperties(bpy.types.PropertyGroup)` — フィールド: `reference_object`(Object, Armatureのみ), `reference_bone`(str), `target_object`(Object, Armatureのみ), `target_bone`(str), `report_lines`(Collection of `AMT_ReportLine`), `report_active_index`(int)
  - `register() -> None` / `unregister() -> None` — `bpy.types.Scene.amt_armature_align` に `AMT_ArmatureAlignProperties` を生やす/削除する

- [ ] **Step 1: `NuniAvatarToolkit/features/armature_align/properties.py` を作成する**

```python
import bpy

from ...core.report import AMT_ReportLine
from . import utils


def _armature_object_poll(self, obj):
    return obj.type == 'ARMATURE'


def _on_reference_object_update(self, context):
    obj = self.reference_object
    if obj is None:
        return
    if self.reference_bone and self.reference_bone in obj.data.bones:
        return
    self.reference_bone = utils.find_hips_bone(obj.data)


def _on_target_object_update(self, context):
    obj = self.target_object
    if obj is None:
        return
    if self.target_bone and self.target_bone in obj.data.bones:
        return
    self.target_bone = utils.find_hips_bone(obj.data)


class AMT_ArmatureAlignProperties(bpy.types.PropertyGroup):
    reference_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="基準Armature",
        description="移動させずに基準とするArmatureを指定してください",
        poll=_armature_object_poll,
        update=_on_reference_object_update,
    )
    reference_bone: bpy.props.StringProperty(name="基準ボーン")

    target_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="対象Armature",
        description="位置を合わせて移動させるArmatureを指定してください",
        poll=_armature_object_poll,
        update=_on_target_object_update,
    )
    target_bone: bpy.props.StringProperty(name="対象ボーン")

    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_ArmatureAlignProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_armature_align = bpy.props.PointerProperty(type=AMT_ArmatureAlignProperties)


def unregister():
    del bpy.types.Scene.amt_armature_align
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 2: 構文チェック**

Run: `python -m py_compile NuniAvatarToolkit/features/armature_align/properties.py`
Expected: エラーなく終了する。

- [ ] **Step 3: Blender headlessで検証する**

`properties.py`は`from ...core.report import AMT_ReportLine`という相対importを使うため、完全修飾パッケージ名でアクセスする(`sys.path`にリポジトリルートを追加し、`NuniAvatarToolkit.features.armature_align.properties`としてimportする)。

検証スクリプトを作成する:

```python
import sys

sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy

from NuniAvatarToolkit.core import report as core_report
from NuniAvatarToolkit.features.armature_align import properties

core_report.register()
properties.register()

assert hasattr(bpy.types.Scene, "amt_armature_align")

bpy.ops.wm.read_factory_settings(use_empty=True)

# 注意: PointerPropertyのpollはUIの選択ダイアログ(検索/ドロップダウン)の候補を絞るだけで、
# Pythonからの直接代入(props.reference_object = obj)は防がない。そのため「Mesh以外弾かれる」
# ことのテストはpoll関数を直接呼び出して行う。

class _FakeSelf:
    pass


fake_self = _FakeSelf()
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
assert properties._armature_object_poll(fake_self, cube) is False, (
    "MeshオブジェクトはpollでFalseを返すはず"
)

# Armatureは受け付け、update callbackでHipsボーンが自動選択されること
bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
arm = bpy.context.object
arm.name = "TestArmature"
edit_bones = arm.data.edit_bones
edit_bones.remove(edit_bones[0])
hips = edit_bones.new("Hips")
hips.head = (0, 0, 1.0)
hips.tail = (0, 0, 1.2)
bpy.ops.object.mode_set(mode='OBJECT')

props = bpy.context.scene.amt_armature_align
props.reference_object = arm
assert props.reference_object == arm
assert props.reference_bone == "Hips", props.reference_bone

# 既に別のボーン名が入っていて、それが新しいオブジェクトにも存在する場合は上書きされないこと
bpy.ops.object.armature_add(enter_editmode=True, location=(2, 0, 0))
arm2 = bpy.context.object
arm2.name = "TestArmature2"
edit_bones2 = arm2.data.edit_bones
edit_bones2.remove(edit_bones2[0])
hips_bone2 = edit_bones2.new("Hips")
hips_bone2.head = (0, 0, 1.0)
hips_bone2.tail = (0, 0, 1.2)
other_bone2 = edit_bones2.new("Chest")
other_bone2.head = (0, 0, 1.3)
other_bone2.tail = (0, 0, 1.5)
bpy.ops.object.mode_set(mode='OBJECT')

props.reference_bone = "Chest"
props.reference_object = arm2
assert props.reference_bone == "Chest", (
    f"既存の有効なボーン名は上書きされないはず: {props.reference_bone}"
)

properties.unregister()
core_report.unregister()
assert not hasattr(bpy.types.Scene, "amt_armature_align")

print("TASK2_ARMATURE_ALIGN_VERIFY_OK")
```

このスクリプトをファイルに保存し、実行する。

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <保存したスクリプトのパス>`
Expected: 標準出力の末尾に `TASK2_ARMATURE_ALIGN_VERIFY_OK` が出力され、例外が発生しないこと。

- [ ] **Step 4: Commit**

```bash
git add NuniAvatarToolkit/features/armature_align/properties.py
git commit -m "Add armature_align/properties.py with armature/bone selection state"
```

---

### Task 3: `armature_align/operators.py` 実装

**Files:**
- Create: `NuniAvatarToolkit/features/armature_align/operators.py`

**Interfaces:**
- Consumes:
  - Task 1: `utils.compute_alignment_delta`, `utils.apply_alignment`, `utils.find_orphan_armature_meshes`
  - Task 2: `bpy.types.Scene.amt_armature_align`(`reference_object`, `reference_bone`, `target_object`, `target_bone`, `report_lines`, `report_active_index`)
  - `core/report.py`: `set_report_lines(collection_prop, [(level, text), ...])`
- Produces: `OBJECT_OT_amt_align_armature(bpy.types.Operator)`, `bl_idname = "object.amt_align_armature"`

- [ ] **Step 1: `NuniAvatarToolkit/features/armature_align/operators.py` を作成する**

```python
import bpy

from ...core.report import set_report_lines
from . import utils


class OBJECT_OT_amt_align_armature(bpy.types.Operator):
    bl_idname = "object.amt_align_armature"
    bl_label = "位置を合わせる"
    bl_description = "対象Armatureを平行移動し、指定ボーンのレストポーズ・ワールド座標を基準Armature側と一致させます"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_armature_align
        return props.reference_object is not None and props.target_object is not None

    def execute(self, context):
        props = context.scene.amt_armature_align
        reference_object = props.reference_object
        target_object = props.target_object

        if reference_object == target_object:
            self.report({'ERROR'}, "基準Armatureと対象Armatureに同じオブジェクトが指定されています")
            return {'CANCELLED'}

        if not props.reference_bone or not props.target_bone:
            self.report({'ERROR'}, "ボーンを指定してください")
            return {'CANCELLED'}

        if target_object.library is not None or target_object.override_library is not None:
            self.report({'ERROR'}, "対象Armatureはリンクされているため移動できません")
            return {'CANCELLED'}

        try:
            delta = utils.compute_alignment_delta(
                reference_object, props.reference_bone, target_object, props.target_bone,
            )
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        if delta.length < 1e-6:
            set_report_lines(props.report_lines, [('INFO', "既に一致しています")])
            self.report({'INFO'}, "既に一致しています")
            return {'FINISHED'}

        utils.apply_alignment(target_object, delta)

        lines = [
            ('INFO', f"基準「{reference_object.name} / {props.reference_bone}」、"
                     f"対象「{target_object.name} / {props.target_bone}」"),
            ('INFO', f"移動量 X={delta.x:.4f}, Y={delta.y:.4f}, Z={delta.z:.4f}"),
        ]
        orphans = utils.find_orphan_armature_meshes(target_object)
        if orphans:
            lines.append((
                'WARNING',
                "次のメッシュは対象Armatureの子ではないため移動していません: " + ", ".join(orphans),
            ))

        set_report_lines(props.report_lines, lines)
        self.report({'INFO'}, f"移動しました(X={delta.x:.4f}, Y={delta.y:.4f}, Z={delta.z:.4f})")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_align_armature,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 2: 構文チェック**

Run: `python -m py_compile NuniAvatarToolkit/features/armature_align/operators.py`
Expected: エラーなく終了する。

- [ ] **Step 3: Blender headlessで検証する**

検証スクリプトを作成する(Task 1と同様のHips差分シーンを組み立て、オペレータを実行する):

```python
import sys

sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy

from NuniAvatarToolkit.core import report as core_report
from NuniAvatarToolkit.features.armature_align import properties, operators

core_report.register()
properties.register()
operators.register()

bpy.ops.wm.read_factory_settings(use_empty=True)

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
ref_arm = bpy.context.object
ref_arm.name = "RefArmature"
eb = ref_arm.data.edit_bones
eb.remove(eb[0])
hips = eb.new("Hips")
hips.head = (0, 0, 1.0)
hips.tail = (0, 0, 1.2)
bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
tgt_arm = bpy.context.object
tgt_arm.name = "TargetArmature"
eb2 = tgt_arm.data.edit_bones
eb2.remove(eb2[0])
hips2 = eb2.new("Hips")
hips2.head = (0, 0, 0.9)
hips2.tail = (0, 0, 1.1)
bpy.ops.object.mode_set(mode='OBJECT')

props = bpy.context.scene.amt_armature_align
props.reference_object = ref_arm
props.target_object = tgt_arm
assert props.reference_bone == "Hips" and props.target_bone == "Hips"

# poll: 両方設定済みなのでTrueのはず
assert bpy.ops.object.amt_align_armature.poll()

# 実行: Z方向に0.1移動するはず
result = bpy.ops.object.amt_align_armature()
assert result == {'FINISHED'}, result
assert abs(tgt_arm.location.z - 0.1) < 1e-6, tgt_arm.location
assert len(props.report_lines) >= 2, len(props.report_lines)

# 同じオブジェクトを指定した場合はCANCELLEDでエラーになること
props.target_object = ref_arm
result2 = bpy.ops.object.amt_align_armature()
assert result2 == {'CANCELLED'}, result2
props.target_object = tgt_arm

# ボーン名が不正な場合はCANCELLEDでエラーになり、Transformが変わらないこと
props.target_bone = "NoSuchBone"
loc_before = tgt_arm.location.copy()
result3 = bpy.ops.object.amt_align_armature()
assert result3 == {'CANCELLED'}, result3
assert tgt_arm.location == loc_before
props.target_bone = "Hips"

# 既に一致している状態で実行すると、エラーではなくFINISHEDで「既に一致しています」
result4 = bpy.ops.object.amt_align_armature()
assert result4 == {'FINISHED'}, result4
assert any("既に一致しています" in line.text for line in props.report_lines), [
    line.text for line in props.report_lines
]

operators.unregister()
properties.unregister()
core_report.unregister()

print("TASK3_ARMATURE_ALIGN_VERIFY_OK")
```

このスクリプトをファイルに保存し、実行する。

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <保存したスクリプトのパス>`
Expected: 標準出力の末尾に `TASK3_ARMATURE_ALIGN_VERIFY_OK` が出力され、例外が発生しないこと。

Undo(`bpy.ops.ed.undo()`)による巻き戻し確認はこのスクリプトには含めない。`--background`モードはウィンドウ/画面コンテキストを持たないため、`bpy.ops.ed.undo()`は`RuntimeError: ... context is incorrect`で必ず失敗する(実機で確認済み)。この確認は本タスク末尾の「実装後の確認(管理人依頼)」でGUI起動時に行う。

- [ ] **Step 4: 親付けされたメッシュが一緒に移動することを検証する**

`apply_alignment`は対象Armatureオブジェクトの`matrix_world`のみを変更する。Blenderの親子関係では、子オブジェクトのワールド行列は親のワールド行列から自動的に再計算されるため、対象Armatureに親付けされたメッシュも追従して移動するはずである。これを`bpy.context.view_layer.update()`後に子オブジェクトのワールド座標を読み取って確認する。

検証スクリプトを作成する:

```python
import sys

sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy

from NuniAvatarToolkit.core import report as core_report
from NuniAvatarToolkit.features.armature_align import properties, operators

core_report.register()
properties.register()
operators.register()

bpy.ops.wm.read_factory_settings(use_empty=True)

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
ref_arm = bpy.context.object
ref_arm.name = "RefArmature"
eb = ref_arm.data.edit_bones
eb.remove(eb[0])
hips = eb.new("Hips")
hips.head = (0, 0, 1.0)
hips.tail = (0, 0, 1.2)
bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
tgt_arm = bpy.context.object
tgt_arm.name = "TargetArmature"
eb2 = tgt_arm.data.edit_bones
eb2.remove(eb2[0])
hips2 = eb2.new("Hips")
hips2.head = (0, 0, 0.9)
hips2.tail = (0, 0, 1.1)
bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0.5))
cube = bpy.context.object
mod = cube.modifiers.new("Armature", 'ARMATURE')
mod.object = tgt_arm
cube.parent = tgt_arm
cube.matrix_parent_inverse = tgt_arm.matrix_world.inverted()

bpy.context.view_layer.update()
cube_world_before = cube.matrix_world.translation.copy()

props = bpy.context.scene.amt_armature_align
props.reference_object = ref_arm
props.target_object = tgt_arm

result = bpy.ops.object.amt_align_armature()
assert result == {'FINISHED'}, result

bpy.context.view_layer.update()
cube_world_after = cube.matrix_world.translation.copy()

assert abs((cube_world_after.z - cube_world_before.z) - 0.1) < 1e-6, (
    f"親付けされたメッシュが対象Armatureと一緒にZ方向へ0.1移動していない: "
    f"before={cube_world_before}, after={cube_world_after}"
)

operators.unregister()
properties.unregister()
core_report.unregister()

print("TASK3_PARENTED_MESH_FOLLOWS_VERIFY_OK")
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <保存したスクリプトのパス>`
Expected: `TASK3_PARENTED_MESH_FOLLOWS_VERIFY_OK` が出力される。

- [ ] **Step 5: 孤立メッシュの警告を検証する**

検証スクリプトを作成する(対象Armatureに親付けされていないメッシュがある場合の警告レポートを確認):

```python
import sys

sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy

from NuniAvatarToolkit.core import report as core_report
from NuniAvatarToolkit.features.armature_align import properties, operators

core_report.register()
properties.register()
operators.register()

bpy.ops.wm.read_factory_settings(use_empty=True)

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
ref_arm = bpy.context.object
ref_arm.name = "RefArmature"
eb = ref_arm.data.edit_bones
eb.remove(eb[0])
hips = eb.new("Hips")
hips.head = (0, 0, 1.0)
hips.tail = (0, 0, 1.2)
bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
tgt_arm = bpy.context.object
tgt_arm.name = "TargetArmature"
eb2 = tgt_arm.data.edit_bones
eb2.remove(eb2[0])
hips2 = eb2.new("Hips")
hips2.head = (0, 0, 0.9)
hips2.tail = (0, 0, 1.1)
bpy.ops.object.mode_set(mode='OBJECT')

bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
mod = cube.modifiers.new("Armature", 'ARMATURE')
mod.object = tgt_arm
# 親付けはしない(孤立メッシュにするため)

props = bpy.context.scene.amt_armature_align
props.reference_object = ref_arm
props.target_object = tgt_arm

result = bpy.ops.object.amt_align_armature()
assert result == {'FINISHED'}, result
warning_lines = [line.text for line in props.report_lines if line.level == 'WARNING']
assert any(cube.name in text for text in warning_lines), warning_lines

operators.unregister()
properties.unregister()
core_report.unregister()

print("TASK3_ORPHAN_WARNING_VERIFY_OK")
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <保存したスクリプトのパス>`
Expected: `TASK3_ORPHAN_WARNING_VERIFY_OK` が出力される。

- [ ] **Step 6: Commit**

```bash
git add NuniAvatarToolkit/features/armature_align/operators.py
git commit -m "Add armature_align/operators.py with the align-armature operator"
```

---

### Task 4: `armature_align/panel.py` 実装

**Files:**
- Create: `NuniAvatarToolkit/features/armature_align/panel.py`

**Interfaces:**
- Consumes: Task 2の`AMT_ArmatureAlignProperties`のフィールド名(`reference_object`, `reference_bone`, `target_object`, `target_bone`, `report_lines`, `report_active_index`)、Task 3の`bl_idname = "object.amt_align_armature"`、`core/report.py`の`AMT_UL_report_lines`(UIListクラス名として文字列参照)、`core/ui.py`の`TOOLKIT_CATEGORY`
- Produces: `VIEW3D_PT_amt_armature_align(bpy.types.Panel)`

- [ ] **Step 1: `NuniAvatarToolkit/features/armature_align/panel.py` を作成する**

```python
import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_armature_align(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "アーマチュア位置合わせ"
    bl_order = 6
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_armature_align

        layout.prop(props, "reference_object")
        if props.reference_object is not None:
            layout.prop_search(props, "reference_bone", props.reference_object.data, "bones")

        layout.prop(props, "target_object")
        if props.target_object is not None:
            layout.prop_search(props, "target_bone", props.target_object.data, "bones")

        layout.operator("object.amt_align_armature", icon='SNAP_ON')

        if len(props.report_lines) > 0:
            layout.separator()
            layout.template_list(
                "AMT_UL_report_lines", "",
                props, "report_lines",
                props, "report_active_index",
                rows=4,
            )


_classes = (VIEW3D_PT_amt_armature_align,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
```

- [ ] **Step 2: 構文チェック**

Run: `python -m py_compile NuniAvatarToolkit/features/armature_align/panel.py`
Expected: エラーなく終了する。

- [ ] **Step 3: Blender headlessで検証する**

検証スクリプトを作成する(パネルの登録・クラス属性・draw()がエラーにならないことを確認する。`draw()`はUIレイアウト無しでは通常呼べないため、代わりにBlenderの`bl_rna`経由でクラスが正しく登録されていること、`bl_category`/`bl_order`/`bl_idname`の値、および依存関係(`report`, `properties`, `operators`)を先に登録した状態でモジュール自体がエラー無くregister/unregisterできることを確認する):

```python
import sys

sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy

from NuniAvatarToolkit.core import report as core_report
from NuniAvatarToolkit.features.armature_align import properties, operators, panel

core_report.register()
properties.register()
operators.register()
panel.register()

cls = bpy.types.VIEW3D_PT_amt_armature_align
assert cls.bl_category == "Avatar Toolkit", cls.bl_category
assert cls.bl_label == "アーマチュア位置合わせ", cls.bl_label
assert cls.bl_order == 6, cls.bl_order
assert cls.bl_idname == "VIEW3D_PT_amt_armature_align", cls.bl_idname

panel.unregister()
operators.unregister()
properties.unregister()
core_report.unregister()

print("TASK4_ARMATURE_ALIGN_VERIFY_OK")
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <保存したスクリプトのパス>`
Expected: `TASK4_ARMATURE_ALIGN_VERIFY_OK` が出力される。

- [ ] **Step 4: Commit**

```bash
git add NuniAvatarToolkit/features/armature_align/panel.py
git commit -m "Add armature_align/panel.py with the sidebar UI"
```

---

### Task 5: feature登録

**Files:**
- Create: `NuniAvatarToolkit/features/armature_align/__init__.py`
- Modify: `NuniAvatarToolkit/__init__.py`

**Interfaces:**
- Consumes: Task 2/3/4の`properties`/`operators`/`panel`モジュール(それぞれ`register()`/`unregister()`を持つ)
- Produces: トップレベルの`register()`/`unregister()`から`armature_align`featureが呼び出される状態

- [ ] **Step 1: `NuniAvatarToolkit/features/armature_align/__init__.py` を作成する**

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

- [ ] **Step 2: `NuniAvatarToolkit/__init__.py` を修正する**

現在の内容(該当箇所):
```python
from .core import report as core_report
from .features import cleanup, diagnostics, hidden_mesh, merge, texture_bake, texture_relink

# core_report must register first: feature modules declare CollectionProperty(type=AMT_ReportLine).
_modules = (core_report, hidden_mesh, texture_bake, cleanup, merge, diagnostics, texture_relink)
```

これを以下に置き換える:
```python
from .core import report as core_report
from .features import armature_align, cleanup, diagnostics, hidden_mesh, merge, texture_bake, texture_relink

# core_report must register first: feature modules declare CollectionProperty(type=AMT_ReportLine).
_modules = (core_report, hidden_mesh, texture_bake, cleanup, merge, diagnostics, texture_relink, armature_align)
```

- [ ] **Step 3: Blender headlessでアドオン全体のregister/unregisterを検証する**

`NuniAvatarToolkit`パッケージをリポジトリのパスから直接importし、`register()`/`unregister()`を呼ぶことで、Blenderのscript_directories登録を経由せずに検証する。

検証スクリプトを作成する:

```python
import sys

sys.path.insert(0, r"E:\git\BlenderAddon")
import bpy

import NuniAvatarToolkit

NuniAvatarToolkit.register()

assert hasattr(bpy.types.Scene, "amt_armature_align")
assert hasattr(bpy.types.Scene, "amt_texture_relink")  # 既存featureも無事なことの確認
assert "object.amt_align_armature" in dir(bpy.ops.object)

NuniAvatarToolkit.unregister()

assert not hasattr(bpy.types.Scene, "amt_armature_align")

print("TASK5_ARMATURE_ALIGN_VERIFY_OK")
```

このスクリプトをファイルに保存し、実行する。

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python <保存したスクリプトのパス>`
Expected: 標準出力の末尾に `TASK5_ARMATURE_ALIGN_VERIFY_OK` が出力され、例外が発生しないこと。特に、既存の`texture_relink`等の登録が壊れていないこと(`amt_texture_relink`が存在すること)を確認する。

- [ ] **Step 4: Commit**

```bash
git add NuniAvatarToolkit/features/armature_align/__init__.py NuniAvatarToolkit/__init__.py
git commit -m "Register armature_align feature in the top-level addon module"
```

---

### Task 6: バージョン・ドキュメント更新

**Files:**
- Modify: `NuniAvatarToolkit/__init__.py`(`bl_info`)
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: なし(ドキュメントのみ)
- Produces: なし

- [ ] **Step 1: `NuniAvatarToolkit/__init__.py` の `bl_info` を更新する**

現在:
```python
bl_info = {
    "name": "NuniAvatarToolkit",
    "author": "Nunifuchisaka",
    "version": (1, 2, 0),
    "blender": (3, 6, 0),
    "location": "3Dビューポート > サイドバー(Nキー) > Avatar Toolkit",
    "description": "VRChat/VRMアバター向けのメッシュ最適化ツール集(隠れメッシュ削除・テクスチャベイク・テクスチャ再リンク・不要データ削除・統合・診断)",
    "category": "Mesh",
    "doc_url": "",
    "tracker_url": "",
}
```

これを以下に置き換える(`version`を`(1, 3, 0)`に、`description`に機能名を追加):
```python
bl_info = {
    "name": "NuniAvatarToolkit",
    "author": "Nunifuchisaka",
    "version": (1, 3, 0),
    "blender": (3, 6, 0),
    "location": "3Dビューポート > サイドバー(Nキー) > Avatar Toolkit",
    "description": "VRChat/VRMアバター向けのメッシュ最適化ツール集(隠れメッシュ削除・テクスチャベイク・テクスチャ再リンク・アーマチュア位置合わせ・不要データ削除・統合・診断)",
    "category": "Mesh",
    "doc_url": "",
    "tracker_url": "",
}
```

- [ ] **Step 2: `README.md` の冒頭機能一覧に1行追加する**

`README.md`の以下の箇所:
```markdown
- **テクスチャ再リンク** — 欠落しているテクスチャ画像を指定フォルダから検索して自動的に再リンク
- **不要データ一括削除** — 空の頂点グループ・無効なシェイプキー・未使用UVマップ/頂点カラー/マテリアルスロット・浮遊頂点/エッジを削除
```

これを以下に置き換える(間に1行追加):
```markdown
- **テクスチャ再リンク** — 欠落しているテクスチャ画像を指定フォルダから検索して自動的に再リンク
- **アーマチュア位置合わせ** — 指定したボーン(既定はHips)のレストポーズ位置が一致するように、別のArmatureを平行移動
- **不要データ一括削除** — 空の頂点グループ・無効なシェイプキー・未使用UVマップ/頂点カラー/マテリアルスロット・浮遊頂点/エッジを削除
```

- [ ] **Step 3: `README.md` に「7. アーマチュア位置合わせ」節を追加する**

`README.md`の以下の箇所(「6. テクスチャ再リンク」節の末尾、「## 全般的な注意事項」の直前):
```markdown
**重要な注意点:**
- あくまでフォルダ内に実在するファイルとの再リンクのみを行います。テクスチャファイル自体が手元に存在しない場合はこの機能では解決できません。
- FBXインポート時にテクスチャノード自体が作成されなかった場合(画像データブロックがそもそも存在しない場合)は対象外です。

## 全般的な注意事項
```

これを以下に置き換える(間に新規節を追加):
```markdown
**重要な注意点:**
- あくまでフォルダ内に実在するファイルとの再リンクのみを行います。テクスチャファイル自体が手元に存在しない場合はこの機能では解決できません。
- FBXインポート時にテクスチャノード自体が作成されなかった場合(画像データブロックがそもそも存在しない場合)は対象外です。

### 7. アーマチュア位置合わせ

同一アバターの別バージョン(例: 素足版とハイヒール版)のArmatureを重ねて比較したいとき、オブジェクトの`location`が両方`(0, 0, 0)`でも、実際のボーン配置(レストポーズ)がズレていることがあります。この機能は、指定したボーン(既定はHips)のレストポーズ・ワールド座標が一致するように、対象Armatureオブジェクト全体を平行移動します。

1. 「基準Armature」に、動かさずに基準としたいArmatureを指定します。ボーンは自動的に"Hips"相当のものが選択されますが、UIから選び直せます。
2. 「対象Armature」に、位置を合わせて動かしたいArmatureを指定します。
3. 「位置を合わせる」を実行すると、対象Armatureが平行移動し、指定ボーンの位置が基準側と一致します。

**重要な注意点:**
- 位置(平行移動)のみを一致させます。回転・スケールは変更しません。
- レストポーズ(Edit Modeでのボーン配置)を基準にします。現在のポーズ(Pose Mode)は見ません。
- 対象Armatureに親付けされたメッシュは一緒に移動しますが、Armatureモディファイアだけで紐づいていて親付けされていないメッシュは移動しません(その場合はレポートに警告が表示されます)。

## 全般的な注意事項
```

- [ ] **Step 4: `CHANGELOG.md` に新しいバージョンの項目を追加する**

`CHANGELOG.md`の先頭:
```markdown
# Changelog

## 1.2.0
```

これを以下に置き換える:
```markdown
# Changelog

## 1.3.0

- アーマチュア位置合わせ: 指定したボーン(既定はHips)のレストポーズ・ワールド座標が一致するように、対象Armatureオブジェクトを平行移動する機能を追加
  - オブジェクトの`location`が両方`(0,0,0)`でも、ボーンのレストポーズ配置の差(例: 素足版とハイヒール版のような差分)を正しく検出して解消する
  - 回転・スケールは変更せず、位置のみを一致させる
  - Armatureモディファイアで紐づくが対象Armatureの子孫でないメッシュがある場合は、移動せず警告としてレポートする

## 1.2.0
```

- [ ] **Step 5: 変更内容を確認する**

Run: `grep -n "1, 3, 0\|アーマチュア位置合わせ" NuniAvatarToolkit/__init__.py README.md CHANGELOG.md`
Expected: `NuniAvatarToolkit/__init__.py`に`(1, 3, 0)`、`README.md`に3箇所(冒頭一覧・節見出し・注意点内で言及)、`CHANGELOG.md`に`## 1.3.0`と本文、がそれぞれヒットすること。

- [ ] **Step 6: Commit**

```bash
git add NuniAvatarToolkit/__init__.py README.md CHANGELOG.md
git commit -m "Bump version to 1.3.0 and document armature-align feature"
```

---

## 実装後の確認(管理人依頼)

全タスク完了後、以下は管理人自身での確認をお願いします(GUI操作を伴うため技師・エージェントでは代替できません):

- Blenderを通常通りGUI起動し、サイドバー「Avatar Toolkit」タブに「アーマチュア位置合わせ」パネルが表示されること。
- 実際に、同一アバターの素足版/ハイヒール版のような、レストポーズのHips位置だけが異なる2つのArmatureを用意し、「基準Armature」「対象Armature」を指定して「位置を合わせる」を実行し、Hipsが重なることを目視確認する。
- 対象Armatureに親付けされたメッシュ(体・服等)が一緒に移動することを確認する。
- Ctrl+Zで元の位置に戻ることを確認する。
