"""Run with blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py."""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Quaternion
import io_alamo_tools as addon
from io_alamo_tools import animation, export_ala, import_ala, utils, viewport

OUTPUT = ROOT / 'tests' / 'output'
OUTPUT.mkdir(parents=True, exist_ok=True)
IMPORT = getattr(bpy.ops, 'import')


def make_rig(name='Rig'):
    rig = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.collection.objects.link(rig)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    parent = rig.data.edit_bones.new('Base')
    parent.head, parent.tail = (0, 0, 0), (0, 1, 0)
    child = rig.data.edit_bones.new('Tip')
    child.head, child.tail = (0, 1, 0), (0, 2, 0)
    child.parent = parent
    child.EnableProxy = True
    child.ProxyName = 'test_effect'
    child.proxyIsHidden = True
    child.billboardMode.billboardMode = 'Face'
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.scene.ActiveSkeleton.skeletonEnum = rig.name
    return rig


def make_mesh(shader='MeshGloss.fx', rig=None):
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    obj.name = 'Hull'
    material = bpy.data.materials.new('HullMaterial')
    material.shaderList.shaderList = shader
    material.Diffuse = (0.25, 0.5, 0.75, 1)
    obj.data.materials.append(material)
    if rig:
        obj.vertex_groups.new(name='Base').add(list(range(8)), 1, 'REPLACE')
        obj.modifiers.new('Rig', 'ARMATURE').object = rig
    return obj


def make_action(rig, rotation='QUATERNION', name='Move'):
    rig.animation_data_create()
    action = bpy.data.actions.new(name)
    rig.animation_data.action = action
    rig.animation_data.action_slot = action.slots.new(id_type='OBJECT', name=rig.name)
    action.AnimationEndFrame = 4
    for frame in range(5):
        for i, pose in enumerate(rig.pose.bones):
            pose.rotation_mode = rotation
            pose.location = (frame * 0.13, 0, 0)
            # Partial component channels must still yield complete binary tracks.
            pose.keyframe_insert('location', index=0, frame=frame)
            angle = frame * 0.15 * (i + 1)
            if rotation == 'QUATERNION':
                pose.rotation_quaternion = Quaternion((0, 0, 1), angle)
                pose.keyframe_insert('rotation_quaternion', frame=frame)
            else:
                pose.rotation_euler = (0, 0, angle)
                pose.keyframe_insert('rotation_euler', index=2, frame=frame)
            pose.proxyIsHiddenAnimation = frame in (1, 3)
            pose.keyframe_insert('proxyIsHiddenAnimation', frame=frame)
    # Unrelated object channels must not crash path parsing or add bone tracks.
    rig.keyframe_insert('location', frame=0)
    bpy.context.scene.render.fps = 30
    bpy.context.scene.render.fps_base = 1.001
    return action


