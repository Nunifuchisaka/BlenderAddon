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


def capture_selection_state(context):
    """Remember the active object, selection and its mode so restore_selection_state() can put them back."""
    active = context.view_layer.objects.active
    return {
        'active': active,
        'selected': list(context.selected_objects),
        'mode': active.mode if active is not None else 'OBJECT',
    }


def restore_selection_state(context, state):
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in context.selected_objects:
        obj.select_set(False)
    for obj in state['selected']:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)
    active = state['active']
    if active is None or active.name not in context.view_layer.objects:
        context.view_layer.objects.active = None
        return
    context.view_layer.objects.active = active
    if state['mode'] != 'OBJECT':
        bpy.ops.object.mode_set(mode=state['mode'])


def object_usability_error(context, obj, label, require_editable=False, require_visible=False):
    """Return a Japanese error message when obj cannot be used in the current view layer, else None."""
    if not any(candidate == obj for candidate in context.view_layer.objects):
        return f"{label}「{obj.name}」が現在のビューレイヤーにありません(別シーンや除外されたコレクションにある可能性があります)"
    if require_editable and (obj.library is not None or (obj.data is not None and obj.data.library is not None)):
        return f"{label}「{obj.name}」はリンクされているため変更できません"
    if require_visible and not obj.visible_get():
        return f"{label}「{obj.name}」が非表示のため編集モードに入れません"
    return None


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
