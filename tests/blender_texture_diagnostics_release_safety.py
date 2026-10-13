"""Real Blender regressions for texture decoding and pre-export diagnostics.

Run: blender --background --factory-startup --python-exit-code 1 --python tests/blender_texture_diagnostics_release_safety.py
"""

import math
import sys
import tempfile
from pathlib import Path

import bpy

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import NuniAvatarToolkit
from NuniAvatarToolkit.features.diagnostics import utils as diagnostics
from NuniAvatarToolkit.features.texture_relink import utils as textures


def reset_scene():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for image in list(bpy.data.images):
        if image.name not in {'Render Result', 'Viewer Node'}:
            bpy.data.images.remove(image)


def write_png(path, value=0.5):
    image = bpy.data.images.new('PNGFixture', width=2, height=2)
    try:
        image.pixels[:] = [value, value, value, 1.0] * 4
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


def missing_cached_image(path):
    write_png(path)
    image = bpy.data.images.load(str(path), check_existing=False)
    assert tuple(image.size) == (2, 2)
    path.unlink()
    assert image.has_data and not path.exists()
    return image


def make_collection(name, parent=None):
    collection = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(collection)
    return collection


def move_to_collection(obj, collection):
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)


def avatar_fixture(collection=None):
    collection = collection or make_collection('Avatar')
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    move_to_collection(cube, collection)
    bpy.ops.object.armature_add()
    armature = bpy.context.object
    move_to_collection(armature, collection)
    bpy.context.view_layer.update()
    return collection, cube, armature


def run_diagnostics(collection):
    props = bpy.context.scene.amt_diagnostics
    props.avatar_collection = collection
    bpy.context.view_layer.update()
    assert bpy.ops.object.amt_diagnostics_run() == {'FINISHED'}
    return [(line.level, line.text) for line in props.report_lines]


def branch_warnings(lines):
    return [text for _level, text in lines if 'のコレクションですが' in text]


def test_corrupt_candidate_keeps_original_cache_and_can_retry():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        originals = root / 'originals'
        candidates = root / 'candidates'
        originals.mkdir()
        candidates.mkdir()
        broken = missing_cached_image(originals / 'Broken.png')
        good = missing_cached_image(originals / 'Good.png')
        original_path = broken.filepath
        original_pixels = tuple(broken.pixels)
        (candidates / 'Broken.png').write_bytes(b'not an image')
        write_png(candidates / 'Good.png', 0.8)
        images_before = {image.as_pointer() for image in bpy.data.images}

        result = textures.relink_missing_textures([broken, good], str(candidates))
        assert [image for image, _ in result['failed']] == [broken], result
        assert [image for image, _ in result['relinked']] == [good], result
        assert broken.filepath == original_path and broken.has_data
        assert tuple(broken.pixels) == original_pixels
        assert textures.collect_missing_images([broken]) == [broken]
        assert {image.as_pointer() for image in bpy.data.images} == images_before

        props = bpy.context.scene.amt_texture_relink
        props.search_directory = str(candidates)
        assert bpy.ops.object.amt_relink_textures() == {'FINISHED'}
        assert any(line.level == 'ERROR' and broken.name in line.text for line in props.report_lines)
        assert not any('再リンクしました' in line.text for line in props.report_lines)
        assert broken.filepath == original_path and tuple(broken.pixels) == original_pixels
        assert {image.as_pointer() for image in bpy.data.images} == images_before

        write_png(candidates / 'Broken.png', 0.2)
        retry = textures.relink_missing_textures([broken], str(candidates))
        assert [image for image, _ in retry['relinked']] == [broken], retry
        assert not retry['failed'] and broken.has_data and tuple(broken.size) == (2, 2)
        assert broken.filepath == str(candidates / 'Broken.png')
        assert tuple(broken.pixels) != original_pixels
        assert {image.as_pointer() for image in bpy.data.images} == images_before


def test_validation_does_not_reuse_an_existing_cached_candidate():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'Cached.png'
        write_png(path)
        cached = bpy.data.images.load(str(path), check_existing=False)
        assert tuple(cached.size) == (2, 2)
        path.write_bytes(b'corrupt after it was cached')
        images_before = {image.as_pointer() for image in bpy.data.images}
        try:
            textures._validate_candidate_image(str(path))
        except RuntimeError:
            pass
        else:
            raise AssertionError('corrupt file was validated through a stale cached datablock')
        assert {image.as_pointer() for image in bpy.data.images} == images_before
        assert cached.has_data


