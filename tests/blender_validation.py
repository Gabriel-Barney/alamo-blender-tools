"""Preflight diagnostics, UI registration, state restoration and export gating."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_smoke import *
from io_alamo_tools import validation, quality
from unittest.mock import patch
from contextlib import contextmanager
import tempfile


def check(**kwargs):
    return validation.validate(bpy.context, **kwargs)[0]


def codes(issues, severity=None):
    return {i.code for i in issues if severity is None or i.severity == severity}


class ValidationTests(unittest.TestCase):
    def setUp(self):
        utils.setModeToObject()
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_collects_problems_across_objects_without_selection_changes(self):
        first=make_mesh();first.data.materials.clear()
        second=make_mesh();second.data.uv_layers.remove(second.data.uv_layers[0]);second.location.x=5
        selected=list(bpy.context.selected_objects);active=bpy.context.object
        issues=check()
        self.assertTrue({'MATERIAL','UV','TRANSFORM'} <= codes(issues))
        self.assertEqual(list(bpy.context.selected_objects),selected)
        self.assertEqual(bpy.context.object,active)
        self.assertTrue(all(i.fix for i in issues))

    def test_material_slots_and_uv_limit(self):
        obj=make_mesh();obj.data.materials.append(None)
        self.assertIn('MATERIAL_SLOT',codes(check(),'ERROR'))
        obj.data.materials.pop(index=1)
        for i in range(4):obj.data.uv_layers.new(name='UV'+str(i))
        self.assertIn('UV_LIMIT',codes(check(),'ERROR'))

    def test_weights_and_rig_diagnostics(self):
        rig=make_rig();obj=make_mesh('RSkinGloss.fx',rig)
        obj.vertex_groups.clear()
        self.assertIn('WEIGHTS_MISSING',codes(check(),'ERROR'))
        obj.vertex_groups.new(name='Typo').add(list(range(8)),1,'REPLACE')
        self.assertIn('WEIGHTS_UNKNOWN',codes(check(),'ERROR'))
        obj.vertex_groups.clear()
        obj.vertex_groups.new(name='Base').add(list(range(8)),0.6,'REPLACE')
        obj.vertex_groups.new(name='Tip').add([0],0.4,'REPLACE')
        self.assertIn('WEIGHTS_BLENDED',codes(check(),'ERROR'))
        self.assertIn('WEIGHTS_BLENDED',codes(check(full_quality=False),'WARNING'))
        obj.modifiers[0].object=None
        self.assertIn('RIG',codes(check(),'ERROR'))
        obj.modifiers.clear()
        self.assertIn('SKIN_RIG',codes(check(),'ERROR'))

    def test_bad_attachment_and_proxy_names(self):
        rig=make_rig();obj=make_mesh()
        constraint=obj.constraints.new('CHILD_OF');constraint.target=rig;constraint.subtarget='Typo'
        self.assertIn('ATTACHMENT',codes(check(),'ERROR'))
        bpy.context.view_layer.objects.active=rig;bpy.ops.object.mode_set(mode='EDIT')
        bone=rig.data.edit_bones['Tip'];bone.ProxyName='X'*255
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertIn('PROXY_NAME',codes(check(),'ERROR'))

    def test_texture_lookup_is_warning_and_directory_resolves_it(self):
        obj=make_mesh();obj.active_material.BaseTexture='ship.dds'
        self.assertIn('TEXTURE_MISSING',codes(check(),'WARNING'))
        self.assertFalse(codes(check(),'ERROR'))
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'ship.dds').write_bytes(b'texture-lookup-fixture')
            self.assertNotIn('TEXTURE_MISSING',codes(check(texture_folder=folder)))
        obj.active_material.BaseTexture='X'*255
        self.assertIn('TEXTURE_NAME',codes(check(),'ERROR'))

    def test_full_quality_checks_evaluated_shadow_not_only_base_mesh(self):
        obj=make_mesh('MeshShadowVolume.fx')
        modifier=obj.modifiers.new('Render tear','EDGE_SPLIT');modifier.show_viewport=False;modifier.show_render=True
        self.assertNotIn('EVALUATED_SHADOW',codes(check(full_quality=False)))
        self.assertIn('EVALUATED_SHADOW',codes(check(full_quality=True),'ERROR'))
        self.assertFalse(modifier.show_viewport)

    def test_evaluation_restores_hidden_collections_modifiers_and_simplify(self):
        rig=make_rig();obj=make_mesh('RSkinGloss.fx',rig)
        group=bpy.data.collections.new('Excluded');bpy.context.scene.collection.children.link(group)
        group.objects.link(obj)
        for coll in list(obj.users_collection):
            if coll!=group:coll.objects.unlink(obj)
        layer=bpy.context.view_layer.layer_collection.children[group.name]
        layer.exclude=True;group.hide_viewport=True;obj.hide_viewport=True
        modifier=obj.modifiers.new('Detail','SUBSURF');modifier.levels=0;modifier.render_levels=1
        bpy.context.scene.render.use_simplify=True
        count=len(bpy.data.meshes);selected=list(bpy.context.selected_objects)
        self.assertEqual(validation.validate(bpy.context,include_hidden=False)[1],0)
        issues,count_objects=validation.validate(bpy.context)
        self.assertEqual(count_objects,1)
        self.assertFalse(codes(issues,'ERROR'))
        self.assertTrue(layer.exclude and group.hide_viewport and obj.hide_viewport)
        self.assertEqual(modifier.levels,0)
        self.assertTrue(bpy.context.scene.render.use_simplify)
        self.assertEqual(len(bpy.data.meshes),count)
        self.assertEqual(obj.modifiers[0].object,rig)
        self.assertEqual(list(bpy.context.selected_objects),selected)

    def test_failed_evaluation_restores_resources(self):
        obj=make_mesh();modifier=obj.modifiers.new('Detail','SUBSURF');modifier.levels=0;modifier.render_levels=1
        count=len(bpy.data.meshes)
        with patch.object(validation,'_check_evaluated',side_effect=RuntimeError('fixture failure')):
            issues=check()
        self.assertIn('EVALUATION',codes(issues,'ERROR'))
        self.assertEqual(len(bpy.data.meshes),count)
        self.assertEqual(len(obj.modifiers),1)
        self.assertEqual(modifier.levels,0)

    def test_export_rechecks_after_clean_report_and_preserves_destination(self):
        obj=make_mesh()
        self.assertEqual(bpy.ops.alamo.validate_export(),{'FINISHED'})
        self.assertFalse(any(i.severity=='ERROR' for i in bpy.context.scene.alamo_validation.issues))
        obj.data.materials.clear()
        path=OUTPUT/'validation_existing.alo';path.write_bytes(b'known-good')
        with self.assertRaisesRegex(RuntimeError,'Missing material'):
            bpy.ops.export.alo(filepath=str(path),exportAnimations=False)
        self.assertEqual(path.read_bytes(),b'known-good')
        self.assertIn('MATERIAL',{i.code for i in bpy.context.scene.alamo_validation.issues})
        self.assertFalse(list(OUTPUT.glob(path.name+'.*.alo.tmp')))

    def test_warnings_do_not_block_export(self):
        obj=make_mesh();obj.location.x=4;obj.active_material.BaseTexture='missing.dds'
        path=OUTPUT/'validation_warning.alo'
        self.assertEqual(bpy.ops.export.alo(filepath=str(path),exportAnimations=False),{'FINISHED'})
        self.assertTrue(path.is_file())
        self.assertTrue({'TRANSFORM','TEXTURE_MISSING'} <= {i.code for i in bpy.context.scene.alamo_validation.issues})

    def test_edit_mode_diagnostic_and_pose_mode_support(self):
        obj=make_mesh();bpy.ops.object.mode_set(mode='EDIT')
        self.assertEqual(codes(check(),'ERROR'),{'MODE'})
        self.assertEqual(bpy.context.mode,'EDIT_MESH')
        bpy.ops.object.mode_set(mode='OBJECT')
        rig=make_rig();bpy.ops.object.mode_set(mode='POSE')
        self.assertNotIn('MODE',codes(check()))
        self.assertEqual(bpy.context.mode,'POSE')

    def test_animated_scale_only_warns_when_exporting_animations(self):
        rig=make_rig();make_mesh();make_action(rig)
        rig.pose.bones['Tip'].keyframe_insert('scale',frame=0)
        self.assertIn('ANIMATED_SCALE',codes(check(),'WARNING'))
        self.assertNotIn('ANIMATED_SCALE',codes(check(export_animations=False)))

    def test_report_selection_reveals_only_target_and_registration_lifecycle(self):
        obj=make_mesh();obj.active_material.BaseTexture='missing.dds';obj.hide_set(True)
        bpy.ops.alamo.validate_export()
        state=bpy.context.scene.alamo_validation
        state.active_issue=next(i for i,item in enumerate(state.issues) if item.code=='TEXTURE_MISSING')
        self.assertEqual(bpy.ops.alamo.select_validation_issue(),{'FINISHED'})
        self.assertEqual(bpy.context.object,obj);self.assertFalse(obj.hide_get())
        addon.unregister()
        self.assertFalse(hasattr(bpy.types.Scene,'alamo_validation'))
        addon.register()
        self.assertTrue(hasattr(bpy.types,'ALAMO_PT_export_validation'))

    def test_panel_draws_without_running_validation(self):
        from types import SimpleNamespace
        class Layout:
            def __init__(self):self.labels=[]
            def label(self,**kwargs):self.labels.append(kwargs.get('text',''))
            def prop(self,*args,**kwargs):pass
            def operator(self,*args,**kwargs):return SimpleNamespace()
            def template_list(self,*args,**kwargs):pass
            def box(self):return self
        make_mesh();bpy.ops.alamo.validate_export()
        layout=Layout()
        context=SimpleNamespace(scene=bpy.context.scene,region=SimpleNamespace(width=280))
        with patch.object(validation,'validate',side_effect=AssertionError('draw must not evaluate meshes')):
            validation.ALAMO_PT_export_validation.draw(SimpleNamespace(layout=layout),context)
        self.assertTrue(any('Last check' in text for text in layout.labels))
        self.assertIn('How to fix:',layout.labels)


if __name__=='__main__':
    addon.register()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ValidationTests))
    utils.setModeToObject();addon.unregister()
    if not result.wasSuccessful():raise RuntimeError('Validation checks failed')
    print('ALAMO_VALIDATION_OK',bpy.app.version_string)
