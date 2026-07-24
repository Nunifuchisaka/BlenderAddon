import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_merge(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "メッシュ/マテリアル統合"
    bl_order = 2
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.label(text="結合先にしたいオブジェクトをアクティブにした状態で")
        col.label(text="結合したい全てのメッシュを選択してから実行してください。")
        col.operator("object.amt_merge_join", icon='MESH_DATA')

        layout.separator()
        col = layout.column(align=True)
        col.label(text="アクティブオブジェクトの重複マテリアルを統合します。")
        col.operator("object.amt_merge_material_slots", icon='MATERIAL')


_classes = (VIEW3D_PT_amt_merge,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
