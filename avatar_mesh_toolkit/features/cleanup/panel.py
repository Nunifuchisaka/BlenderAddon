import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_cleanup(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "不要データ一括削除"
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_cleanup

        layout.prop(props, "target_object")

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "remove_empty_vertex_groups")
        col.prop(props, "remove_noop_shape_keys")
        if props.remove_noop_shape_keys:
            col.prop(props, "shape_key_noop_threshold")
        col.prop(props, "remove_unused_uv_maps")
        col.prop(props, "remove_unused_vertex_colors")
        col.prop(props, "remove_unused_material_slots")
        col.prop(props, "remove_loose_geometry")

        layout.separator()
        row = layout.row(align=True)
        row.operator("object.amt_cleanup_scan", icon='VIEWZOOM')
        row.operator("object.amt_cleanup_execute", icon='TRASH')

        if len(props.report_lines) > 0:
            layout.separator()
            layout.template_list(
                "AMT_UL_report_lines", "",
                props, "report_lines",
                props, "report_active_index",
                rows=4,
            )


_classes = (VIEW3D_PT_amt_cleanup,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
