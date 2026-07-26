import os

import bpy

from ...core.report import set_report_lines
from . import utils


class OBJECT_OT_amt_relink_textures(bpy.types.Operator):
    bl_idname = "object.amt_relink_textures"
    bl_label = "欠落テクスチャを再リンク"
    bl_description = "検索フォルダの中から、欠落しているテクスチャ画像と同名/類似名のファイルを探して再リンクします"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.amt_texture_relink
        return bool(props.search_directory)

    def execute(self, context):
        props = context.scene.amt_texture_relink

        if not utils.collect_missing_images(bpy.data.images):
            set_report_lines(props.report_lines, [('INFO', "欠落しているテクスチャはありません")])
            self.report({'INFO'}, "欠落しているテクスチャはありません")
            return {'FINISHED'}

        try:
            directory = bpy.path.abspath(props.search_directory)
            result = utils.relink_missing_textures(bpy.data.images, directory)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        lines = []
        for image, new_path in result['relinked']:
            lines.append(('INFO', f"{image.name}: '{new_path}' に再リンクしました"))
        for image, matches in result['ambiguous']:
            candidates_text = ", ".join(os.path.basename(m) for m in matches)
            lines.append(('WARNING', f"{image.name}: 完全一致ではない、または候補が複数あるためスキップしました({candidates_text})"))
        for image in result['not_found']:
            lines.append(('WARNING', f"{image.name}: 一致するファイルが見つかりませんでした"))

        set_report_lines(props.report_lines, lines)
        self.report(
            {'INFO'},
            f"再リンク {len(result['relinked'])} 件、保留 {len(result['ambiguous'])} 件、"
            f"見つからず {len(result['not_found'])} 件",
        )
        return {'FINISHED'}


_classes = (OBJECT_OT_amt_relink_textures,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
