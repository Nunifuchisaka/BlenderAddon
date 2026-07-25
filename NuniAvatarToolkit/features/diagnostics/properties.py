import bpy

from ...core.report import AMT_ReportLine


class AMT_DiagnosticsProperties(bpy.types.PropertyGroup):
    avatar_collection: bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="アバターコレクション",
        description="統計・チェック対象となるアバター一式(体・服・アーマチュア等)をまとめたコレクションを指定してください",
    )
    report_lines: bpy.props.CollectionProperty(type=AMT_ReportLine)
    report_active_index: bpy.props.IntProperty()


_classes = (AMT_DiagnosticsProperties,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.amt_diagnostics = bpy.props.PointerProperty(type=AMT_DiagnosticsProperties)


def unregister():
    del bpy.types.Scene.amt_diagnostics
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
