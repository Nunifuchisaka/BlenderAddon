"""Release ownership, rigid-follow and translation-only regression tests in Blender."""
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import NuniAvatarToolkit

NuniAvatarToolkit.register()


def reset_scene():
  if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
  bpy.ops.wm.read_factory_settings(use_empty=True)


def make_active(obj):
  bpy.ops.object.select_all(action='DESELECT')
  obj.select_set(True)
  bpy.context.view_layer.objects.active = obj


def armature(name, location=(0, 0, 0)):
  bpy.ops.object.armature_add(location=location)
  obj = bpy.context.object
  obj.name = name
  obj.data.bones[0].name = 'Follow'
  return obj


def cube(name, location=(0, 0, 0)):
  bpy.ops.mesh.primitive_cube_add(location=location)
  obj = bpy.context.object
  obj.name = name
  return obj


def weight_setup(obj, rig):
  props = bpy.context.scene.amt_bone_follow
  props.target_object = obj
  props.armature_object = rig
  props.bone_name = 'Follow'


def alignment_setup(reference, target):
  props = bpy.context.scene.amt_armature_align
  props.reference_object = reference
  props.target_object = target
  props.reference_bone = props.target_bone = 'Follow'


def assert_cancelled(operation, message):
  try:
    result = operation()
  except RuntimeError as exc:
    assert message in str(exc), str(exc)
  else:
    assert result == {'CANCELLED'}, result


def weights(obj):
  return (
    tuple(group.name for group in obj.vertex_groups),
    tuple(tuple((group.group, group.weight) for group in vertex.groups) for vertex in obj.data.vertices),
  )


def transform(obj):
  names = (
    'location', 'rotation_mode', 'rotation_euler', 'rotation_quaternion',
    'rotation_axis_angle', 'scale', 'delta_location', 'delta_rotation_euler',
    'delta_rotation_quaternion', 'delta_scale',
  )
  return {name: value if isinstance(value, str) else tuple(value)
          for name in names for value in (getattr(obj, name),)}


def assert_linear_unchanged(before, after):
  assert max(abs(before[row][col] - after[row][col])
             for row in range(3) for col in range(3)) < 1e-5, (before, after)


def assert_successful_translation(reference, target, before_channels, before_world):
  assert bpy.ops.object.amt_align_armature() == {'FINISHED'}
  after = transform(target)
  assert {k: v for k, v in after.items() if k != 'location'} == {
    k: v for k, v in before_channels.items() if k != 'location'
  }, (before_channels, after)
  assert_linear_unchanged(before_world, target.matrix_world)
  reference_head = reference.matrix_world @ reference.data.bones['Follow'].head_local
  target_head = target.matrix_world @ target.data.bones['Follow'].head_local
  assert (reference_head - target_head).length < 1e-4


def test_shared_weights_reject_without_edit_mode_or_data_changes():
  reset_scene()
  rig = armature('Rig')
  obj = cube('Accessory')
  group = obj.vertex_groups.new(name='Follow')
  group.add(list(range(8)), 0.25, 'REPLACE')
  other = obj.copy()
  other.name = 'UntouchedSharedObject'
  bpy.context.scene.collection.objects.link(other)
  before = weights(other)
  weight_setup(obj, rig)
  make_active(obj)
  bpy.ops.object.mode_set(mode='EDIT')
  assert_cancelled(bpy.ops.object.amt_assign_rigid_bone_weight, '共有')
  assert obj.mode == 'EDIT' and bpy.context.object == obj
  assert weights(obj) == before and weights(other) == before
  assert not obj.modifiers and not other.modifiers
  bpy.ops.object.mode_set(mode='OBJECT')
  assert weights(obj) == before and weights(other) == before


