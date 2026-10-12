import importlib.util
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_utils():
  path = REPO_ROOT / 'NuniAvatarToolkit/features/bone_follow/utils.py'
  spec = importlib.util.spec_from_file_location('bone_follow_utils_for_test', path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def make_object(name, object_type='MESH', parent_type='OBJECT'):
  return types.SimpleNamespace(
    name=name,
    type=object_type,
    parent_type=parent_type,
    library=None,
    override_library=None,
    data=types.SimpleNamespace(vertices=[object()]),
  )


class BoneWeightTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.utils = load_utils()

  def test_rejects_non_mesh_target(self):
    target = make_object('Light', 'LIGHT')
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={'Head': object()})

    with self.assertRaisesRegex(ValueError, 'メッシュオブジェクト'):
      self.utils.validate_weight_setup(target, armature, 'Head')

  def test_rejects_missing_bone(self):
    target = make_object('Accessory')
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={})

    with self.assertRaisesRegex(ValueError, '見つかりません'):
      self.utils.validate_weight_setup(target, armature, 'Missing')

  def test_rejects_existing_bone_parent(self):
    target = make_object('Accessory', parent_type='BONE')
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={'Head': object()})

    with self.assertRaisesRegex(ValueError, 'Bone Parent'):
      self.utils.validate_weight_setup(target, armature, 'Head')

  def test_rejects_target_in_edit_mode(self):
    target = make_object('Accessory')
    target.mode = 'EDIT'
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={'Head': object()})

    with self.assertRaisesRegex(ValueError, '編集モード'):
      self.utils.validate_weight_setup(target, armature, 'Head')

  def test_edit_mode_can_be_allowed_for_pre_validation(self):
    target = make_object('Accessory')
    target.mode = 'EDIT'
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={'Head': object()})

    self.utils.validate_weight_setup(target, armature, 'Head', allow_edit_mode=True)

  def test_rejects_modifier_bound_to_another_armature(self):
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={'Head': object()})
    other = make_object('Other', 'ARMATURE')
    target = make_object('Accessory')
    target.modifiers = [types.SimpleNamespace(type='ARMATURE', object=other)]

    with self.assertRaisesRegex(ValueError, '別のArmature'):
      self.utils.validate_weight_setup(target, armature, 'Head', allow_edit_mode=True)

  def test_rejects_other_armature_even_alongside_reusable_modifiers(self):
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={'Head': object()})
    other = make_object('Other', 'ARMATURE')
    for reusable in (armature, None):
      target = make_object('Accessory')
      target.modifiers = [
        types.SimpleNamespace(type='ARMATURE', object=reusable),
        types.SimpleNamespace(type='ARMATURE', object=other),
      ]
      with self.assertRaisesRegex(ValueError, '別のArmature'):
        self.utils.validate_weight_setup(target, armature, 'Head')

  def test_accepts_modifier_bound_to_same_armature(self):
    armature = make_object('Armature', 'ARMATURE')
    armature.data = types.SimpleNamespace(bones={'Head': object()})
    target = make_object('Accessory')
    target.modifiers = [types.SimpleNamespace(type='ARMATURE', object=armature)]

    self.utils.validate_weight_setup(target, armature, 'Head')


if __name__ == '__main__':
  unittest.main()
