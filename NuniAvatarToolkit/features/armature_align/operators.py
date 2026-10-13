import bpy

from ...core.context_utils import object_usability_error
from ...core.report import set_report_lines
from . import utils


class OBJECT_OT_amt_align_armature(bpy.types.Operator):
    bl_idname = "object.amt_align_armature"
    bl_label = "位置を合わせる"
    bl_description = "対象Armatureを平行移動し、指定ボーンのレストポーズ・ワールド座標を基準Armature側と一致させます"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_armature_align
        return props.reference_object is not None and props.target_object is not None

    def execute(self, context):
        props = context.scene.amt_armature_align
        reference_object = props.reference_object
        target_object = props.target_object

        if reference_object == target_object:
            self.report({'ERROR'}, "基準Armatureと対象Armatureに同じオブジェクトが指定されています")
            return {'CANCELLED'}

        if not props.reference_bone or not props.target_bone:
            self.report({'ERROR'}, "ボーンを指定してください")
            return {'CANCELLED'}

        for obj, label in ((reference_object, "基準Armature"), (target_object, "対象Armature")):
            error = object_usability_error(context, obj, label)
            if error:
                self.report({'ERROR'}, error)
                return {'CANCELLED'}

        if (target_object.library is not None or target_object.override_library is not None
                or not target_object.is_editable):
            self.report({'ERROR'}, "対象Armatureはリンクされているため移動できません")
            return {'CANCELLED'}

        try:
            context.view_layer.update()
            delta = utils.compute_alignment_delta(
                reference_object, props.reference_bone, target_object, props.target_bone,
            )
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        if delta.length < 1e-6:
            set_report_lines(props.report_lines, [('INFO', "既に一致しています")])
            self.report({'INFO'}, "既に一致しています")
            return {'FINISHED'}

        # Preserve raw channels: restoring matrix_basis can decompose rotation/scale differently.
        previous_channels = utils.capture_transform_channels(target_object)
        previous_linear = target_object.matrix_world.to_3x3().copy()
        try:
            utils.apply_alignment(target_object, delta)
            context.view_layer.update()
            remaining = utils.compute_alignment_delta(
                reference_object, props.reference_bone, target_object, props.target_bone,
            )
            if (remaining.length > 1e-4
                    or not utils.preserves_rotation_scale(target_object, previous_channels, previous_linear)):
                raise ValueError("位置・回転・スケールを保持した平行移動ができません")
        except (ValueError, RuntimeError) as exc:
            utils.restore_transform_channels(target_object, previous_channels)
            context.view_layer.update()
            message = (
                "安全に位置を合わせられなかったため元に戻しました"
                f"({exc}。コンストレイント・ドライバー・親の変換を確認してください)"
            )
            set_report_lines(props.report_lines, [('ERROR', message)])
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        lines = [
            ('INFO', f"基準「{reference_object.name} / {props.reference_bone}」、"
                     f"対象「{target_object.name} / {props.target_bone}」"),
            ('INFO', f"移動量 X={delta.x:.4f}, Y={delta.y:.4f}, Z={delta.z:.4f}"),
        ]
        orphans = utils.find_orphan_armature_meshes(target_object, context.scene.objects)
        if orphans:
            lines.append((
                'WARNING',
                "次のメッシュは対象Armatureの子ではないため移動していません: " + ", ".join(orphans),
            ))

        set_report_lines(props.report_lines, lines)
        self.report({'INFO'}, f"移動しました(X={delta.x:.4f}, Y={delta.y:.4f}, Z={delta.z:.4f})")
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_align_armature,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