def test_linked_mesh_rejects_before_modifier_or_weights():
  reset_scene()
  source = cube('LibrarySource')
  mesh_name = source.data.name
  with tempfile.TemporaryDirectory(prefix='amt_bone_library_') as directory:
    filepath = str(Path(directory) / 'source.blend')
    bpy.data.libraries.write(filepath, {source.data})
    source_mesh = source.data
    bpy.data.objects.remove(source, do_unlink=True)
    bpy.data.meshes.remove(source_mesh)
    with bpy.data.libraries.load(filepath, link=True) as (source_ids, target_ids):
      target_ids.meshes = [mesh_name]
    obj = bpy.data.objects.new('LocalObjectLinkedMesh', target_ids.meshes[0])
    bpy.context.scene.collection.objects.link(obj)
    rig = armature('Rig')
    assert obj.library is None and obj.data.library is not None
    before = weights(obj)
    weight_setup(obj, rig)
    assert_cancelled(bpy.ops.object.amt_assign_rigid_bone_weight, 'リンク')
    assert weights(obj) == before and not obj.modifiers
    assert obj.data == target_ids.meshes[0]


def test_non_deform_bone_rejects_without_clearing_existing_weights():
  reset_scene()
  rig = armature('Rig')
  bpy.ops.object.mode_set(mode='EDIT')
  bone = rig.data.edit_bones.new('OtherDeform')
  bone.head = (0, 0, 1)
  bone.tail = (0, 0, 2)
  bpy.ops.object.mode_set(mode='OBJECT')
  rig.data.bones['Follow'].use_deform = False
  obj = cube('Accessory')
  obj.vertex_groups.new(name='OtherDeform').add(list(range(8)), 0.4, 'REPLACE')
  before = weights(obj)
  weight_setup(obj, rig)
  assert_cancelled(bpy.ops.object.amt_assign_rigid_bone_weight, '変形が無効')
  assert weights(obj) == before and not obj.modifiers


def test_fake_user_does_not_make_a_single_object_mesh_shared():
  reset_scene()
  rig = armature('Rig')
  obj = cube('Accessory')
  obj.data.use_fake_user = True
  assert obj.data.users == 2
  weight_setup(obj, rig)
  assert bpy.ops.object.amt_assign_rigid_bone_weight() == {'FINISHED'}
  group = obj.vertex_groups['Follow']
  assert all(abs(group.weight(vertex.index) - 1) < 1e-6 for vertex in obj.data.vertices)


def evaluated_positions(obj, indices):
  bpy.context.view_layer.update()
  evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
  return [evaluated.matrix_world @ evaluated.data.vertices[index].co for index in indices]


def test_documented_join_workflow_keeps_source_modifier_settings_supported():
  for source_setup in ('NONE', 'DISABLED_GROUPS', 'DUPLICATE_MODIFIERS'):
    reset_scene()
    rig = armature('Rig')
    obj = cube('Accessory', (4, 0, 0))
    if source_setup == 'DISABLED_GROUPS':
      mod = obj.modifiers.new('DisabledSourceGroups', 'ARMATURE')
      mod.object = rig
      mod.use_vertex_groups = False
    elif source_setup == 'DUPLICATE_MODIFIERS':
      for _ in range(2):
        obj.modifiers.new('SourceArmature', 'ARMATURE').object = rig
    base = cube('AvatarMesh')
    base.modifiers.new('BaseArmature', 'ARMATURE').object = rig
    weight_setup(obj, rig)
    assert bpy.ops.object.amt_assign_rigid_bone_weight() == {'FINISHED'}
    make_active(base)
    obj.select_set(True)
    assert bpy.ops.object.join() == {'FINISHED'}
    group = base.vertex_groups['Follow']
    indices = [v.index for v in base.data.vertices
               if any(g.group == group.index and abs(g.weight - 1) < 1e-6 for g in v.groups)]
    assert len(indices) == 8
    assert sum(mod.type == 'ARMATURE' for mod in base.modifiers) == 1
    before = evaluated_positions(base, indices)
    rig.pose.bones['Follow'].location.x = 1
    after = evaluated_positions(base, indices)
    assert all((end - start - Vector((1, 0, 0))).length < 1e-5
               for start, end in zip(before, after)), source_setup


