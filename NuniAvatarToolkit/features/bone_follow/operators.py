import bpy

from ...core.context_utils import reset_to_object_mode_with_active
from ...core.report import set_report_lines
from . import utils


class OBJECT_OT_amt_assign_rigid_bone_weight(bpy.types.Operator):
    bl_idname = "object.amt_assign_rigid_bone_weight"
    bl_label = "統合用ウェイトを設定"
    bl_description = "全頂点を指定ボーンへウェイト1.0で割り当て、メッシュ統合後も追従できるようにします"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_bone_follow
        return props.target_object is not None and props.armature_object is not None

    def execute(self, context):
        props = context.scene.amt_bone_follow
        target_object = props.target_object
        armature_object = props.armature_object

        # VertexGroup.add() fails in Edit Mode, so leave it before touching any data.
        if target_object.mode != 'OBJECT' or context.mode != 'OBJECT':
            reset_to_object_mode_with_active(context, target_object)

        try:
            result = utils.assign_rigid_bone_weight(
                target_object,
                armature_object,
                props.bone_name,
            )
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        modifier_message = "Armatureモディファイアを追加しました" if result['modifier_created'] else "既存のArmatureモディファイアを使用しました"
        set_report_lines(props.report_lines, [
            ('INFO', f"「{target_object.name}」の全{result['vertex_count']}頂点を「{props.bone_name}」へウェイト1.0で設定しました"),
            ('INFO', f"{modifier_message}: {armature_object.name}"),
            ('INFO', "結合先にも同じArmatureモディファイアを設定してからメッシュを結合してください"),
        ])
        self.report({'INFO'}, f"「{target_object.name}」へ統合用ボーンウェイトを設定しました")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_assign_rigid_bone_weight,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
