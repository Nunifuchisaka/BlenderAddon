import bpy

from ...core.report import AMT_ReportLine
from . import utils


def _armature_object_poll(self, obj):
    return obj.type == 'ARMATURE'


def _on_reference_object_update(self, context):
    obj = self.reference_object
    if obj is None:
        return
    if self.reference_bone and self.reference_bone in obj.data.bones:
        return
    self.reference_bone = utils.find_hips_bone(obj.data)


def _on_target_object_update(self, context):
    obj = self.target_object
    if obj is None:
        return
    if self.target_bone and self.target_bone in obj.data.bones:
        return
    self.target_bone = utils.find_hips_bone(obj.data)


class AMT_ArmatureAlignProperties(bpy.types.PropertyGroup):
    reference_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="基準Armature",
        description="移動させずに基準とするArmatureを指定してください",
        poll=_armature_object_poll,
        update=_on_reference_object_update,
    )
    reference_bone: bpy.props.StringProperty(name="基準ボーン")

    target_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="対象Armature",
        description="位置を合わせて移動させるArmatureを指定してください",
        poll=_armature_object_poll,
        update=_on_target_object_update,
    )
    target_bone: bpy.props.StringProperty(name="対象ボーン")

    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_ArmatureAlignProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_armature_align = bpy.props.PointerProperty(type=AMT_ArmatureAlignProperties)


def unregister():
    del bpy.types.Scene.amt_armature_align
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