def test_alignment_rejects_reference_and_target_edit_mode_without_hidden_edits():
  for edit_reference in (False, True):
    reset_scene()
    reference = armature('Reference')
    target = armature('Target', (2, 0, 0))
    alignment_setup(reference, target)
    edited = reference if edit_reference else target
    make_active(edited)
    bpy.ops.object.mode_set(mode='EDIT')
    bone = edited.data.edit_bones['Follow']
    bone.head.x += 3
    bone.tail.x += 3
    head, tail = tuple(bone.head), tuple(bone.tail)
    target_before = transform(target)
    assert_cancelled(bpy.ops.object.amt_align_armature, '編集モード')
    assert bpy.context.object == edited and edited.mode == 'EDIT'
    assert tuple(bone.head) == head and tuple(bone.tail) == tail
    assert transform(target) == target_before
    bpy.ops.object.mode_set(mode='OBJECT')


def test_alignment_preserves_partial_and_full_rotation_scale_constraints():
  for constraint_type in ('COPY_SCALE', 'COPY_ROTATION'):
    for influence in (0.5, 1.0):
      reset_scene()
      reference = armature('Reference')
      target = armature('Target', (2, 0, 0))
      target.rotation_mode = 'QUATERNION'
      target.rotation_quaternion = Quaternion((0, 0, 1), 0.2)
      target.scale = (0.8, 1.2, 1.3)
      target.delta_location = (0.4, -0.3, 0.2)
      target.delta_rotation_quaternion = Quaternion((1, 0, 0), 0.1)
      target.delta_scale = (1.1, 0.9, 1.2)
      anchor = bpy.data.objects.new('Anchor', None)
      bpy.context.scene.collection.objects.link(anchor)
      anchor.rotation_euler.z = 1
      anchor.scale = (2, 3, 4)
      constraint = target.constraints.new(constraint_type)
      constraint.target = anchor
      constraint.influence = influence
      alignment_setup(reference, target)
      bpy.context.view_layer.update()
      assert_successful_translation(reference, target, transform(target), target.matrix_world.copy())


def test_alignment_handles_parent_inverse_rotation_scale_and_delta_transforms():
  reset_scene()
  reference = armature('Reference', (2, 3, 4))
  target = armature('Target')
  bpy.ops.object.mode_set(mode='EDIT')
  bone = target.data.edit_bones['Follow']
  bone.head = (0.3, -0.2, 0.7)
  bone.tail = (0.3, -0.2, 1.7)
  bpy.ops.object.mode_set(mode='OBJECT')
  parent = bpy.data.objects.new('ScaledRotatedParent', None)
  bpy.context.scene.collection.objects.link(parent)
  parent.location = (-1, 2, 0.5)
  parent.rotation_euler = (0.2, 0.5, 0.6)
  parent.scale = (2, 0.5, 1.3)
  target.parent = parent
  target.matrix_parent_inverse = Matrix.Rotation(0.4, 4, 'Y') @ Matrix.Diagonal((0.8, 1.1, 0.9, 1))
  target.location = (2, -1, 0.4)
  target.rotation_euler = (0.3, -0.1, 0.2)
  target.scale = (0.8, 1.2, 1)
  target.delta_location = (0.4, -0.2, 0.1)
  target.delta_rotation_euler = (0.1, 0.2, 0.3)
  target.delta_scale = (1.1, 0.9, 1.2)
  alignment_setup(reference, target)
  bpy.context.view_layer.update()
  parent_before = transform(parent)
  assert_successful_translation(reference, target, transform(target), target.matrix_world.copy())
  assert transform(parent) == parent_before


