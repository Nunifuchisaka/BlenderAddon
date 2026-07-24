"""Shared bpy.ops/context helpers reused across features. No bpy.types classes here."""

import bpy


def reset_to_object_mode_with_active(context, obj):
    """Force Object Mode (regardless of what was being edited) and make obj the sole active/selected object."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in context.selected_objects:
        o.select_set(False)
    context.view_layer.objects.active = obj
    obj.select_set(True)
