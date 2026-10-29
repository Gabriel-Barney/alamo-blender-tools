"""Legacy model records, indexed attachments, strings and malformed geometry."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_reliability import chunk, rewrite, field, counts
from blender_smoke import *
from alo_binary import chunks, read_model
import struct


class ModelCompatibilityTests(unittest.TestCase):
    def setUp(self):
        utils.setModeToObject();bpy.ops.wm.read_factory_settings(use_empty=True)

    def fixture(self):
        rig=make_rig();obj=make_mesh()
        constraint=obj.constraints.new('CHILD_OF');constraint.target=rig;constraint.subtarget='Tip'
        path=OUTPUT/'model_compat.alo'
        bpy.ops.export.alo(filepath=str(path),exportAnimations=False)
        return rig,obj,path

    def load(self,path):
        existing=set(bpy.context.scene.objects)
        IMPORT.alo(filepath=str(path),importAnimations=False)
        added=set(bpy.context.scene.objects)-existing
        return next(o for o in added if o.type=='ARMATURE'),next(o for o in added if o.type=='MESH')

    def test_legacy_bones_without_billboard_field(self):
        rig,obj,path=self.fixture()
        def legacy(data):
            return b''.join(chunk(0x205,p[:8]+p[12:]) if t==0x206 else chunk(t,p,c) for t,p,c in chunks(data))
        path.write_bytes(rewrite(path.read_bytes(),0x202,legacy))
        imported,mesh=self.load(path)
        self.assertEqual(mesh.constraints[0].subtarget,'Tip')
        self.assertLess((rig.data.bones['Tip'].matrix_local.translation-imported.data.bones['Tip'].matrix_local.translation).length,1e-6)
        bpy.context.view_layer.objects.active=imported;bpy.ops.object.mode_set(mode='EDIT')
        self.assertEqual(imported.data.edit_bones['Tip'].billboardMode.billboardMode,'Disable')

    def test_unknown_skeleton_and_bone_records(self):
        rig,obj,path=self.fixture();extra=chunk(0x2ee,b'extra metadata')
        data=rewrite(path.read_bytes(),0x202,lambda p:extra+p)
        data=rewrite(data,0x200,lambda p:p+extra)
        path.write_bytes(data)
        imported,mesh=self.load(path)
        self.assertEqual(set(imported.data.bones.keys()),{'Base','Tip'})

    def test_duplicate_bone_parent_uses_file_index(self):
        rig=make_rig();rig.data.bones['Tip'].name='Base.001'
        bpy.context.view_layer.objects.active=rig;bpy.ops.object.mode_set(mode='EDIT')
        bone=rig.data.edit_bones.new('Child');bone.parent=rig.data.edit_bones['Base.001'];bone.head=(0,2,0);bone.tail=(0,3,0)
        bpy.ops.object.mode_set(mode='OBJECT');make_mesh()
        path=OUTPUT/'duplicate_bones.alo';bpy.ops.export.alo(filepath=str(path),exportAnimations=False)
        imported,mesh=self.load(path)
        self.assertEqual(imported.data.bones['Child'].parent.name,'Base.001')

    def test_existing_object_is_not_used_for_imported_attachment(self):
        rig,obj,path=self.fixture()
        name=read_model(path)[0]['name']
        unrelated=bpy.data.objects.new(name+'.001',bpy.data.meshes.new('Unrelated mesh'))
        bpy.context.collection.objects.link(unrelated)
        imported,mesh=self.load(path)
        self.assertNotEqual(mesh.name,mesh.data.name)
        self.assertEqual(len(unrelated.constraints),0)
        self.assertEqual(mesh.constraints[0].target,imported)
        self.assertEqual(mesh.constraints[0].subtarget,'Tip')

    def test_skipped_light_does_not_shift_mesh_connection(self):
        rig,obj,path=self.fixture()
        data=rewrite(path.read_bytes(),0x602,lambda p:field(p,2,struct.pack('<I',1)))
        data=rewrite(data,0x601,lambda p:field(p,1,struct.pack('<I',2)))
        light_connection=chunk(0x602,b'\x02\x04'+struct.pack('<I',0)+b'\x03\x04'+struct.pack('<I',0))
        def connections(payload):
            return b''.join(chunk(t,p,c)+(light_connection if t==0x601 else b'') for t,p,c in chunks(payload))
        data=rewrite(data,0x600,connections)
        out=b''
        for tag,payload,container in chunks(data):
            if tag==0x400:out+=chunk(0x1300,b'ignored light')
            out+=chunk(tag,payload,container)
        path.write_bytes(out)
        imported,mesh=self.load(path)
        self.assertEqual(mesh.constraints[0].subtarget,'Tip')

    def test_full_length_proxy_and_unknown_proxy_fields(self):
        rig,obj,path=self.fixture()
        bpy.context.view_layer.objects.active=rig;bpy.ops.object.mode_set(mode='EDIT')
        proxy='FX_'+('X'*251)
        rig.data.edit_bones['Tip'].ProxyName=proxy
        rig.data.edit_bones['Tip'].altDecreaseStayHidden=True
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.export.alo(filepath=str(path),exportAnimations=False)
        path.write_bytes(rewrite(path.read_bytes(),0x603,lambda p:p+bytes((127,3))+b'abc'))
        imported,mesh=self.load(path)
        bpy.context.view_layer.objects.active=imported;bpy.ops.object.mode_set(mode='EDIT')
        self.assertEqual(imported.data.edit_bones['Tip'].ProxyName,proxy)
        self.assertTrue(imported.data.edit_bones['Tip'].altDecreaseStayHidden)

    def test_texture_names_are_decoded_and_extensions_converted_correctly(self):
        for source,expected in [('hull_diffuse','hull_diffuse.dds'),('hull.jpeg','hull.dds'),(r'Textures\Hull.dds',r'Textures\Hull.dds')]:
            with self.subTest(source=source):
                self.setUp();obj=make_mesh();obj.active_material.BaseTexture=source
                path=OUTPUT/'texture_names.alo';bpy.ops.export.alo(filepath=str(path),exportAnimations=False)
                imported,mesh=self.load(path)
                self.assertEqual(mesh.active_material.BaseTexture,expected)

    def test_empty_submeshes_do_not_shift_material_assignment(self):
        rig,obj,path=self.fixture()
        def prepend_empty(payload):
            records=list(chunks(payload))
            material=next(chunk(t,p,c) for t,p,c in records if t==0x10100)
            data=next(chunk(t,p,c) for t,p,c in records if t==0x10000)
            data=rewrite(data,0x10001,lambda p:bytes(8)+p[8:])
            data=rewrite(data,0x10007,lambda p:b'')
            data=rewrite(data,0x10004,lambda p:b'')
            out=b''
            for t,p,c in records:
                if t==0x402:p=struct.pack('<I',3)+p[4:]
                out+=chunk(t,p,c)
                if t==0x402:out+=(material+data)*2
            return out
        path.write_bytes(rewrite(path.read_bytes(),0x400,prepend_empty))
        imported,mesh=self.load(path)
        self.assertEqual(len(mesh.data.materials),3)
        self.assertEqual({p.material_index for p in mesh.data.polygons},{2})
        self.assertEqual(len(mesh.data.polygons),12)

    def test_bad_buffer_counts_indices_and_values_roll_back(self):
        rig,obj,path=self.fixture();original=path.read_bytes();before=counts()
        cases=[
            rewrite(original,0x10001,lambda p:struct.pack('<I',9999)+p[4:]),
            rewrite(original,0x10004,lambda p:struct.pack('<H',65535)+p[2:]),
            rewrite(original,0x10007,lambda p:struct.pack('<f',float('nan'))+p[4:]),
            rewrite(original,0x206,lambda p:struct.pack('<i',9999)+p[4:]),
            rewrite(original,0x602,lambda p:field(p,3,struct.pack('<I',9999))),
        ]
        for index,data in enumerate(cases):
            with self.subTest(case=index):
                path.write_bytes(data)
                with self.assertRaises(RuntimeError):self.load(path)
                self.assertEqual(counts(),before)

    def test_legacy_vertex_buffer_stride(self):
        rig,obj,path=self.fixture()
        def old_vertices(payload):
            out=b''
            for tag,data,container in chunks(payload):
                if tag==0x10007:
                    data=b''.join(data[i:i+96]+data[i+112:i+144] for i in range(0,len(data),144))
                    tag=0x10005
                out+=chunk(tag,data,container)
            return out
        path.write_bytes(rewrite(path.read_bytes(),0x10000,old_vertices))
        imported,mesh=self.load(path)
        self.assertEqual(len(mesh.data.polygons),12)


if __name__=='__main__':
    addon.register()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ModelCompatibilityTests))
    utils.setModeToObject();addon.unregister()
    if not result.wasSuccessful():raise RuntimeError('Model compatibility checks failed')
    print('ALAMO_MODEL_COMPATIBILITY_OK',bpy.app.version_string)
