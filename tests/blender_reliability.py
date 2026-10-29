"""Malformed files, rollback, unknown records, atomic writes and motion continuity."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_smoke import *
from io_alamo_tools import fileio, foc_animation, import_alo
from alo_binary import chunks
from unittest.mock import patch
import struct


def chunk(tag, payload, container=False):
    return struct.pack('<II', tag, len(payload) | (0x80000000 if container else 0))+payload


def rewrite(data, tag, edit):
    out=b''
    for kind,payload,container in chunks(data):
        if container: payload=rewrite(payload,tag,edit)
        if kind==tag: payload=edit(payload)
        out+=chunk(kind,payload,container)
    return out


def field(data, tag, value):
    out=b'';offset=0
    while offset<len(data):
        kind,size=data[offset:offset+2]
        payload=data[offset+2:offset+2+size]
        if kind==tag:payload=value
        out+=bytes((kind,len(payload)))+payload
        offset+=size+2
    return out


def counts():
    return tuple(len(getattr(bpy.data,name)) for name in ('objects','collections','meshes','armatures','materials','actions','images'))


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        utils.setModeToObject();bpy.ops.wm.read_factory_settings(use_empty=True)

    def clip(self):
        rig=make_rig();action=make_action(rig)
        path=OUTPUT/'reliability_source.ala'
        export_ala.AnimationExporter().exportAnimation(str(path))
        return rig,action,path

    def model(self):
        obj=make_mesh();path=OUTPUT/'reliability_source.alo'
        bpy.ops.export.alo(filepath=str(path),exportAnimations=False)
        return obj,path

    def test_malformed_animations_leave_action_and_scene_intact(self):
        rig,action,path=self.clip();original=path.read_bytes();before=counts()
        cases=[original[:-1],b'not an animation',
            rewrite(original,0x1001,lambda p:field(p,2,struct.pack('<f',0))),
            rewrite(original,0x1001,lambda p:field(p,13,struct.pack('<I',3))),
            rewrite(original,0x1003,lambda p:field(p,16,struct.pack('<h',32764))),
            rewrite(original,0x1009,lambda p:p[:-2]),
            rewrite(original,0x1007,lambda p:b'')]
        for i,payload in enumerate(cases):
            with self.subTest(case=i):
                broken=OUTPUT/'reliability_bad.ala';broken.write_bytes(payload)
                with self.assertRaises(RuntimeError):import_ala.AnimationImporter().loadAnimation(str(broken))
                self.assertEqual(counts(),before)
                self.assertEqual(rig.animation_data.action,action)

    def test_unknown_ala_records_and_fields_skip_by_length(self):
        rig,action,path=self.clip()
        unknown=chunk(0x7fff,b'\x03\x10\0\0'+b'garbage')
        data=rewrite(path.read_bytes(),0x1000,lambda p:p+unknown)
        data=rewrite(data,0x1003,lambda p:p+bytes((127,4))+b'TEST')
        path.write_bytes(data)
        result=import_ala.AnimationImporter().loadAnimation(str(path))
        self.assertIsNotNone(result)
        self.assertEqual(result.AnimationEndFrame,4)

    def test_duplicate_bone_names_without_visibility_tracks(self):
        rig,action,path=self.clip()
        data=rewrite(path.read_bytes(),0x1003,lambda p:field(p,4,b'Base\0'))
        def remove_visibility(payload):
            return b''.join(chunk(t,p,c) for t,p,c in chunks(payload) if t!=0x1007)
        data=rewrite(data,0x1002,remove_visibility);path.write_bytes(data)
        rig.data.bones['Tip'].name='Base.001'
        parsed=foc_animation.read(path)
        self.assertEqual([b['name'] for b in parsed['bones']],['Base','Base.001'])
        self.assertIsNotNone(import_ala.AnimationImporter().loadAnimation(str(path)))

    def test_padded_visibility_and_unused_default_quaternions(self):
        rig,action,path=self.clip()
        data=rewrite(path.read_bytes(),0x1007,lambda p:p+b'\0\0\0')
        data=rewrite(data,0x1003,lambda p:field(p,17,bytes(8)))
        path.write_bytes(data)
        self.assertIsNotNone(import_ala.AnimationImporter().loadAnimation(str(path)))

    def test_mismatched_skeleton_is_reported_as_failure(self):
        rig,action,path=self.clip();rig.data.bones['Tip'].name='Different'
        before=counts()
        with self.assertRaisesRegex(RuntimeError,'do not match Active Skeleton'):
            import_ala.AnimationImporter().loadAnimation(str(path))
        self.assertEqual(counts(),before)
        self.assertEqual(rig.animation_data.action,action)

    def test_animation_runtime_failure_rolls_back_action_and_pose(self):
        rig,action,path=self.clip();bpy.context.scene.frame_set(2,subframe=0.25)
        slot=rig.animation_data.action_slot;before=counts();matrix=rig.pose.bones['Base'].matrix.copy()
        def fail(data):
            bpy.context.scene.frame_end=99
            bpy.context.scene.render.fps=12
            rig.pose.bones['Base'].rotation_mode='XYZ'
            rig.pose.bones['Base'].location=(50,50,50)
            raise RuntimeError('simulated curve creation failure')
        fps=bpy.context.scene.render.fps;end=bpy.context.scene.frame_end
        with patch.object(import_ala,'create_animation',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'simulated'):
                import_ala.AnimationImporter().loadAnimation(str(path))
        self.assertEqual(counts(),before)
        self.assertEqual(rig.animation_data.action,action)
        self.assertEqual(rig.animation_data.action_slot,slot)
        self.assertEqual(rig.pose.bones['Base'].rotation_mode,'QUATERNION')
        self.assertEqual(bpy.context.scene.frame_current,2)
        self.assertEqual(bpy.context.scene.frame_subframe,0.25)
        self.assertEqual(bpy.context.scene.render.fps,fps)
        self.assertEqual(bpy.context.scene.frame_end,end)
        self.assertLess((rig.pose.bones['Base'].matrix.translation-matrix.translation).length,1e-6)

    def test_truncated_model_rejected_before_scene_changes(self):
        obj,path=self.model();before=counts();path.write_bytes(path.read_bytes()[:-10])
        with self.assertRaisesRegex(RuntimeError,'Truncated'):
            IMPORT.alo(filepath=str(path),importAnimations=False)
        self.assertEqual(counts(),before)
        self.assertEqual(bpy.context.object,obj)

    def test_model_runtime_failure_removes_partial_import(self):
        obj,path=self.model();before=counts();selected=list(bpy.context.selected_objects)
        with patch.object(import_alo.viewport,'frame_model',side_effect=RuntimeError('simulated late import failure')):
            with self.assertRaisesRegex(RuntimeError,'simulated late'):
                IMPORT.alo(filepath=str(path),importAnimations=False)
        self.assertEqual(counts(),before)
        self.assertEqual(bpy.context.object,obj)
        self.assertEqual(list(bpy.context.selected_objects),selected)
        self.assertIsNone(utils.findArmature())

    def test_unknown_model_mesh_and_material_chunks_skip_safely(self):
        obj,path=self.model();unknown=chunk(0x7fff,b'\x00\x04\0\0'+b'not a real mesh')
        data=path.read_bytes()+unknown
        data=rewrite(data,0x10100,lambda p:p+unknown)
        data=rewrite(data,0x10000,lambda p:p+unknown)
        path.write_bytes(data)
        self.assertEqual(IMPORT.alo(filepath=str(path),importAnimations=False),{'FINISHED'})
        self.assertEqual(sum(o.type=='MESH' for o in bpy.context.scene.objects),2)

    def test_bad_auto_animation_does_not_discard_valid_model(self):
        obj,path=self.model()
        bad=path.with_name(path.stem+'_BROKEN.ala');bad.write_bytes(b'invalid')
        try:
            self.assertEqual(IMPORT.alo(filepath=str(path),importAnimations=True),{'FINISHED'})
            self.assertEqual(sum(o.type=='MESH' for o in bpy.context.scene.objects),2)
            self.assertFalse(list(bpy.data.actions))
        finally:bad.unlink()

    def test_animation_replace_failure_preserves_destination_and_state(self):
        rig,action,path=self.clip();path.write_bytes(b'previous-good-animation')
        bpy.context.scene.frame_set(3)
        before_selected=list(bpy.context.selected_objects);active=bpy.context.object
        with patch.object(fileio.os,'replace',side_effect=PermissionError('simulated file lock')):
            with self.assertRaisesRegex(PermissionError,'simulated file lock'):
                export_ala.AnimationExporter().exportAnimation(str(path))
        self.assertEqual(path.read_bytes(),b'previous-good-animation')
        self.assertFalse(list(OUTPUT.glob(path.name+'.*.tmp')))
        self.assertEqual(bpy.context.scene.frame_current,3)
        self.assertEqual(bpy.context.object,active)
        self.assertEqual(list(bpy.context.selected_objects),before_selected)

    def test_batch_sanitized_names_do_not_overwrite_each_other(self):
        rig=make_rig();make_mesh('RSkinGloss.fx',rig)
        first=make_action(rig,name='A/B')
        second=make_action(rig,name='A?B');second.AnimationEndFrame=2
        path=OUTPUT/'reliability_batch.alo'
        jobs=animation.export_jobs(rig,str(path))
        self.assertEqual(len(jobs),2)
        self.assertEqual(len({name.casefold() for name,_,_ in jobs}),2)
        self.assertEqual(bpy.ops.export.alo(filepath=str(path),exportAnimations=True),{'FINISHED'})
        self.assertNotEqual(Path(jobs[0][0]).read_bytes(),Path(jobs[1][0]).read_bytes())
        self.assertEqual(rig.animation_data.action,second)

    def test_quaternion_crossing_180_does_not_flip_between_frames(self):
        rig=make_rig();rig.animation_data_create()
        action=bpy.data.actions.new('Cross180');rig.animation_data.action=action
        rig.animation_data.action_slot=action.slots.new(id_type='OBJECT',name=rig.name)
        action.AnimationEndFrame=1
        pose=rig.pose.bones['Base'];pose.rotation_mode='QUATERNION'
        for frame,degrees in enumerate((170,190)):
            pose.rotation_quaternion=Quaternion((0,0,1),math.radians(degrees))
            pose.keyframe_insert('rotation_quaternion',frame=frame)
        path=OUTPUT/'reliability_cross180.ala'
        export_ala.AnimationExporter().exportAnimation(str(path))
        import_ala.AnimationImporter().loadAnimation(str(path))
        bpy.context.scene.frame_set(0,subframe=0.5)
        expected=Quaternion((0,0,1),math.pi)
        self.assertGreater(abs(pose.matrix.to_quaternion().dot(expected)),0.9999)


if __name__=='__main__':
    addon.register()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReliabilityTests))
    utils.setModeToObject();addon.unregister()
    if not result.wasSuccessful():raise RuntimeError('Reliability checks failed')
    print('ALAMO_RELIABILITY_OK',bpy.app.version_string)
