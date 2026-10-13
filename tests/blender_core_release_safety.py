"""Real Blender regressions for evaluated geometry and destructive-operation guards.

Run: blender --background --factory-startup --python-exit-code 1 --python tests/blender_core_release_safety.py
"""

import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from NuniAvatarToolkit.core.context_utils import object_usability_error
from NuniAvatarToolkit.core.mesh_eval import build_bvh_from_objects, snapshot_deform_only


def reset():
  for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
  for collection in list(bpy.data.collections):
    bpy.data.collections.remove(collection)


def cube(name, collection=None):
  mesh = bpy.data.meshes.new(name + 'Mesh')
  bm = bmesh.new()
  bmesh.ops.create_cube(bm, size=2)
  bm.to_mesh(mesh)
  bm.free()
  obj = bpy.data.objects.new(name, mesh)
  (collection or bpy.context.scene.collection).objects.link(obj)
  return obj


def expect_rejected(message, callback):
  try:
    callback()
  except ValueError as exc:
    assert message in str(exc), str(exc)
  else:
    raise AssertionError('unsafe geometry was accepted')


def test_world_reflections_keep_exterior_normals():
  for scale, inherited in [((1, 1, 1), False), ((-1, 1, 1), False), ((-1, 2, .5), True)]:
    reset()
    obj = cube('Body')
    if inherited:
      parent = bpy.data.objects.new('ReflectedParent', None)
      bpy.context.scene.collection.objects.link(parent)
      parent.scale = scale
      obj.parent = parent
    else:
      obj.scale = scale
    bpy.context.view_layer.update()
    bvh, _, _ = build_bvh_from_objects(bpy.context.evaluated_depsgraph_get(), [obj])
    for local_x, expected_sign in [(.9, -1), (1.1, 1)]:
      point = obj.matrix_world @ Vector((local_x, 0, 0))
      surface, normal, _, _ = bvh.find_nearest(point)
      signed_distance = (point - surface).dot(normal)
      assert signed_distance * expected_sign > .09, (scale, inherited, signed_distance)


def test_mixed_objects_preserve_each_objects_winding():
  reset()
  normal = cube('Normal')
  reflected = cube('Reflected')
  reflected.location.x = 5
  reflected.scale.x = -1
  bpy.context.view_layer.update()
  bvh, _, _ = build_bvh_from_objects(bpy.context.evaluated_depsgraph_get(), [normal, reflected])
  for x in (1.1, 6.1):
    point = Vector((x, 0, 0))
    surface, direction, _, _ = bvh.find_nearest(point)
    assert (point - surface).dot(direction) > .09
    assert direction.x > .99


def test_unevaluated_objects_are_not_used_as_base_geometry():
  for exclusion in (False, True):
    reset()
    collection = bpy.data.collections.new('ClothingCollection')
    bpy.context.scene.collection.children.link(collection)
    clothing = cube('Clothing', collection)
    if exclusion:
      bpy.context.view_layer.layer_collection.children[collection.name].exclude = True
    else:
      clothing.hide_viewport = True
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    expect_rejected('評価されていません', lambda: build_bvh_from_objects(depsgraph, [clothing]))
    expect_rejected('評価されていません', lambda: snapshot_deform_only(depsgraph, clothing))


def test_fake_user_is_not_treated_as_another_object():
  reset()
  body = cube('Body')
  body.data.use_fake_user = True
  bpy.context.view_layer.update()
  assert body.data.users == 2
  assert object_usability_error(bpy.context, body, '対象', require_single_user=True) is None
  peer = bpy.data.objects.new('OtherBody', body.data)
  bpy.context.scene.collection.objects.link(peer)
  bpy.context.view_layer.update()
  assert '共有' in object_usability_error(bpy.context, body, '対象', require_single_user=True)


def test_monitor_disabled_cached_references_are_rejected():
  bpy.types.Scene.amt_test_reference = bpy.props.PointerProperty(type=bpy.types.Object)
  try:
    for exclusion in ('object-monitor', 'collection-monitor', 'exclude'):
      reset()
      collection = bpy.data.collections.new('ReferencedCollection')
      bpy.context.scene.collection.children.link(collection)
      obj = cube('ReferencedBody', collection)
      bpy.context.scene.amt_test_reference = obj
      bpy.context.view_layer.update()
      build_bvh_from_objects(bpy.context.evaluated_depsgraph_get(), [obj])
      if exclusion == 'object-monitor':
        obj.hide_viewport = True
      elif exclusion == 'collection-monitor':
        collection.hide_viewport = True
      else:
        bpy.context.view_layer.layer_collection.children[collection.name].exclude = True
      expect_rejected('評価されていません', lambda: build_bvh_from_objects(bpy.context.evaluated_depsgraph_get(), [obj]))
  finally:
    bpy.context.scene.amt_test_reference = None
    del bpy.types.Scene.amt_test_reference


def test_enabled_collection_membership_wins_over_disabled_branch():
  reset()
  disabled = bpy.data.collections.new('Disabled')
  enabled = bpy.data.collections.new('Enabled')
  bpy.context.scene.collection.children.link(disabled)
  bpy.context.scene.collection.children.link(enabled)
  obj = cube('SharedCollectionObject', disabled)
  enabled.objects.link(obj)
  disabled.hide_viewport = True
  bpy.context.view_layer.update()
  bvh, _, _ = build_bvh_from_objects(bpy.context.evaluated_depsgraph_get(), [obj])
  assert bvh is not None


def test_degenerate_and_nonfinite_geometry_is_rejected():
  reset()
  obj = cube('Degenerate')
  obj.scale.x = 0
  bpy.context.view_layer.update()
  expect_rejected('スケールが0', lambda: build_bvh_from_objects(bpy.context.evaluated_depsgraph_get(), [obj]))
  expect_rejected('スケールが0', lambda: snapshot_deform_only(bpy.context.evaluated_depsgraph_get(), obj))
  obj.scale.x = 1
  obj.data.vertices[0].co.x = math.nan
  obj.data.update()
  bpy.context.view_layer.update()
  expect_rejected('NaN/Inf', lambda: build_bvh_from_objects(bpy.context.evaluated_depsgraph_get(), [obj]))
  expect_rejected('NaN/Inf', lambda: snapshot_deform_only(bpy.context.evaluated_depsgraph_get(), obj))


for test in (
  test_world_reflections_keep_exterior_normals,
  test_mixed_objects_preserve_each_objects_winding,
  test_unevaluated_objects_are_not_used_as_base_geometry,
  test_fake_user_is_not_treated_as_another_object,
  test_monitor_disabled_cached_references_are_rejected,
  test_enabled_collection_membership_wins_over_disabled_branch,
  test_degenerate_and_nonfinite_geometry_is_rejected,
):
  test()
  print('PASS ' + test.__name__)
print('BLENDER_CORE_RELEASE_SAFETY_OK')
