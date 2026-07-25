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
