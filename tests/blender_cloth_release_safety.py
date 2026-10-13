"""Real Blender regressions for cloth fit / poke-through release safety.

Run with Blender --background --factory-startup --python this_file.py.
"""

import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import patch

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import NuniAvatarToolkit
from NuniAvatarToolkit.core import mesh_eval
from NuniAvatarToolkit.features.cloth_fit import operators as cloth_operators
from NuniAvatarToolkit.features.cloth_fit import utils as cloth_utils
from NuniAvatarToolkit.features.poke_through import utils as poke_utils


def reset_scene():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    scene.amt_poke_through.clothing_objects.clear()
    scene.amt_cloth_fit.shape_key_name = 'AMT_Fit'
    scene.amt_cloth_fit.offset = .01
    scene.amt_cloth_fit.max_search_distance = 0.0
    scene.unit_settings.scale_length = 1.0


def make_mesh(name, vertices, faces=()):
    mesh = bpy.data.meshes.new(name + 'Mesh')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_cube(name, size=2.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    mesh = bpy.data.meshes.new(name + 'Mesh')
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_active(obj, edit=False):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in bpy.context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if edit:
        bpy.ops.object.mode_set(mode='EDIT')


def setup_fit(body=None, cloth=None):
    body = body if body is not None else make_cube('Body')
    cloth = cloth if cloth is not None else make_mesh(
        'Cloth', [(.9, -.1, -.1), (.9, .1, -.1), (.9, 0, .1)], [(0, 1, 2)],
    )
    group = cloth.vertex_groups.get('Fit') or cloth.vertex_groups.new(name='Fit')
    if cloth.data.library is None and len(cloth.data.vertices):
        group.add(list(range(len(cloth.data.vertices))), 1.0, 'REPLACE')
    props = bpy.context.scene.amt_cloth_fit
    props.body_object = body
    props.clothing_object = cloth
    props.vertex_group = 'Fit'
    props.shape_key_name = 'AMT_Fit'
    props.offset = .01
    props.max_search_distance = 0.0
    bpy.context.view_layer.update()
    return body, cloth


def coordinates(key):
    return np.array([tuple(point.co) for point in key.data])


def assert_cancelled(fragment, operator, *args):
    try:
        result = operator(*args)
    except RuntimeError as exc:
        message = str(exc)
        assert fragment in message and 'Traceback' not in message, message
        return
    raise AssertionError(f'Expected rejection containing {fragment!r}, got {result}')


def assert_edit_context(obj):
    assert bpy.context.mode == 'EDIT_MESH', bpy.context.mode
    assert bpy.context.view_layer.objects.active == obj
    assert list(bpy.context.selected_objects) == [obj]


def reflect_with_parent(obj):
    parent = bpy.data.objects.new('ReflectionParent', None)
    bpy.context.scene.collection.objects.link(parent)
    parent.scale.x = -1.0
    obj.parent = parent
    bpy.context.view_layer.update()


def test_reflected_bvh_helpers_keep_exterior_normals():
    reset_scene()
    surface = make_cube('Surface')
    positions = np.array([[.9, 0, 0], [1.1, 0, 0]], dtype=np.float64)
    for reflected in (False, True):
        if reflected:
            reflect_with_parent(surface)
        bpy.context.view_layer.update()
        bvh, _minimum, _maximum = mesh_eval.build_bvh_from_objects(
            bpy.context.evaluated_depsgraph_get(), [surface],
        )
        fitted, moved, _maximum_move = cloth_utils.compute_fitted_positions(
            positions, np.ones(2), bvh, .01, 0.0,
        )
        flags, _depths = poke_utils.compute_protruding_vertex_flags(
            positions, bvh, np.zeros(2, dtype=bool), .001, .5,
        )
        assert moved.tolist() == [True, False], (reflected, moved)
        assert flags.tolist() == [False, True], (reflected, flags)
        assert np.allclose(fitted[:, 0], [1.01, 1.1], atol=1e-6), fitted


def test_reflected_body_real_fit_matches_normal_geometry():
    outputs = []
    for reflected in (False, True):
        reset_scene()
        body, cloth = setup_fit()
        if reflected:
            reflect_with_parent(body)
        assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
        outputs.append(coordinates(cloth.data.shape_keys.key_blocks['AMT_Fit']))
    assert np.allclose(outputs[0][:, 0], 1.01, atol=1e-6), outputs[0]
    assert np.allclose(outputs[0], outputs[1], atol=1e-6), outputs


def test_reflected_clothing_real_poke_selects_same_face():
    for reflected in (False, True):
        reset_scene()
        body = make_mesh('Body', [
            (.9, -.1, -.1), (.9, .1, -.1), (.9, 0, .1),
            (1.1, -.1, -.1), (1.1, .1, -.1), (1.1, 0, .1),
        ], [(0, 1, 2), (3, 4, 5)])
        clothing = make_cube('Clothing')
        if reflected:
            reflect_with_parent(clothing)
        props = bpy.context.scene.amt_poke_through
        props.body_object = body
        props.clothing_objects.add().object = clothing
        props.max_search_distance = .5
        props.protrusion_threshold = .001
        props.face_select_mode = 'ANY'
        bpy.context.view_layer.update()
        assert bpy.ops.object.amt_check_poke_through() == {'FINISHED'}
        bm = bmesh.from_edit_mesh(body.data)
        bm.faces.ensure_lookup_table()
        assert {face.index for face in bm.faces if face.select} == {1}, reflected


def test_shared_poke_body_rejected_without_changing_peer_selection():
    reset_scene()
    body = make_cube('Body')
    peer = body.copy()
    bpy.context.scene.collection.objects.link(peer)
    body.data.polygons[0].select = True
    before = [face.select for face in body.data.polygons]
    clothing = make_cube('Clothing', 1.8)
    props = bpy.context.scene.amt_poke_through
    props.body_object = body
    props.clothing_objects.add().object = clothing
    props.max_search_distance = .5
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('共有', bpy.ops.object.amt_check_poke_through)
    assert peer.data == body.data
    assert [face.select for face in peer.data.polygons] == before
    assert_edit_context(other)


def test_shared_clothing_reference_can_be_used_for_poke():
    reset_scene()
    body = make_mesh('Body', [(1.1, -.1, -.1), (1.1, .1, -.1), (1.1, 0, .1)], [(0, 1, 2)])
    clothing = make_cube('Clothing')
    peer = clothing.copy()
    bpy.context.scene.collection.objects.link(peer)
    props = bpy.context.scene.amt_poke_through
    props.body_object = body
    props.clothing_objects.add().object = clothing
    props.max_search_distance = .5
    props.protrusion_threshold = .001
    props.face_select_mode = 'ANY'
    bpy.context.view_layer.update()
    assert bpy.ops.object.amt_check_poke_through() == {'FINISHED'}
    assert bpy.context.view_layer.objects.active == body and bpy.context.mode == 'EDIT_MESH'
    assert clothing.data == peer.data


def test_linked_mesh_on_local_object_is_rejected():
    reset_scene()
    _body, source = setup_fit()
    source_name = source.data.name
    library_path = str(Path(tempfile.mkdtemp()) / 'cloth_library.blend')
    bpy.data.libraries.write(library_path, {source}, fake_user=True)
    with bpy.data.libraries.load(library_path, link=True) as (_available, loaded):
        loaded.meshes = [source_name]
    linked_mesh = loaded.meshes[0]
    local_cloth = bpy.data.objects.new('LocalCloth', linked_mesh)
    bpy.context.scene.collection.objects.link(local_cloth)
    local_cloth.vertex_groups.new(name='Fit')
    bpy.context.scene.amt_cloth_fit.clothing_object = local_cloth
    other = make_cube('Other')
    make_active(other, edit=True)
    assert local_cloth.library is None and local_cloth.data.library is not None
    assert_cancelled('リンク', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert local_cloth.data.shape_keys is None
    assert_edit_context(other)


def test_shared_mesh_is_rejected_without_changing_any_instance():
    reset_scene()
    _body, cloth = setup_fit()
    other_instance = cloth.copy()
    bpy.context.scene.collection.objects.link(other_instance)
    assert cloth.data.users == 2
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('共有', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert cloth.data.shape_keys is None and other_instance.data.shape_keys is None
    assert_edit_context(other)


def test_single_mesh_with_fake_user_can_still_be_fitted():
    reset_scene()
    _body, cloth = setup_fit()
    cloth.data.use_fake_user = True
    assert cloth.data.users == 2
    assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
    assert np.allclose(coordinates(cloth.data.shape_keys.key_blocks['AMT_Fit'])[:, 0], 1.01, atol=1e-6)


def test_absolute_keys_rejected_without_animation_changes():
    reset_scene()
    _body, cloth = setup_fit()
    cloth.shape_key_add(name='Basis', from_mix=False)
    fit = cloth.shape_key_add(name='AMT_Fit', from_mix=False)
    fit.data[0].co.x = .95
    fit.value = .25
    cloth.data.shape_keys.use_relative = False
    cloth.data.shape_keys.eval_time = 3.0
    before = coordinates(fit)
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('絶対シェイプキー', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert not cloth.data.shape_keys.use_relative
    assert cloth.data.shape_keys.eval_time == 3.0
    assert np.array_equal(coordinates(fit), before) and fit.value == .25
    assert_edit_context(other)


def test_self_relative_fit_key_rejected_without_changing_relationship():
    reset_scene()
    _body, cloth = setup_fit()
    cloth.shape_key_add(name='Basis', from_mix=False)
    fit = cloth.shape_key_add(name='AMT_Fit', from_mix=False)
    fit.data[0].co.x = .95
    fit.relative_key = fit
    fit.value = .25
    before = coordinates(fit)
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('自身を相対キー', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert fit.relative_key == fit and fit.value == .25
    assert np.array_equal(coordinates(fit), before)
    assert_edit_context(other)


def test_existing_fit_key_range_cannot_clamp_required_value():
    reset_scene()
    _body, cloth = setup_fit()
    cloth.shape_key_add(name='Basis', from_mix=False)
    fit = cloth.shape_key_add(name='AMT_Fit', from_mix=False)
    fit.data[0].co.x = .95
    fit.slider_max = .5
    fit.value = .25
    before = coordinates(fit)
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('スライダー範囲', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert fit.slider_min == 0.0 and fit.slider_max == .5 and fit.value == .25
    assert np.array_equal(coordinates(fit), before)
    assert_edit_context(other)


def test_muted_fit_key_rejected_without_changing_settings():
    reset_scene()
    _body, cloth = setup_fit()
    cloth.shape_key_add(name='Basis', from_mix=False)
    fit = cloth.shape_key_add(name='AMT_Fit', from_mix=False)
    fit.data[0].co.x = .95
    fit.mute = True
    fit.value = .25
    before = coordinates(fit)
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('ミュート', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert fit.mute and fit.value == .25
    assert np.array_equal(coordinates(fit), before)
    assert_edit_context(other)


def test_edit_mode_deleted_vertex_uses_current_topology():
    reset_scene()
    cloth = make_cube('Cloth', 1.8)
    _body, cloth = setup_fit(cloth=cloth)
    make_active(cloth, edit=True)
    bm = bmesh.from_edit_mesh(cloth.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[-1]], context='VERTS')
    bmesh.update_edit_mesh(cloth.data, loop_triangles=False, destructive=True)
    assert len(cloth.data.vertices) == 8 and len(bm.verts) == 7
    assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
    assert len(cloth.data.vertices) == 7
    assert len(cloth.data.shape_keys.key_blocks['AMT_Fit'].data) == 7


def test_edit_mode_new_vertex_on_empty_mesh_is_fitted():
    reset_scene()
    cloth = make_mesh('Cloth', [])
    _body, cloth = setup_fit(cloth=cloth)
    make_active(cloth, edit=True)
    bm = bmesh.from_edit_mesh(cloth.data)
    layer = bm.verts.layers.deform.verify()
    vertex = bm.verts.new((.9, 0, 0))
    vertex[layer][cloth.vertex_groups['Fit'].index] = 1.0
    bmesh.update_edit_mesh(cloth.data, loop_triangles=False, destructive=True)
    assert len(cloth.data.vertices) == 0 and len(bm.verts) == 1
    assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}
    fit = cloth.data.shape_keys.key_blocks['AMT_Fit']
    assert len(fit.data) == 1 and abs(fit.data[0].co.x - 1.01) < 1e-6


def test_compute_failure_restores_context_pose_and_creates_no_keys():
    reset_scene()
    body, cloth = setup_fit()
    armature = bpy.data.armatures.new('RigData')
    rig = bpy.data.objects.new('Rig', armature)
    bpy.context.scene.collection.objects.link(rig)
    body.modifiers.new('Armature', 'ARMATURE').object = rig
    cloth.modifiers.new('Armature', 'ARMATURE').object = rig
    other = make_cube('Other')
    make_active(other, edit=True)
    with patch.object(cloth_utils, 'compute_fitted_positions', side_effect=RuntimeError('injected solver failure')):
        assert_cancelled('injected solver failure', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert cloth.data.shape_keys is None
    assert armature.pose_position == 'POSE'
    assert_edit_context(other)


def test_partial_key_creation_is_rolled_back():
    reset_scene()
    _body, cloth = setup_fit()
    other = make_cube('Other')
    make_active(other, edit=True)
    original = cloth_operators._get_or_create_shape_key

    def fail_after_creation(obj, name):
        original(obj, name)
        raise RuntimeError('injected key creation failure')

    with patch.object(cloth_operators, '_get_or_create_shape_key', side_effect=fail_after_creation):
        assert_cancelled('injected key creation failure', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert cloth.data.shape_keys is None
    assert_edit_context(other)


def test_failed_overwrite_restores_existing_key_and_settings():
    reset_scene()
    _body, cloth = setup_fit()
    cloth.shape_key_add(name='Basis', from_mix=False)
    fit = cloth.shape_key_add(name='AMT_Fit', from_mix=False)
    fit.data[0].co.x = .95
    fit.value = .25
    cloth.active_shape_key_index = 1
    cloth.show_only_shape_key = True
    before = coordinates(fit)
    other = make_cube('Other')
    make_active(other, edit=True)

    def fail_after_overwriting(obj, name):
        key = obj.data.shape_keys.key_blocks[name]
        key.data[0].co.x = 8.0
        key.value = .7
        obj.active_shape_key_index = 0
        obj.show_only_shape_key = False
        raise RuntimeError('injected overwrite failure')

    with patch.object(cloth_operators, '_get_or_create_shape_key', side_effect=fail_after_overwriting):
        assert_cancelled('injected overwrite failure', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert np.array_equal(coordinates(fit), before)
    assert fit.value == .25
    assert cloth.active_shape_key_index == 1 and cloth.show_only_shape_key
    assert_edit_context(other)


def test_unsupported_cloth_deformation_rejected_before_changes():
    reset_scene()
    _body, cloth = setup_fit()
    modifier = cloth.modifiers.new('UnsafeDisplace', 'DISPLACE')
    modifier.direction = 'X'
    modifier.strength = .2
    modifier.mid_level = 0.0
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('UnsafeDisplace', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert modifier.show_viewport and cloth.data.shape_keys is None
    assert_edit_context(other)
    modifier.show_viewport = False
    assert bpy.ops.object.amt_cloth_fit('EXEC_DEFAULT') == {'FINISHED'}


def test_excluded_cloth_rejected_before_context_changes():
    reset_scene()
    _body, cloth = setup_fit()
    collection = bpy.data.collections.new('ExcludedClothing')
    bpy.context.scene.collection.children.link(collection)
    for old_collection in list(cloth.users_collection):
        old_collection.objects.unlink(cloth)
    collection.objects.link(cloth)
    bpy.context.view_layer.layer_collection.children[collection.name].exclude = True
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('ビューレイヤー', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert cloth.data.shape_keys is None
    assert_edit_context(other)


def test_unevaluated_body_failure_preserves_context_and_keys():
    reset_scene()
    body, cloth = setup_fit()
    body.hide_viewport = True
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('評価', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert cloth.data.shape_keys is None
    assert_edit_context(other)


def test_zero_clothing_scale_rejected_without_fabricated_coordinates():
    reset_scene()
    _body, cloth = setup_fit()
    cloth.scale.x = 0.0
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('スケールが0', bpy.ops.object.amt_cloth_fit, 'EXEC_DEFAULT')
    assert cloth.data.shape_keys is None
    assert_edit_context(other)


def test_unevaluated_clothing_failure_restores_poke_context():
    reset_scene()
    body = make_cube('Body')
    clothing = make_cube('Clothing', 2.2)
    clothing.hide_viewport = True
    props = bpy.context.scene.amt_poke_through
    props.body_object = body
    props.clothing_objects.add().object = clothing
    other = make_cube('Other')
    make_active(other, edit=True)
    assert_cancelled('評価', bpy.ops.object.amt_check_poke_through)
    assert_edit_context(other)


TESTS = [value for name, value in list(globals().items()) if name.startswith('test_') and callable(value)]
NuniAvatarToolkit.register()
try:
    for test in TESTS:
        test()
        print(f'PASS {test.__name__}')
    print(f'BLENDER_CLOTH_RELEASE_SAFETY_OK ({len(TESTS)} tests)')
except Exception:
    traceback.print_exc()
    sys.exit(1)
finally:
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    NuniAvatarToolkit.unregister()
