import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_hidden_mesh(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TOOLKIT_CATEGORY
    bl_label = "隠れメッシュ削除"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        props = context.scene.amt_hidden_mesh

        col = layout.column(align=True)
        col.prop(props, "body_object")
        col.prop(props, "clothing_collection")

        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "ray_samples")
        col.prop(props, "ray_epsilon_ratio")
        col.prop(props, "face_select_mode")

        layout.separator()
        box = layout.box()
        box.prop(props, "include_body_self_occlusion")
        if props.include_body_self_occlusion:
            box.prop(props, "self_occlusion_min_distance_ratio")

        layout.separator()
        col = layout.column(align=True)
        if props.body_object is not None:
            col.prop_search(props, "exclude_vertex_group", props.body_object, "vertex_groups")
        else:
            col.label(text="先にボディメッシュを指定してください", icon='INFO')

        layout.separator()
        col = layout.column(align=True)
        col.operator("object.amt_select_hidden_faces", icon='HIDE_OFF')
        col.operator("object.amt_delete_hidden_faces", icon='TRASH')


_classes = (VIEW3D_PT_amt_hidden_mesh,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