def pose_samples(rig):
    result = []
    for frame in range(5):
        bpy.context.scene.frame_set(frame)
        result.append([(p.matrix.copy(), p.proxyIsHiddenAnimation) for p in rig.pose.bones])
    return result


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        utils.setModeToObject()
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_registration_lifecycle(self):
        addon.unregister()
        self.assertFalse(hasattr(bpy.types.Scene, 'ActiveSkeleton'))
        self.assertFalse(hasattr(bpy.types.Material, 'shaderList'))
        self.assertFalse(hasattr(bpy.types.Scene, 'modelFileName'))
        addon.register()
        self.assertIsNone(utils.findArmature())

    def test_static_model_and_custom_normals(self):
        obj = make_mesh('MeshBumpColorize.fx')
        for poly in obj.data.polygons:
            poly.use_smooth = True
        # Shared smooth vertices have split normals at every face boundary.
        normals = [poly.normal.copy() for poly in obj.data.polygons for _ in poly.loop_indices]
        obj.data.normals_split_custom_set(normals)
        obj.Hidden = True
        obj.HasCollision = True
        path = OUTPUT / 'static.alo'
        before_meshes = len(bpy.data.meshes)
        self.assertEqual(bpy.ops.export.alo(filepath=str(path), exportAnimations=False), {'FINISHED'})
        self.assertEqual(len(bpy.data.meshes), before_meshes)
        self.assertEqual(len(obj.modifiers), 0)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        engine = bpy.context.scene.render.engine
        self.assertEqual(IMPORT.alo(filepath=str(path), importAnimations=False), {'FINISHED'})
        obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
        self.assertEqual(len(obj.data.polygons), 12)
        self.assertTrue(obj.Hidden and obj.HasCollision and obj.hide_get())
        self.assertEqual(bpy.context.scene.render.engine, engine)
        self.assertEqual(obj.active_material.shaderList.shaderList, 'MeshBumpColorize.fx')
        self.assertTrue(obj.active_material.node_tree.nodes.get('Material Output').inputs['Surface'].is_linked)
        for poly in obj.data.polygons:
            for loop in poly.loop_indices:
                self.assertGreater(obj.data.corner_normals[loop].vector.dot(poly.normal), 0.999)

    def test_rigged_model_and_animation_roundtrip(self):
        for rotation in ('QUATERNION', 'XYZ'):
            with self.subTest(rotation=rotation):
                self.setUp()
                rig = make_rig()
                make_mesh('RSkinGloss.fx', rig)
                action = make_action(rig, rotation)
                expected = pose_samples(rig)
                model = OUTPUT / ('rig_' + rotation + '.alo')
                clip = OUTPUT / ('rig_' + rotation + '_Move.ALA')
                bpy.context.scene.frame_set(2)
                old_slot = rig.animation_data.action_slot
                bpy.ops.export.alo(filepath=str(model), exportAnimations=True)
                self.assertEqual(rig.animation_data.action, action)
                self.assertEqual(rig.animation_data.action_slot, old_slot)
                self.assertEqual(bpy.context.scene.frame_current, 2)
                self.assertTrue(clip.exists())
                with clip.open('rb') as stream:
                    import_ala.file = stream
                    parsed = import_ala.read_next_chunk(str(clip))
                self.assertEqual(parsed.num_frames, 5)
                self.assertEqual(parsed.num_bones, 2)
                self.assertEqual(parsed.translation_block_size, 2)
                self.assertEqual(parsed.rotation_block_size, 2)
                bpy.ops.wm.read_factory_settings(use_empty=True)
                IMPORT.alo(filepath=model.as_posix(), importAnimations=True)
                rig = utils.findArmature()
                self.assertEqual(len(rig.data.bones), 2)
                self.assertEqual(rig.animation_data.action.name, 'Move')
                self.assertIsNotNone(rig.animation_data.action_slot)
                self.assertAlmostEqual(bpy.context.scene.render.fps / bpy.context.scene.render.fps_base, 30 / 1.001, places=4)
                for frame, (actual, wanted) in enumerate(zip(pose_samples(rig), expected)):
                    for bone, ((matrix, hidden), (target, target_hidden)) in enumerate(zip(actual, wanted)):
                        error = max(abs(matrix[r][c] - target[r][c]) for r in range(4) for c in range(4))
                        self.assertLess(error, 0.001, (rotation, frame, bone, matrix, target))
                        self.assertEqual(hidden, target_hidden)
                utils.setModeToObject()
                bpy.context.view_layer.objects.active = rig
                bpy.ops.object.mode_set(mode='EDIT')
                tip = rig.data.edit_bones['Tip']
                self.assertTrue(tip.EnableProxy and tip.proxyIsHidden)
                self.assertEqual(tip.ProxyName, 'TEST_EFFECT')
                self.assertEqual(tip.billboardMode.billboardMode, 'Face')
                utils.setModeToObject()

    def test_slot_isolation_and_escaped_bone_paths(self):
        rig = make_rig()
        rig.data.bones['Base'].name = 'Base"quoted'
        action = make_action(rig)
        original_slot = rig.animation_data.action_slot
        other = make_rig('OtherRig')
        other.animation_data_create()
        other.animation_data.action = action
        other.animation_data.action_slot = action.slots.new(id_type='OBJECT', name=other.name)
        other.pose.bones['Base'].keyframe_insert('scale', frame=0)
        self.assertEqual(len(list(animation.object_curves(other))), 3)
        self.assertEqual(animation.bone_tracks(rig), (['Base"quoted', 'Tip'], ['Base"quoted', 'Tip']))
        self.assertEqual(rig.animation_data.action_slot, original_slot)

    def test_missing_animation_does_not_write_file(self):
        path = OUTPUT / 'missing.ala'
        if path.exists():
            path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'Active Skeleton'):
            export_ala.AnimationExporter().exportAnimation(str(path))
        self.assertFalse(path.exists())

    def test_large_model_viewport_clipping_and_orbit_center(self):
        obj = make_mesh()
        obj.location = (12000, -3000, 4000)
        obj.scale = (2000, 1000, 500)
        bpy.context.view_layer.update()
        matrix = obj.matrix_world.copy()
        center, radius = viewport.model_bounds(bpy.context, [obj])
        self.assertTrue(viewport.frame_model(bpy.context, [obj]))
        area = viewport.viewport_areas(bpy.context)[0]
        space = area.spaces.active
        self.assertLess((space.region_3d.view_location - center).length, 0.001)
        self.assertGreater(space.region_3d.view_distance, radius)
        self.assertGreater(space.clip_end, space.region_3d.view_distance + radius * 10)
        self.assertLessEqual(space.clip_start, 0.101)
        self.assertEqual(obj.matrix_world, matrix)

    def test_viewport_ignores_hidden_meshes_and_proxy_bones(self):
        obj = make_mesh()
        hidden = make_mesh()
        hidden.location = (1e6, 0, 0)
        hidden.hide_set(True)
        rig = make_rig()
        rig.location = (-1e6, 0, 0)
        bpy.context.view_layer.update()
        bounds = viewport.model_bounds(bpy.context, [obj, hidden, rig])
        self.assertLess(bounds[0].length, 0.001)
        self.assertAlmostEqual(bounds[1], math.sqrt(3), places=4)
        obj.hide_set(True)
        self.assertFalse(viewport.frame_model(bpy.context, [obj, hidden, rig]))

    def test_small_model_near_clip_and_frame_button(self):
        obj = make_mesh()
        obj.scale = (0.01,) * 3
        bpy.context.view_layer.update()
        self.assertEqual(bpy.ops.view3d.alamo_frame_model(), {'FINISHED'})
        space = viewport.viewport_areas(bpy.context)[0].spaces.active
        self.assertLessEqual(space.clip_start, 0.00101)
        self.assertGreater(space.region_3d.view_distance, 0.01)

    def test_fast_preview_restores_settings_and_preserves_export(self):
        make_mesh()
        area = viewport.viewport_areas(bpy.context)[0]
        space = area.spaces.active
        space.shading.type = 'MATERIAL'
        space.overlay.show_overlays = True
        space.show_gizmo = True
        before = OUTPUT / 'preview_before.alo'
        after = OUTPUT / 'preview_after.alo'
        bpy.ops.export.alo(filepath=str(before), exportAnimations=False)
        self.assertTrue(viewport.set_fast_preview(bpy.context, True))
        self.assertTrue(viewport.is_fast_preview(area))
        self.assertEqual(space.shading.type, 'SOLID')
        self.assertFalse(space.overlay.show_overlays)
        self.assertFalse(space.show_gizmo)
        # Reapplying must not overwrite the saved original settings.
        viewport.set_fast_preview(bpy.context, True)
        bpy.ops.export.alo(filepath=str(after), exportAnimations=False)
        self.assertEqual(before.read_bytes(), after.read_bytes())
        self.assertTrue(viewport.set_fast_preview(bpy.context, False))
        self.assertEqual(space.shading.type, 'MATERIAL')
        self.assertTrue(space.overlay.show_overlays)
        self.assertTrue(space.show_gizmo)
        self.assertFalse(viewport.is_fast_preview(area))

    def test_fast_preview_restore_survives_save_reload(self):
        make_mesh()
        area = viewport.viewport_areas(bpy.context)[0]
        area.spaces.active.shading.type = 'WIREFRAME'
        area.spaces.active.overlay.show_overlays = True
        viewport.set_fast_preview(bpy.context, True)
        path = OUTPUT / 'fast_preview.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        bpy.ops.wm.open_mainfile(filepath=str(path))
        area = viewport.viewport_areas(bpy.context)[0]
        self.assertTrue(viewport.is_fast_preview(area))
        bpy.ops.view3d.alamo_fast_preview()
        self.assertEqual(area.spaces.active.shading.type, 'WIREFRAME')
        self.assertTrue(area.spaces.active.overlay.show_overlays)

    def test_fast_preview_import_option(self):
        make_mesh()
        path = OUTPUT / 'fast_import.alo'
        bpy.ops.export.alo(filepath=str(path), exportAnimations=False)
        self.setUp()
        IMPORT.alo(filepath=str(path), importAnimations=False, fastPreview=True)
        area = viewport.viewport_areas(bpy.context)[0]
        self.assertTrue(viewport.is_fast_preview(area))
        self.assertFalse(area.spaces.active.overlay.show_overlays)

    def test_failed_mesh_export_restores_modifiers_and_visibility(self):
        rig = make_rig()
        obj = make_mesh('RSkinGloss.fx', rig)
        obj.vertex_groups.clear()
        obj.hide_render = True
        before_meshes = len(bpy.data.meshes)
        with self.assertRaisesRegex(RuntimeError, 'Missing vertex group'):
            bpy.ops.export.alo(filepath=str(OUTPUT / 'invalid.alo'), exportAnimations=False)
        self.assertTrue(obj.hide_render)
        self.assertEqual(len(obj.modifiers), 1)
        self.assertEqual(obj.modifiers[0].object, rig)
        self.assertEqual(len(bpy.data.meshes), before_meshes)

    def test_shadow_import_preserves_existing_objects(self):
        shadow = make_mesh('MeshShadowVolume.fx')
        shadow.data.uv_layers.remove(shadow.data.uv_layers[0])
        path = OUTPUT / 'shadow.alo'
        bpy.ops.export.alo(filepath=str(path), exportAnimations=False)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        existing = make_mesh('MeshShadowVolume.fx')
        existing.hide_set(False)
        before_vertices = len(existing.data.vertices)
        IMPORT.alo(filepath=str(path), importAnimations=False)
        self.assertFalse(existing.hide_get())
        self.assertEqual(len(existing.data.vertices), before_vertices)
        imported = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o != existing]
        self.assertEqual(len(imported), 1)
        self.assertTrue(imported[0].hide_get())

    def test_multiple_slots_batch_export(self):
        rig = make_rig()
        make_mesh('RSkinGloss.fx', rig)
        action = make_action(rig, name='Shared')
        first = rig.animation_data.action_slot
        second = action.slots.new(id_type='OBJECT', name='Second')
        rig.animation_data.action_slot = second
        rig.pose.bones['Tip'].keyframe_insert('location', frame=0)
        rig.animation_data.action_slot = first
        # A camera/object action must not be exported as skeleton animation.
        unrelated = bpy.data.objects.new('Unrelated', None)
        bpy.context.collection.objects.link(unrelated)
        unrelated.keyframe_insert('location', frame=0)
        model = OUTPUT / 'batch.alo'
        bpy.ops.export.alo(filepath=str(model), exportAnimations=True)
        self.assertEqual(rig.animation_data.action_slot, first)
        for slot in (first, second):
            name = bpy.path.clean_name(action.name + '_' + slot.identifier)
            self.assertTrue((OUTPUT / ('batch_' + name + '.ALA')).exists())
        self.assertFalse((OUTPUT / 'batch_UnrelatedAction.ALA').exists())


if __name__ == '__main__':
    addon.register()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RoundTripTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    addon.unregister()
    if not result.wasSuccessful():
        raise RuntimeError('Blender integration tests failed')
    print('ALAMO_INTEGRATION_OK', bpy.app.version_string)
