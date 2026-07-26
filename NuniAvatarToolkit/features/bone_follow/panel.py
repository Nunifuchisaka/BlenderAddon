import bpy

from ...core.ui import TOOLKIT_CATEGORY


class VIEW3D_PT_amt_bone_follow(bpy.types.Panel):
  bl_space_type = 'VIEW_3D'
  bl_region_type = 'UI'
  bl_category = TOOLKIT_CATEGORY
  bl_label = "統合用ボーンウェイト"
  bl_order = 7
  bl_options = {'DEFAULT_CLOSED'}

  def draw(self, context):
    layout = self.layout
    props = context.scene.amt_bone_follow

    layout.prop(props, "target_object")
    layout.prop(props, "armature_object")
    if props.armature_object is not None:
      layout.prop_search(props, "bone_name", props.armature_object.data, "bones")

    box = layout.box()
    box.label(text="全頂点を指定ボーンへウェイト1.0で設定します", icon='INFO')
    box.label(text="設定後、同じArmatureを使うメッシュへ結合してください")

    layout.operator("object.amt_assign_rigid_bone_weight", icon='GROUP_VERTEX')

    if len(props.report_lines) > 0:
      layout.separator()
      layout.template_list(
        "AMT_UL_report_lines", "",
        props, "report_lines",
        props, "report_active_index",
        rows=3,
      )


_classes = (VIEW3D_PT_amt_bone_follow,)


def register():
  for cls in _classes:
    bpy.utils.register_class(cls)


def unregister():
  for cls in reversed(_classes):
    bpy.utils.unregister_class(cls)