def test_alignment_handles_bone_parent_with_and_without_relative_parent():
  for relative_parent in (False, True):
    reset_scene()
    reference = armature('Reference', (2, 3, 4))
    parent = armature('ParentRig', (1, -2, 0.5))
    bpy.ops.object.mode_set(mode='EDIT')
    bone = parent.data.edit_bones['Follow']
    bone.head = (0.2, -0.3, 0.4)
    bone.tail = (0.8, 0.5, 0.7)
    bone.roll = 0.4
    bpy.ops.object.mode_set(mode='OBJECT')
    parent.data.bones['Follow'].use_relative_parent = relative_parent
    parent.rotation_euler = (0.3, 0.5, 0.2)
    parent.scale = (1.3, 0.8, 1.1)
    parent.pose.bones['Follow'].rotation_mode = 'XYZ'
    parent.pose.bones['Follow'].rotation_euler = (0.2, -0.3, 0.5)
    target = armature('Target')
    target.parent = parent
    target.parent_type = 'BONE'
    target.parent_bone = 'Follow'
    target.matrix_parent_inverse = Matrix.Rotation(0.2, 4, 'X')
    target.location = (2, 1, -0.5)
    target.rotation_euler = (0.1, 0.2, 0.3)
    target.scale = (0.8, 1.2, 1)
    alignment_setup(reference, target)
    bpy.context.view_layer.update()
    assert_successful_translation(reference, target, transform(target), target.matrix_world.copy())


def test_unsatisfiable_constraints_and_driver_restore_all_channels():
  for setup in ('COPY_LOCATION', 'TRACK_TO', 'LOCATION_DRIVER'):
    reset_scene()
    reference = armature('Reference')
    target = armature('Target', (2, 0, 0))
    target.rotation_euler = (0.1, 0.2, 0.3)
    target.delta_location = (0.2, 0.3, 0.4)
    target.delta_rotation_euler = (0.2, 0.1, 0.3)
    target.delta_scale = (1.2, 1.1, 0.9)
    if setup == 'LOCATION_DRIVER':
      target.driver_add('location', 0).driver.expression = '2'
    else:
      anchor = bpy.data.objects.new('Anchor', None)
      bpy.context.scene.collection.objects.link(anchor)
      anchor.location = (5, 2, 1)
      target.constraints.new(setup).target = anchor
    alignment_setup(reference, target)
    bpy.context.view_layer.update()
    before, world_before = transform(target), target.matrix_world.copy()
    assert_cancelled(bpy.ops.object.amt_align_armature, '元に戻しました')
    assert transform(target) == before, (setup, before, transform(target))
    assert_linear_unchanged(world_before, target.matrix_world)
    assert (world_before.translation - target.matrix_world.translation).length < 1e-5


def test_zero_scale_parent_rejects_and_restores():
  reset_scene()
  reference = armature('Reference', (3, 0, 0))
  target = armature('Target')
  parent = bpy.data.objects.new('ZeroScaleParent', None)
  bpy.context.scene.collection.objects.link(parent)
  parent.scale.x = 0
  target.parent = parent
  alignment_setup(reference, target)
  bpy.context.view_layer.update()
  before = transform(target)
  assert_cancelled(bpy.ops.object.amt_align_armature, '元に戻しました')
  assert transform(target) == before


TESTS = (
  test_shared_weights_reject_without_edit_mode_or_data_changes,
  test_linked_mesh_rejects_before_modifier_or_weights,
  test_non_deform_bone_rejects_without_clearing_existing_weights,
  test_fake_user_does_not_make_a_single_object_mesh_shared,
  test_documented_join_workflow_keeps_source_modifier_settings_supported,
  test_alignment_rejects_reference_and_target_edit_mode_without_hidden_edits,
  test_alignment_preserves_partial_and_full_rotation_scale_constraints,
  test_alignment_handles_parent_inverse_rotation_scale_and_delta_transforms,
  test_alignment_handles_bone_parent_with_and_without_relative_parent,
  test_unsatisfiable_constraints_and_driver_restore_all_channels,
  test_zero_scale_parent_rejects_and_restores,
)

for test in TESTS:
  test()
  print('PASS', test.__name__)

NuniAvatarToolkit.unregister()
print('BLENDER_BONE_RELEASE_SAFETY_OK')
