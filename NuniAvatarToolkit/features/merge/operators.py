import bpy

from ...core.context_utils import capture_selection_state, reset_to_object_mode_with_active, restore_selection_state
from . import utils


class OBJECT_OT_amt_merge_join(bpy.types.Operator):
    bl_idname = "object.amt_merge_join"
    bl_label = "選択メッシュを結合"
    bl_description = (
        "選択中のメッシュオブジェクトをアクティブオブジェクトに結合します"
        "(Blender標準のオブジェクト結合機能に、事前の注意点チェックを追加したものです)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    _issues = ()

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if context.mode != 'OBJECT' or obj is None or obj.type != 'MESH':
            return False
        return len([o for o in context.selected_objects if o.type == 'MESH']) >= 2

    def invoke(self, context, event):
        self._issues = utils.analyze_join_candidates(context.selected_objects, context.active_object)
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        col = self.layout.column(align=True)
        has_warning = any(level in ('WARNING', 'ERROR') for level, _ in self._issues)
        if has_warning:
            col.label(text="以下の点に注意してください:", icon='ERROR')
        for level, text in self._issues:
            col.label(text=text, icon='ERROR' if level == 'ERROR' else 'NONE')
        col.separator()
        col.label(text="作業前にファイルを保存することを推奨します。")

    def execute(self, context):
        active_object = context.active_object
        mesh_objects = [o for o in context.selected_objects if o.type == 'MESH']
        editable = set(context.selected_editable_objects)
        for obj in mesh_objects:
            if obj not in editable or obj.library is not None or obj.data.library is not None:
                self.report({'ERROR'}, f"「{obj.name}」はリンクされているなどの理由で編集できないため結合できません")
                return {'CANCELLED'}

        active_name = active_object.name
        count = len(mesh_objects) - 1
        try:
            result = bpy.ops.object.join()
        except RuntimeError as exc:
            self.report({'ERROR'}, f"結合できませんでした: {exc}")
            return {'CANCELLED'}
        if 'FINISHED' not in result:
            self.report({'ERROR'}, "結合できませんでした")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{count} 個のメッシュを '{active_name}' に結合しました")
        return {'FINISHED'}


def _duplicate_slot_remap(obj):
    """{duplicate_slot_index: first_slot_index} for slots that repeat an earlier slot's material."""
    first_slot_for_material = {}
    remap = {}
    for i, slot in enumerate(obj.material_slots):
        mat = slot.material
        if mat is None:
            continue
        if mat not in first_slot_for_material:
            first_slot_for_material[mat] = i
        else:
            remap[i] = first_slot_for_material[mat]
    return remap


class OBJECT_OT_amt_merge_material_slots(bpy.types.Operator):
    bl_idname = "object.amt_merge_material_slots"
    bl_label = "重複マテリアルスロットを統合"
    bl_description = "同一のマテリアルを参照している重複したマテリアルスロットを1つに統合し、重複していたスロットだけを削除します"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def _check(self, context):
        """Return (obj, remap) or None after reporting why nothing can be done. Changes nothing."""
        obj = context.active_object
        if obj.library is not None or obj.data.library is not None:
            self.report({'ERROR'}, f"「{obj.name}」はリンクされているため変更できません")
            return None
        if obj.data.users > 1:
            self.report({'ERROR'}, f"「{obj.name}」のメッシュは他のオブジェクトと共有されているため変更できません(先にシングルユーザー化してください)")
            return None
        remap = _duplicate_slot_remap(obj)
        if not remap:
            self.report({'INFO'}, "統合できる重複マテリアルスロットはありませんでした")
            return None
        return obj, remap

    def invoke(self, context, event):
        if self._check(context) is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        obj = context.active_object
        remap = _duplicate_slot_remap(obj)
        col = self.layout.column(align=True)
        col.label(text="次の重複スロットを統合して削除します。", icon='ERROR')
        for index, target in sorted(remap.items()):
            col.label(text=f"スロット{index + 1} → スロット{target + 1}({obj.material_slots[index].material.name})")

    def execute(self, context):
        checked = self._check(context)
        if checked is None:
            return {'CANCELLED'}
        obj, remap = checked

        previous_state = capture_selection_state(context)
        try:
            reset_to_object_mode_with_active(context, obj)
            for poly in obj.data.polygons:
                if poly.material_index in remap:
                    poly.material_index = remap[poly.material_index]
            # Remove only the slots made redundant above, highest index first so the rest keep their index.
            # material_slot_remove shifts the face indices above the removed slot.
            for index in sorted(remap, reverse=True):
                obj.active_material_index = index
                bpy.ops.object.material_slot_remove()
        finally:
            restore_selection_state(context, previous_state)

        self.report({'INFO'}, f"{len(remap)} 個の重複マテリアルスロットを統合しました")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_merge_join, OBJECT_OT_amt_merge_material_slots)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
