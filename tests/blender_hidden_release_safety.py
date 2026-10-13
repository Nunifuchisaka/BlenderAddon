"""Real Blender regressions for hidden-mesh release safety.

Run: blender --background --factory-startup --python tests/blender_hidden_release_safety.py
"""

import sys
import tempfile
from pathlib import Path

import bmesh
import bpy


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import NuniAvatarToolkit
from NuniAvatarToolkit.features.hidden_mesh import api, operators


def reset_scene():
  if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
  for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
  for collection in list(bpy.data.collections):
    bpy.data.collections.remove(collection)


def make_cube(name, size):
  mesh = bpy.data.meshes.new(f"{name}Mesh")
  bm = bmesh.new()
  bmesh.ops.create_cube(bm, size=size)
  bm.to_mesh(mesh)
  bm.free()
  mesh.update()
  obj = bpy.data.objects.new(name, mesh)
  bpy.context.scene.collection.objects.link(obj)
  return obj


def make_active(obj):
  for selected in bpy.context.selected_objects:
    selected.select_set(False)
  bpy.context.view_layer.objects.active = obj
  obj.select_set(True)


def selection_state():
  return (
    bpy.context.active_object,
    frozenset(bpy.context.selected_objects),
    bpy.context.mode,
  )


def mesh_state(mesh):
  return (
    tuple(tuple(vertex.co) for vertex in mesh.vertices),
    tuple(tuple(polygon.vertices) for polygon in mesh.polygons),
    tuple(polygon.select for polygon in mesh.polygons),
  )


def assert_rejected(call, expected_message):
  try:
    call()
  except api.HiddenMeshError as exc:
    assert expected_message in str(exc), str(exc)
    return
  raise AssertionError("unsafe hidden-mesh action was accepted")


def assert_operator_rejected(call, expected_message):
  # Blender raises for an operator's ERROR report, even if it returns CANCELLED.
  try:
    result = call()
  except RuntimeError as exc:
    assert expected_message in str(exc) and 'Traceback' not in str(exc), str(exc)
    return
  assert result == {'CANCELLED'}, result


def add_translation_nodes(obj, distance):
  tree = bpy.data.node_groups.new('SafetyTranslate', 'GeometryNodeTree')
  tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
  tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
  input_node = tree.nodes.new('NodeGroupInput')
  output_node = tree.nodes.new('NodeGroupOutput')
  transform = tree.nodes.new('GeometryNodeTransform')
  transform.inputs['Translation'].default_value.x = distance
  tree.links.new(input_node.outputs['Geometry'], transform.inputs['Geometry'])
  tree.links.new(transform.outputs['Geometry'], output_node.inputs['Geometry'])
  obj.modifiers.new('SafetyTranslate', 'NODES').node_group = tree


def test_shared_body_actions_leave_every_user_untouched():
  reset_scene()
  body = make_cube('Body', 1)
  clothing = make_cube('Clothing', 2)
  peer = bpy.data.objects.new('OtherAvatar', body.data)
  bpy.context.scene.collection.objects.link(peer)
  peer.location.x = 10
  make_active(clothing)
  before_selection = selection_state()
  before_mesh = mesh_state(body.data)
  analysis = NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action='ANALYZE', ray_samples=8)
  assert analysis['hidden_face_count'] == 6, analysis
  assert selection_state() == before_selection
  for action in ('SELECT', 'DELETE'):
    assert_rejected(
      lambda: NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action=action, ray_samples=8),
      '共有',
    )
    assert selection_state() == before_selection
    assert mesh_state(peer.data) == before_mesh
  assert bpy.data.collections.get('AMT_Backups') is None

  # The sidebar's deletion path must refuse the same mesh before making a backup.
  make_active(body)
  bpy.ops.object.mode_set(mode='EDIT')
  bpy.ops.mesh.select_all(action='SELECT')
  before_selection = selection_state()
  assert_operator_rejected(lambda: bpy.ops.object.amt_delete_hidden_faces('EXEC_DEFAULT'), '共有')
  assert selection_state() == before_selection
  assert bpy.data.collections.get('AMT_Backups') is None
  bpy.ops.object.mode_set(mode='OBJECT')
  assert len(body.data.polygons) == len(peer.data.polygons) == 6


def test_any_mode_preserves_protected_vertices_and_faces():
  reset_scene()
  body = make_cube('Body', 1)
  clothing = make_cube('Clothing', 2)
  protected_coordinate = tuple(body.data.vertices[0].co)
  protected_faces = {polygon.index for polygon in body.data.polygons if 0 in polygon.vertices}
  group = body.vertex_groups.new(name='Protect')
  group.add([0], 1, 'REPLACE')
  before_mesh = mesh_state(body.data)
  for margin in ('NONE', 'MEDIUM'):
    analysis = NuniAvatarToolkit.run_hidden_mesh(
      body, [clothing], action='ANALYZE', ray_samples=8, safety_margin=margin,
      face_select_mode='ANY', exclude_vertex_group='Protect',
    )
    assert analysis['raw_hidden_face_count'] == 3, analysis
    assert not protected_faces.intersection(analysis['hidden_face_indices']), analysis
    assert mesh_state(body.data) == before_mesh

  selected = NuniAvatarToolkit.run_hidden_mesh(
    body, [clothing], action='SELECT', ray_samples=8, safety_margin='NONE',
    face_select_mode='ANY', exclude_vertex_group='Protect',
  )
  bm = bmesh.from_edit_mesh(body.data)
  bm.faces.ensure_lookup_table()
  assert not any(bm.faces[index].select for index in protected_faces)
  assert sum(face.select for face in bm.faces) == selected['hidden_face_count'] == 3
  bpy.ops.object.mode_set(mode='OBJECT')

  result = NuniAvatarToolkit.run_hidden_mesh(
    body, [clothing], action='DELETE', ray_samples=8, safety_margin='NONE',
    face_select_mode='ANY', exclude_vertex_group='Protect',
  )
  bpy.ops.object.mode_set(mode='OBJECT')
  assert result['deleted_face_count'] == 3, result
  assert len(body.data.polygons) == 3
  protected_vertices = [
    vertex for vertex in body.data.vertices
    if any(assignment.group == group.index and assignment.weight > 0 for assignment in vertex.groups)
  ]
  assert len(protected_vertices) == 1
  assert tuple(protected_vertices[0].co) == protected_coordinate
  backup = bpy.data.objects[result['backup_object']]
  assert len(backup.data.polygons) == 6 and backup.data != body.data


