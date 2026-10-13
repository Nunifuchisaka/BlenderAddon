"""Real Blender regressions for destructive cleanup / material-slot release safety.

Run: blender --background --factory-startup --python-exit-code 1 --python tests/blender_cleanup_release_safety.py
"""
import sys
import tempfile
from pathlib import Path

import bpy
import bmesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import NuniAvatarToolkit

NuniAvatarToolkit.register()
FLAGS = (
    'remove_empty_vertex_groups', 'remove_noop_shape_keys', 'remove_unused_uv_maps',
    'remove_unused_vertex_colors', 'remove_unused_material_slots', 'remove_loose_geometry',
)


def reset_scene():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def make_mesh(name='Body'):
    mesh = bpy.data.meshes.new(name + 'Mesh')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    make_active(obj)
    return obj


def make_active(*objects):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def set_flags(obj, *enabled):
    props = bpy.context.scene.amt_cleanup
    props.target_object = obj
    for name in FLAGS:
        setattr(props, name, name in enabled)
    return props


def add_unused_data(obj):
    obj.vertex_groups.new(name='EmptyGroup')
    obj.shape_key_add(name='Basis', from_mix=False)
    obj.shape_key_add(name='EmptyKey', from_mix=False)
    obj.data.uv_layers.new(name='MainUV')
    obj.data.uv_layers.new(name='UnusedUV')
    obj.data.uv_layers.active_index = 0
    obj.data.uv_layers[0].active_render = True


def snapshot(obj):
    return (
        tuple(vg.name for vg in obj.vertex_groups),
        tuple(kb.name for kb in obj.data.shape_keys.key_blocks) if obj.data.shape_keys else (),
        tuple(uv.name for uv in obj.data.uv_layers),
        tuple(attr.name for attr in obj.data.color_attributes),
        tuple((slot.material, slot.link) for slot in obj.material_slots),
        tuple(poly.material_index for poly in obj.data.polygons),
        tuple(tuple(v.co) for v in obj.data.vertices),
    )


def assert_cancelled(operator, message):
    try:
        result = operator('EXEC_DEFAULT')
    except RuntimeError as exc:
        assert message in str(exc) and 'Traceback' not in str(exc), str(exc)
    else:
        assert result == {'CANCELLED'}, result


