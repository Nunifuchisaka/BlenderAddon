import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_diagnostics(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "統計/書き出し前チェック"
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_diagnostics

        layout.prop(props, "avatar_collection")
        layout.operator("object.amt_diagnostics_run", icon='VIEWZOOM')

        if len(props.report_lines) > 0:
            layout.separator()
            layout.template_list(
                "AMT_UL_report_lines", "",
                props, "report_lines",
                props, "report_active_index",
                rows=8,
            )


_classes = (VIEW3D_PT_amt_diagnostics,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
