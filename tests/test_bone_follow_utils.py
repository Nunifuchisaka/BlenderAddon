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


if __name__ == '__main__':
  unittest.main()