def evaluated_materials(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [evaluated.data.materials[p.material_index].original for p in evaluated.data.polygons]


def test_edited_shape_key_is_preserved_by_scan_and_cleanup():
    reset_scene()
    obj = make_mesh('Edited')
    obj.shape_key_add(name='Basis', from_mix=False)
    key = obj.shape_key_add(name='Smile', from_mix=False)
    obj.active_shape_key_index = 1
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.verts[0].co.z = 0.2
    bmesh.update_edit_mesh(obj.data)
    props = set_flags(obj, 'remove_noop_shape_keys')
    assert bpy.ops.object.amt_cleanup_scan() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_MESH'
    assert any('シェイプキー: 0 個' in line.text for line in props.report_lines)
    assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_MESH'
    assert 'Smile' in obj.data.shape_keys.key_blocks
    bpy.ops.object.mode_set(mode='OBJECT')
    assert abs(key.data[0].co.z - 0.2) < 1e-6


def test_shared_mesh_rejects_all_cleanup_before_any_mutation():
    reset_scene()
    obj = make_mesh('Target')
    add_unused_data(obj)
    twin = obj.copy()
    twin.name = 'NotTarget'
    twin.data = obj.data
    bpy.context.scene.collection.objects.link(twin)
    mod = twin.modifiers.new('ReadsOtherUV', 'DISPLACE')
    mod.texture_coords = 'UV'
    mod.uv_layer = 'UnusedUV'
    set_flags(obj, *FLAGS)
    before = snapshot(obj), snapshot(twin)
    assert_cancelled(bpy.ops.object.amt_cleanup_execute, '共有')
    assert (snapshot(obj), snapshot(twin)) == before
    assert bpy.context.active_object == obj


def link_data(obj, local_object=False):
    path = str(Path(tempfile.mkdtemp()) / 'library.blend')
    mesh_name, name = obj.data.name, obj.name
    bpy.data.libraries.write(path, {obj}, fake_user=True)
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    with bpy.data.libraries.load(path, link=True) as (_source, target):
        if local_object:
            target.meshes = [mesh_name]
        else:
            target.objects = [name]
    obj = bpy.data.objects.new('LocalUsingLinkedMesh', target.meshes[0]) if local_object else target.objects[0]
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    make_active(obj)
    return obj


def test_linked_object_and_linked_mesh_reject_before_partial_mutation():
    for local_object in (False, True):
        reset_scene()
        obj = make_mesh('LinkedTarget')
        add_unused_data(obj)
        obj = link_data(obj, local_object)
        assert obj.data.library is not None
        assert (obj.library is None) == local_object
        set_flags(obj, *FLAGS)
        before = snapshot(obj)
        assert_cancelled(bpy.ops.object.amt_cleanup_execute, 'リンク')
        assert snapshot(obj) == before


def test_hidden_mesh_rejects_before_removing_attributes():
    reset_scene()
    obj = make_mesh('Hidden')
    add_unused_data(obj)
    obj.hide_set(True)
    set_flags(obj, *FLAGS)
    before = snapshot(obj)
    assert_cancelled(bpy.ops.object.amt_cleanup_execute, '非表示')
    assert snapshot(obj) == before


def test_effective_object_material_preserves_uv_and_color_references():
    reset_scene()
    obj = make_mesh('ObjectMaterial')
    obj.data.materials.append(bpy.data.materials.new('DataMaterial'))
    material = bpy.data.materials.new('EffectiveMaterial')
    material.use_nodes = True
    obj.material_slots[0].link = 'OBJECT'
    obj.material_slots[0].material = material
    node = material.node_tree.nodes.new('ShaderNodeUVMap')
    node.uv_map = 'RequiredUV'
    texture = material.node_tree.nodes.new('ShaderNodeTexImage')
    material.node_tree.links.new(node.outputs['UV'], texture.inputs['Vector'])
    color_node = material.node_tree.nodes.new('ShaderNodeVertexColor')
    color_node.layer_name = 'RequiredColor'
    for name in ('MainUV', 'RequiredUV', 'UnusedUV'):
        obj.data.uv_layers.new(name=name)
    obj.data.uv_layers.active_index = 0
    obj.data.uv_layers[0].active_render = True
    for name in ('MainColor', 'RequiredColor', 'UnusedColor'):
        obj.data.color_attributes.new(name=name, type='FLOAT_COLOR', domain='POINT')
    obj.data.color_attributes.active_color = obj.data.color_attributes['MainColor']
    obj.data.color_attributes.render_color_index = 0
    set_flags(obj, 'remove_unused_uv_maps', 'remove_unused_vertex_colors')
    assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
    assert [uv.name for uv in obj.data.uv_layers] == ['MainUV', 'RequiredUV']
    assert [color.name for color in obj.data.color_attributes] == ['MainColor', 'RequiredColor']


def test_live_driver_controls_survive_key_mesh_and_object_paths():
    reset_scene()
    obj = make_mesh('DriverControls')
    obj.shape_key_add(name='Basis', from_mix=False)
    controls = []
    for name, value in [('Control"\\Toggle', 0.7), ('MeshControl', 0.4), ('ObjectControl', 0.2)]:
        key = obj.shape_key_add(name=name, from_mix=False)
        key.value = value
        controls.append(key)
    obj.shape_key_add(name='UnreferencedEmpty', from_mix=False)
    material = bpy.data.materials.new('DrivenMaterial')
    material.use_nodes = True
    obj.data.materials.append(material)
    bsdf = material.node_tree.nodes.get('Principled BSDF')
    drivers = []
    settings = [('Roughness', 'KEY', obj.data.shape_keys, controls[0].path_from_id() + '.value'),
                ('Metallic', 'MESH', obj.data, 'shape_keys.' + controls[1].path_from_id() + '.value'),
                ('Alpha', 'OBJECT', obj, 'data.shape_keys.key_blocks[3].value')]
    for input_name, id_type, target_id, path in settings:
        curve = bsdf.inputs[input_name].driver_add('default_value')
        curve.driver.type = 'SCRIPTED'
        curve.driver.expression = 'control'
        var = curve.driver.variables.new()
        var.name = 'control'
        var.type = 'SINGLE_PROP'
        var.targets[0].id_type = id_type
        var.targets[0].id = target_id
        var.targets[0].data_path = path
        drivers.append(curve)
    bpy.context.view_layer.update()
    before = [bsdf.inputs[name].default_value for name, *_ in settings]
    assert all(abs(actual - expected) < 1e-6 for actual, expected in zip(before, (0.7, 0.4, 0.2))), before
    set_flags(obj, 'remove_noop_shape_keys')
    assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
    bpy.context.view_layer.update()
    assert all(key.name in obj.data.shape_keys.key_blocks for key in controls)
    assert 'UnreferencedEmpty' not in obj.data.shape_keys.key_blocks
    assert all(curve.driver.is_valid for curve in drivers)
    assert [bsdf.inputs[name].default_value for name, *_ in settings] == before


def test_solidify_cleanup_rejects_before_other_categories_change():
    reset_scene()
    obj = make_mesh('SolidifyCleanup')
    add_unused_data(obj)
    for name in ('ClothBase', 'ClothRim'):
        obj.data.materials.append(bpy.data.materials.new(name))
    mod = obj.modifiers.new('Solidify', 'SOLIDIFY')
    mod.thickness = 0.1
    mod.material_offset_rim = 1
    props = set_flags(obj, *FLAGS)
    bpy.ops.object.mode_set(mode='EDIT')
    before = snapshot(obj), evaluated_materials(obj)
    assert bpy.ops.object.amt_cleanup_scan() == {'FINISHED'}
    assert any('モディファイア' in line.text and line.level == 'WARNING' for line in props.report_lines)
    assert_cancelled(bpy.ops.object.amt_cleanup_execute, 'モディファイア')
    assert bpy.context.mode == 'EDIT_MESH'
    assert (snapshot(obj), evaluated_materials(obj)) == before
    # Users can still clean the other categories by disabling this one option.
    props.remove_unused_material_slots = False
    assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_MESH'
    assert evaluated_materials(obj) == before[1]


def test_indexed_driver_keeps_preceding_shape_key_indices():
    reset_scene()
    obj = make_mesh('IndexedDriver')
    obj.shape_key_add(name='Basis', from_mix=False)
    obj.shape_key_add(name='IndexPadding', from_mix=False)
    control = obj.shape_key_add(name='IndexedControl', from_mix=False)
    control.value = 0.6
    obj.shape_key_add(name='UnusedAfterControl', from_mix=False)
    obj['output'] = 0.0
    curve = obj.driver_add('["output"]')
    curve.driver.type = 'SCRIPTED'
    curve.driver.expression = 'control'
    var = curve.driver.variables.new()
    var.name = 'control'
    var.type = 'SINGLE_PROP'
    var.targets[0].id_type = 'KEY'
    var.targets[0].id = obj.data.shape_keys
    var.targets[0].data_path = 'key_blocks[2].value'
    set_flags(obj, 'remove_noop_shape_keys')
    assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
    bpy.context.view_layer.update()
    assert [kb.name for kb in obj.data.shape_keys.key_blocks] == ['Basis', 'IndexPadding', 'IndexedControl']
    assert curve.driver.is_valid and abs(obj['output'] - 0.6) < 1e-6


def test_solidify_merge_preserves_slot_and_rim_materials():
    reset_scene()
    obj = make_mesh('SolidifyMerge')
    material_a = bpy.data.materials.new('A')
    for material in (material_a, material_a, bpy.data.materials.new('B'), bpy.data.materials.new('C')):
        obj.data.materials.append(material)
    mod = obj.modifiers.new('Solidify', 'SOLIDIFY')
    mod.thickness = 0.1
    mod.material_offset_rim = 2
    before = snapshot(obj), evaluated_materials(obj)
    assert_cancelled(bpy.ops.object.amt_merge_material_slots, 'モディファイア')
    assert (snapshot(obj), evaluated_materials(obj)) == before
    assert mod.material_offset_rim == 2


def test_disabled_material_index_modifiers_are_also_protected():
    for modifier_type in ('BEVEL', 'WIREFRAME', 'NODES'):
        reset_scene()
        obj = make_mesh('DisabledModifier')
        material_a = bpy.data.materials.new('Repeat')
        obj.data.materials.append(material_a)
        obj.data.materials.append(material_a)
        obj.modifiers.new('FutureMaterialIndex', modifier_type).show_viewport = False
        before = snapshot(obj)
        assert_cancelled(bpy.ops.object.amt_merge_material_slots, 'モディファイア')
        assert snapshot(obj) == before


def test_wireframe_cleanup_preserves_generated_materials_before_any_deletion():
    reset_scene()
    obj = make_mesh('WireframeCleanup')
    add_unused_data(obj)
    surface, wire = bpy.data.materials.new('Surface'), bpy.data.materials.new('Wire')
    obj.data.materials.append(surface)
    obj.data.materials.append(wire)
    mod = obj.modifiers.new('Wireframe', 'WIREFRAME')
    mod.material_offset = 1
    set_flags(obj, *FLAGS)
    before = snapshot(obj), evaluated_materials(obj)
    assert wire in before[1], before[1]
    assert_cancelled(bpy.ops.object.amt_cleanup_execute, 'モディファイア')
    assert (snapshot(obj), evaluated_materials(obj)) == before


def test_wireframe_merge_preserves_generated_material_indices():
    reset_scene()
    obj = make_mesh('WireframeMerge')
    material_a = bpy.data.materials.new('WireA')
    for material in (material_a, material_a, bpy.data.materials.new('WireB')):
        obj.data.materials.append(material)
    mod = obj.modifiers.new('Wireframe', 'WIREFRAME')
    mod.material_offset = 1
    before = snapshot(obj), evaluated_materials(obj)
    assert before[1] and all(material == material_a for material in before[1])
    assert_cancelled(bpy.ops.object.amt_merge_material_slots, 'モディファイア')
    assert (snapshot(obj), evaluated_materials(obj)) == before
    assert mod.material_offset == 1


def test_simple_slot_cleanup_and_merge_continue_to_work():
    reset_scene()
    obj = make_mesh('SimpleSlots')
    obj.data.use_fake_user = True
    material_a, material_b = bpy.data.materials.new('SimpleA'), bpy.data.materials.new('SimpleB')
    for material in (material_a, material_a, material_b):
        obj.data.materials.append(material)
    obj.data.polygons[0].material_index = 1
    assert bpy.ops.object.amt_merge_material_slots('EXEC_DEFAULT') == {'FINISHED'}
    assert [slot.material for slot in obj.material_slots] == [material_a, material_b]
    assert obj.data.polygons[0].material_index == 0
    set_flags(obj, 'remove_unused_material_slots')
    assert bpy.ops.object.amt_cleanup_execute('EXEC_DEFAULT') == {'FINISHED'}
    assert [slot.material for slot in obj.material_slots] == [material_a]


def test_join_rejects_shared_active_mesh_without_touching_other_objects():
    reset_scene()
    obj = make_mesh('SharedJoin')
    twin = obj.copy()
    twin.data = obj.data
    bpy.context.scene.collection.objects.link(twin)
    other = make_mesh('Part')
    make_active(obj, other)
    before = snapshot(obj), snapshot(twin), snapshot(other)
    assert_cancelled(bpy.ops.object.amt_merge_join, '共有')
    assert (snapshot(obj), snapshot(twin), snapshot(other)) == before
    assert other.name in bpy.data.objects


TESTS = (
    test_edited_shape_key_is_preserved_by_scan_and_cleanup,
    test_shared_mesh_rejects_all_cleanup_before_any_mutation,
    test_linked_object_and_linked_mesh_reject_before_partial_mutation,
    test_hidden_mesh_rejects_before_removing_attributes,
    test_effective_object_material_preserves_uv_and_color_references,
    test_live_driver_controls_survive_key_mesh_and_object_paths,
    test_indexed_driver_keeps_preceding_shape_key_indices,
    test_solidify_cleanup_rejects_before_other_categories_change,
    test_solidify_merge_preserves_slot_and_rim_materials,
    test_disabled_material_index_modifiers_are_also_protected,
    test_wireframe_cleanup_preserves_generated_materials_before_any_deletion,
    test_wireframe_merge_preserves_generated_material_indices,
    test_simple_slot_cleanup_and_merge_continue_to_work,
    test_join_rejects_shared_active_mesh_without_touching_other_objects,
)
for test in TESTS:
    test()
    print('PASS', test.__name__)
print('BLENDER_CLEANUP_RELEASE_SAFETY_OK')
