import bpy

from ...core.report import AMT_ReportLine


class AMT_TextureRelinkProperties(bpy.types.PropertyGroup):
    search_directory: bpy.props.StringProperty(
        name="検索フォルダ",
        description="欠落しているテクスチャ画像を探すフォルダを指定してください(サブフォルダも再帰的に検索します)",
        subtype='DIR_PATH',
    )
    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_TextureRelinkProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_texture_relink = bpy.props.PointerProperty(type=AMT_TextureRelinkProperties)


def unregister():
    del bpy.types.Scene.amt_texture_relink
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
