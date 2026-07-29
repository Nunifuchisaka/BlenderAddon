import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_cloth_fit(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "服メッシュフィット"
    bl_order = 8
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_cloth_fit

        layout.prop(props, "body_object")
        layout.prop(props, "clothing_object")
        if props.clothing_object is not None:
            layout.prop_search(props, "vertex_group", props.clothing_object, "vertex_groups")
        else:
            layout.label(text="先に服メッシュを指定してください", icon='INFO')

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "offset")
        col.prop(props, "max_search_distance")
        col.prop(props, "shape_key_name")

        box = layout.box()
        box.label(text="頂点グループの範囲のうち、体に埋まっている", icon='INFO')
        box.label(text="頂点だけを体表面まで押し出します")
        box.label(text="結果はシェイプキーとして追加されます")

        layout.operator("object.amt_cloth_fit", icon='MOD_SHRINKWRAP')

        if len(props.report_lines) > 0:
            layout.separator()
            layout.template_list(
                "AMT_UL_report_lines", "",
                props, "report_lines",
                props, "report_active_index",
                rows=4,
            )


_classes = (VIEW3D_PT_amt_cloth_fit,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
