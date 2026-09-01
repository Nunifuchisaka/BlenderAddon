import bpy

from ...core.ui import TOOLKIT_CATEGORY


class AMT_UL_poke_through_clothing_objects(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "object", text="", emboss=True, icon='MESH_DATA')


class VIEW3D_PT_amt_poke_through(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "貫通チェック"
    bl_order = 9
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_poke_through

        col = layout.column(align=True)
        col.prop(props, "body_object")

        col.label(text="服メッシュ")
        row = col.row()
        row.template_list(
            "AMT_UL_poke_through_clothing_objects",
            "",
            props,
            "clothing_objects",
            props,
            "clothing_objects_index",
            rows=3,
        )
        buttons = row.column(align=True)
        buttons.operator("object.amt_add_poke_through_clothing", text="", icon='ADD')
        buttons.operator("object.amt_remove_poke_through_clothing", text="", icon='REMOVE')

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "max_search_distance")
        col.prop(props, "protrusion_threshold")
        col.prop(props, "face_select_mode")

        layout.separator()
        col = layout.column(align=True)
        if props.body_object is not None:
            col.prop_search(props, "exclude_vertex_group", props.body_object, "vertex_groups")
        else:
            col.label(text="先にボディメッシュを指定してください", icon='INFO')

        box = layout.box()
        box.label(text="服から出ている体の面を現在のポーズで検出し、", icon='INFO')
        box.label(text="編集モードで選択します(削除はしません)")

        layout.operator("object.amt_check_poke_through", icon='MOD_TRIANGULATE')

        if len(props.report_lines) > 0:
            layout.separator()
            layout.template_list(
                "AMT_UL_report_lines", "",
                props, "report_lines",
                props, "report_active_index",
                rows=4,
            )


_classes = (AMT_UL_poke_through_clothing_objects, VIEW3D_PT_amt_poke_through)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