def test_disabled_inputs_are_rejected_and_context_is_restored():
  for disabled_input in ('CLOTHING_MONITOR', 'CLOTHING_EXCLUDE', 'BODY_MONITOR', 'BODY_EXCLUDE'):
    reset_scene()
    body = make_cube('Body', 1)
    clothing = make_cube('Clothing', 2)
    add_translation_nodes(clothing, 5)
    other = make_cube('Other', 1)
    other.location.x = 12
    baseline = NuniAvatarToolkit.run_hidden_mesh(
      body, [clothing], action='ANALYZE', ray_samples=8, safety_margin='NONE',
    )
    assert baseline['hidden_face_count'] == 0, baseline
    obj = clothing if disabled_input.startswith('CLOTHING') else body
    if disabled_input.endswith('MONITOR'):
      obj.hide_viewport = True
      expected = '評価' if obj == clothing else '非表示'
    else:
      collection = bpy.data.collections.new('ExcludedInput')
      bpy.context.scene.collection.children.link(collection)
      bpy.context.scene.collection.objects.unlink(obj)
      collection.objects.link(obj)
      bpy.context.view_layer.layer_collection.children[collection.name].exclude = True
      expected = 'ビューレイヤー'
    make_active(other)
    bpy.ops.object.mode_set(mode='EDIT')
    before_selection = selection_state()
    before_mesh = mesh_state(body.data)
    for action in ('ANALYZE', 'SELECT', 'DELETE'):
      expected_message = '評価' if disabled_input == 'BODY_MONITOR' and action == 'ANALYZE' else expected
      assert_rejected(
        lambda: NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action=action, ray_samples=8),
        expected_message,
      )
      assert selection_state() == before_selection, (disabled_input, action)
      assert mesh_state(body.data) == before_mesh
      assert bpy.data.collections.get('AMT_Backups') is None

    # Call the invoke method with a report collector; rejection must precede timers.
    props = bpy.context.scene.amt_hidden_mesh
    props.body_object = body
    props.clothing_objects.clear()
    props.clothing_objects.add().object = clothing
    reports = []
    class InvokeProbe:
      def report(self, levels, message):
        reports.append((levels, message))
    assert operators.OBJECT_OT_amt_select_hidden_faces.invoke(InvokeProbe(), bpy.context, None) == {'CANCELLED'}
    assert reports and expected in reports[0][1], reports
    assert selection_state() == before_selection
    assert mesh_state(body.data) == before_mesh


def test_linked_bodies_can_be_analyzed_but_cannot_be_edited():
  reset_scene()
  source = make_cube('LibraryBody', 1)
  with tempfile.TemporaryDirectory() as directory:
    library_path = str(Path(directory) / 'hidden_safety.blend')
    bpy.data.libraries.write(library_path, {source})
    bpy.data.objects.remove(source, do_unlink=True)
    with bpy.data.libraries.load(library_path, link=True) as (_available, requested):
      requested.objects = ['LibraryBody']
    linked_body = requested.objects[0]
    bpy.context.scene.collection.objects.link(linked_body)
    local_body = bpy.data.objects.new('LocalObjectLinkedMesh', linked_body.data)
    bpy.context.scene.collection.objects.link(local_body)
    clothing = make_cube('Clothing', 2)
    make_active(clothing)
    for body in (linked_body, local_body):
      before_selection = selection_state()
      before_mesh = mesh_state(body.data)
      result = NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action='ANALYZE', ray_samples=8)
      assert result['hidden_face_count'] == 6, result
      assert selection_state() == before_selection
      for action in ('SELECT', 'DELETE'):
        assert_rejected(
          lambda: NuniAvatarToolkit.run_hidden_mesh(body, [clothing], action=action, ray_samples=8),
          'リンク',
        )
        assert selection_state() == before_selection
        assert mesh_state(body.data) == before_mesh
      assert_rejected(lambda: api.delete_faces(bpy.context, body, [0]), 'リンク')
      assert selection_state() == before_selection
      assert mesh_state(body.data) == before_mesh
    assert bpy.data.collections.get('AMT_Backups') is None


NuniAvatarToolkit.register()
try:
  for test in (
    test_shared_body_actions_leave_every_user_untouched,
    test_any_mode_preserves_protected_vertices_and_faces,
    test_disabled_inputs_are_rejected_and_context_is_restored,
    test_linked_bodies_can_be_analyzed_but_cannot_be_edited,
  ):
    test()
    print(f"PASS {test.__name__}")
  print('BLENDER_HIDDEN_RELEASE_SAFETY_OK')
finally:
  if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
  NuniAvatarToolkit.unregister()