def test_nonthrowing_reload_failure_restores_missing_path():
    class DisappearingCandidate:
        """Inject a file-removal race, but use Blender for decoding and reloading."""
        def __init__(self, image, candidate):
            self.image = image
            self.candidate = candidate

        def __getattr__(self, name):
            return getattr(self.image, name)

        @property
        def filepath(self):
            return self.image.filepath

        @filepath.setter
        def filepath(self, value):
            self.image.filepath = value

        def reload(self):
            self.candidate.unlink()
            self.image.reload()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        originals = root / 'originals'
        candidates = root / 'candidates'
        originals.mkdir()
        candidates.mkdir()
        image = missing_cached_image(originals / 'Race.png')
        old_path = image.filepath
        path = candidates / 'Race.png'
        write_png(path)
        images_before = {item.as_pointer() for item in bpy.data.images}
        proxy = DisappearingCandidate(image, path)
        result = textures.relink_missing_textures([proxy], str(candidates))
        assert not result['relinked'] and len(result['failed']) == 1, result
        assert image.filepath == old_path
        assert textures.collect_missing_images([image]) == [image]
        assert {item.as_pointer() for item in bpy.data.images} == images_before


def test_normal_avatar_has_no_false_diagnostic_errors():
    collection, _cube, _armature = avatar_fixture()
    lines = run_diagnostics(collection)
    assert not any(level == 'ERROR' for level, _text in lines), lines
    assert not branch_warnings(lines), lines
    assert any(text == '重大な問題は検出されませんでした' for _level, text in lines), lines


def test_target_root_exclusion_and_hide_render_are_reported():
    collection, _cube, _armature = avatar_fixture()
    layer = diagnostics.find_layer_collection(bpy.context.view_layer.layer_collection, collection)
    layer.exclude = True
    warnings = branch_warnings(run_diagnostics(collection))
    assert len(warnings) == 1 and '[Avatar]' in warnings[0] and '除外' in warnings[0], warnings
    layer.exclude = False
    collection.hide_render = True
    warnings = branch_warnings(run_diagnostics(collection))
    assert len(warnings) == 1 and '[Avatar]' in warnings[0] and '非表示' in warnings[0], warnings


def test_ancestor_restrictions_are_reported_at_the_target_root():
    parent = make_collection('Parent')
    target = make_collection('Avatar', parent)
    avatar_fixture(target)
    parent_layer = diagnostics.find_layer_collection(bpy.context.view_layer.layer_collection, parent)
    parent_layer.exclude = True
    warnings = branch_warnings(run_diagnostics(target))
    assert len(warnings) == 1 and '[Avatar]' in warnings[0] and '除外' in warnings[0], warnings
    parent_layer.exclude = False
    parent.hide_render = True
    warnings = branch_warnings(run_diagnostics(target))
    assert len(warnings) == 1 and '[Avatar]' in warnings[0] and '非表示' in warnings[0], warnings


def test_shared_target_uses_all_of_its_view_layer_paths():
    blocked = make_collection('BlockedParent')
    available = make_collection('AvailableParent')
    target = make_collection('Avatar', blocked)
    available.children.link(target)
    avatar_fixture(target)
    blocked_layer = diagnostics.find_layer_collection(bpy.context.view_layer.layer_collection, blocked)
    blocked_layer.exclude = True
    blocked.hide_render = True
    assert not branch_warnings(run_diagnostics(target))


def test_child_layer_restriction_is_resolved_within_the_target():
    outside = make_collection('Outside')
    target = make_collection('Avatar')
    shared = make_collection('Shared', outside)
    target.children.link(shared)
    avatar_fixture(shared)
    outside_layer = diagnostics.find_layer_collection(bpy.context.view_layer.layer_collection, outside)
    target_layer = diagnostics.find_layer_collection(bpy.context.view_layer.layer_collection, target)
    outside_layer.children['Shared'].exclude = True
    assert not branch_warnings(run_diagnostics(target))
    outside_layer.children['Shared'].exclude = False
    target_layer.children['Shared'].exclude = True
    warnings = branch_warnings(run_diagnostics(target))
    assert len(warnings) == 1 and '[Shared]' in warnings[0] and '除外' in warnings[0], warnings


def test_nested_restrictions_only_report_topmost_branch():
    target = make_collection('Avatar')
    top = make_collection('Top', target)
    nested = make_collection('Nested', top)
    avatar_fixture(nested)
    top_layer = diagnostics.find_layer_collection(bpy.context.view_layer.layer_collection, top)
    top_layer.exclude = True
    top_layer.children['Nested'].exclude = True
    warnings = branch_warnings(run_diagnostics(target))
    assert len(warnings) == 1 and '[Top]' in warnings[0], warnings


