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
