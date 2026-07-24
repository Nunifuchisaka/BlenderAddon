import bpy

from ...core.context_utils import reset_to_object_mode_with_active
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
        active_name = context.active_object.name
        count = len([o for o in context.selected_objects if o.type == 'MESH']) - 1
        bpy.ops.object.join()
        self.report({'INFO'}, f"{count} 個のメッシュを '{active_name}' に結合しました")
        return {'FINISHED'}


class OBJECT_OT_amt_merge_material_slots(bpy.types.Operator):
    bl_idname = "object.amt_merge_material_slots"
    bl_label = "重複マテリアルスロットを統合"
    bl_description = "同一のマテリアルを参照している重複したマテリアルスロットを1つに統合し、不要になったスロットを削除します"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        reset_to_object_mode_with_active(context, obj)
        mesh = obj.data

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

        if not remap:
            self.report({'INFO'}, "統合できる重複マテリアルスロットはありませんでした")
            return {'CANCELLED'}

        for poly in mesh.polygons:
            if poly.material_index in remap:
                poly.material_index = remap[poly.material_index]

        bpy.ops.object.material_slot_remove_unused()
        self.report({'INFO'}, f"{len(remap)} 個の重複マテリアルスロットを統合しました")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_merge_join, OBJECT_OT_amt_merge_material_slots)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
