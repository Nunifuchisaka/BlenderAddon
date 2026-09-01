"""Shared bpy.ops/context helpers reused across features. No bpy.types classes here."""

import bmesh
import bpy


def reset_to_object_mode_with_active(context, obj):
    """Force Object Mode (regardless of what was being edited) and make obj the sole active/selected object."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in context.selected_objects:
        o.select_set(False)
    context.view_layer.objects.active = obj
    obj.select_set(True)


def select_faces_in_edit_mode(context, obj, face_indices):
    """Replace the current edit-mode selection with the specified faces of obj."""
    face_indices = frozenset(int(index) for index in face_indices)
    reset_to_object_mode_with_active(context, obj)
    bpy.ops.object.mode_set(mode='EDIT')
    context.tool_settings.mesh_select_mode = (False, False, True)
    bpy.ops.mesh.select_all(action='DESELECT')

    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    for face_index in face_indices:
        if 0 <= face_index < len(bm.faces):
            bm.faces[face_index].select = True
    bmesh.update_edit_mesh(obj.data)
