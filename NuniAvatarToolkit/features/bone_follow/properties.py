import bpy

from ...core.report import AMT_ReportLine


def _armature_object_poll(self, obj):
  return obj.type == 'ARMATURE'


def _mesh_object_poll(self, obj):
  return obj.type == 'MESH'


def _on_armature_object_update(self, context):
  armature = self.armature_object
  if armature is None:
    self.bone_name = ""
    return

  if self.bone_name and self.bone_name in armature.data.bones:
    return

  active_bone = armature.data.bones.active
  self.bone_name = active_bone.name if active_bone is not None else ""


class AMT_BoneFollowProperties(bpy.types.PropertyGroup):
  target_object: bpy.props.PointerProperty(
    type=bpy.types.Object,
    name="対象メッシュ",
    description="指定したボーンへ全頂点をウェイト1.0で割り当てるメッシュを指定してください",
    poll=_mesh_object_poll,
  )
  armature_object: bpy.props.PointerProperty(
    type=bpy.types.Object,
    name="Armature",
    description="追従先のボーンを持つArmatureを指定してください",
    poll=_armature_object_poll,
    update=_on_armature_object_update,
  )
  bone_name: bpy.props.StringProperty(name="ボーン")
  report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
  report_active_index: bpy.props.IntProperty()


_classes = (AMT_BoneFollowProperties,)


def register():
  for cls in _classes:
    bpy.utils.register_class(cls)
  bpy.types.Scene.amt_bone_follow = bpy.props.PointerProperty(type=AMT_BoneFollowProperties)


def unregister():
  del bpy.types.Scene.amt_bone_follow
  for cls in reversed(_classes):
    bpy.utils.unregister_class(cls)
