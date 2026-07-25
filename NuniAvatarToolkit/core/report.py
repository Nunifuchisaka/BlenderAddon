"""Shared scrollable report-list widget reused by the cleanup and diagnostics features.

Unlike mesh_eval.py/ui.py, this module DOES define bpy.types classes and therefore
DOES need register()/unregister() called (from the top-level __init__.py, before any
feature module that declares a CollectionProperty(type=AMT_ReportLine)).
"""

import bpy

_LEVEL_ICON = {'INFO': 'INFO', 'WARNING': 'ERROR', 'ERROR': 'CANCEL'}


class AMT_ReportLine(bpy.types.PropertyGroup):
    text: bpy.props.StringProperty()
    level: bpy.props.EnumProperty(
        items=[('INFO', "Info", ""), ('WARNING', "Warning", ""), ('ERROR', "Error", "")],
        default='INFO',
    )


class AMT_UL_report_lines(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.text, icon=_LEVEL_ICON.get(item.level, 'INFO'))


def set_report_lines(collection_prop, lines):
    """lines: iterable of (level, text) tuples. Replaces the collection's contents."""
    collection_prop.clear()
    for level, text in lines:
        item = collection_prop.add()
        item.level = level
        item.text = text


_classes = (AMT_ReportLine, AMT_UL_report_lines)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