def test_basis_nonfinite_coordinates_are_reported_and_reach_obj_export():
    collection, cube, _armature = avatar_fixture()
    basis = cube.shape_key_add(name='Basis')
    cube.shape_key_add(name='Morph')
    basis.data[0].co.x = math.nan
    assert diagnostics.find_non_finite_vertices(cube) == 0
    assert diagnostics.find_non_finite_shape_keys(cube) == [('Basis', 1)]
    lines = run_diagnostics(collection)
    assert any(level == 'ERROR' and 'シェイプキー「Basis」' in text for level, text in lines), lines
    assert not any(text == '重大な問題は検出されませんでした' for _level, text in lines), lines
    bpy.ops.object.select_all(action='DESELECT')
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'invalid.obj'
        bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=True, export_materials=False)
        vertices = [line.split()[1:] for line in path.read_text().splitlines() if line.startswith('v ')]
        assert any(not all(math.isfinite(float(value)) for value in vertex) for vertex in vertices)


def add_geometry_node_material(obj, material):
    tree = bpy.data.node_groups.new('GeneratedMaterial', 'GeometryNodeTree')
    tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    input_node = tree.nodes.new('NodeGroupInput')
    output_node = tree.nodes.new('NodeGroupOutput')
    set_material = tree.nodes.new('GeometryNodeSetMaterial')
    set_material.inputs['Material'].default_value = material
    tree.links.new(input_node.outputs['Geometry'], set_material.inputs['Geometry'])
    tree.links.new(set_material.outputs['Geometry'], output_node.inputs['Geometry'])
    obj.modifiers.new('GeneratedMaterial', 'NODES').node_group = tree


def test_geometry_nodes_materials_are_counted_in_the_report_and_fbx():
    collection, first, _armature = avatar_fixture()
    bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
    second = bpy.context.object
    move_to_collection(second, collection)
    material = bpy.data.materials.new('OutputMaterial')
    add_geometry_node_material(first, material)
    add_geometry_node_material(second, material)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    assert diagnostics.count_material_slots([first, second]) == 0
    assert diagnostics.count_material_slots([first, second], depsgraph) == 2
    lines = run_diagnostics(collection)
    assert any(text.startswith('マテリアルスロット数: 2 ') and 'Quest: Medium' in text for _level, text in lines), lines
    bpy.ops.object.select_all(action='DESELECT')
    first.select_set(True)
    second.select_set(True)
    bpy.context.view_layer.objects.active = first
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'generated.fbx')
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, use_mesh_modifiers=True)
        bpy.ops.import_scene.fbx(filepath=path)
        imported = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
        assert len(imported) == 2 and sum(len(obj.material_slots) for obj in imported) == 2


def test_evaluated_slots_preserve_duplicate_material_slots():
    _collection, cube, _armature = avatar_fixture()
    material = bpy.data.materials.new('Repeated')
    for _ in range(3):
        cube.data.materials.append(material)
    bpy.context.view_layer.update()
    assert diagnostics.count_material_slots([cube], bpy.context.evaluated_depsgraph_get()) == 3


def test_armature_transforms_are_reported():
    collection, _cube, armature = avatar_fixture()
    armature.delta_scale = (-1.0, 2.0, 1.0)
    armature.rotation_mode = 'QUATERNION'
    armature.delta_rotation_quaternion = (0.9238795, 0.0, 0.3826834, 0.0)
    lines = run_diagnostics(collection)
    warnings = [text for level, text in lines if level == 'WARNING' and f'[{armature.name}]' in text]
    assert any('マイナス値' in text for text in warnings), lines
    assert any('不均一' in text for text in warnings), lines
    assert any('回転が適用されていません' in text for text in warnings), lines
    assert not any(text == '重大な問題は検出されませんでした' for _level, text in lines), lines


TESTS = (
    test_corrupt_candidate_keeps_original_cache_and_can_retry,
    test_validation_does_not_reuse_an_existing_cached_candidate,
    test_nonthrowing_reload_failure_restores_missing_path,
    test_normal_avatar_has_no_false_diagnostic_errors,
    test_target_root_exclusion_and_hide_render_are_reported,
    test_ancestor_restrictions_are_reported_at_the_target_root,
    test_shared_target_uses_all_of_its_view_layer_paths,
    test_child_layer_restriction_is_resolved_within_the_target,
    test_nested_restrictions_only_report_topmost_branch,
    test_basis_nonfinite_coordinates_are_reported_and_reach_obj_export,
    test_geometry_nodes_materials_are_counted_in_the_report_and_fbx,
    test_evaluated_slots_preserve_duplicate_material_slots,
    test_armature_transforms_are_reported,
)

NuniAvatarToolkit.register()
try:
    for test in TESTS:
        reset_scene()
        test()
        print(f'PASS {test.__name__}', flush=True)
    print('BLENDER_TEXTURE_DIAGNOSTICS_RELEASE_SAFETY_OK', flush=True)
finally:
    reset_scene()
    NuniAvatarToolkit.unregister()
