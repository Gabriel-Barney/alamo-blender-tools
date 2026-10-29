"""Binary fidelity and original feature coverage; run in background Blender."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_smoke import *
from io_alamo_tools import settings
from alo_binary import read_model
from collections import Counter


def export_file(name='fidelity.alo', **kwargs):
    path = OUTPUT / name
    bpy.ops.export.alo(filepath=str(path), exportAnimations=False, **kwargs)
    return path, read_model(path)


class FidelityTests(unittest.TestCase):
    def setUp(self):
        utils.setModeToObject()
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_all_proxy_visibility_bit_patterns(self):
        import io, struct
        data=import_ala.animation_data()
        packed=bytes(range(256))
        previous=getattr(import_ala,'file',None)
        try:
            import_ala.file=io.BytesIO(struct.pack('<I',len(packed))+packed)
            import_ala.read_visibility_data(data,'Proxy')
        finally:
            import_ala.file=previous
        expected=''.join(str((value>>bit)&1) for value in range(256) for bit in range(8))
        self.assertEqual(data.visibilityDict['Proxy'],expected)

    def test_every_original_shader_parameter(self):
        self.assertEqual(set(settings.material_parameter_dict),set(settings.vertex_format_dict))
        for shader, params in settings.material_parameter_dict.items():
            with self.subTest(shader=shader):
                self.setUp()
                rig=make_rig() if shader.startswith('RSkin') else None
                obj=make_mesh(shader,rig)
                mat=obj.active_material
                expected={}
                for index,param in enumerate(p for p in params if p):
                    value=getattr(mat,param)
                    if isinstance(value,str):
                        value=param.lower()+'.dds'
                    elif hasattr(value,'__len__'):
                        value=(-0.13,0.27,1.61,2.83)
                    else:
                        value=-300.17 + index*0.031
                    setattr(mat,param,value)
                    value=getattr(mat,param)
                    expected[param]=value if isinstance(value,str) else tuple(value) if hasattr(value,'__len__') else (value,)
                path,models=export_file()
                actual=models[0]['submeshes'][0]['material']
                self.assertEqual(actual['shader'],shader)
                self.assertEqual(actual['parameters'],expected)
                self.setUp()
                IMPORT.alo(filepath=str(path),importAnimations=False)
                mat=next(o.active_material for o in bpy.context.scene.objects if o.type=='MESH')
                self.assertEqual(mat.shaderList.shaderList,shader)
                for param,value in expected.items():
                    got=getattr(mat,param)
                    got=got if isinstance(got,str) else tuple(got) if hasattr(got,'__len__') else (got,)
                    self.assertEqual(got,value,(shader,param))

    def test_uv_color_normal_and_tangent_seams(self):
        mesh=bpy.data.meshes.new('Seams')
        mesh.from_pydata([(0,0,0),(2,0,0),(0,2,0),(2,2,0)],[],[(0,1,2),(1,3,2)])
        obj=bpy.data.objects.new('Seams',mesh);bpy.context.collection.objects.link(obj)
        mat=bpy.data.materials.new('Bump');mat.shaderList.shaderList='MeshBumpColorize.fx';mesh.materials.append(mat)
        for poly in mesh.polygons: poly.use_smooth=True
        normals=[(0,0,1)]*3+[(0,0.6,0.8)]*3
        mesh.normals_split_custom_set(normals)
        for channel in range(4):
            uv=mesh.uv_layers.new(name='UV'+str(channel))
            for loop in mesh.loops:
                co=mesh.vertices[loop.vertex_index].co
                uv.data[loop.index].uv=(co.x*0.5+channel*2,co.y*0.5+channel*0.3+(0.2 if loop.index>=3 and channel==1 else 0))
        mesh.uv_layers.active_index=0
        color=mesh.color_attributes.new(name='Paint',type='FLOAT_COLOR',domain='CORNER')
        for i,c in enumerate(color.data): c.color=(0.1+i*0.1,0.2,0.3,0.4+i*0.05)
        mesh.color_attributes.active_color=color
        bpy.context.view_layer.objects.active=obj
        path,models=export_file()
        sub=models[0]['submeshes'][0]
        self.assertEqual(sub['triangle_count'],2)
        self.assertEqual(sub['vertex_count'],6)
        for loop,idx in zip(mesh.loops,sub['indices']):
            vertex=sub['vertices'][idx]
            self.assertEqual(vertex['position'],tuple(mesh.vertices[loop.vertex_index].co))
            self.assertEqual(vertex['color'],tuple(color.data[loop.index].color))
            for channel in range(4):
                u,v=mesh.uv_layers[channel].data[loop.index].uv
                self.assertEqual(vertex['uvs'][channel*2:channel*2+2],(u,-v))
            self.assertGreater(sum(a*b for a,b in zip(vertex['normal'],normals[loop.index])),0.999)
            for field in ('tangent','bitangent'):
                self.assertAlmostEqual(sum(v*v for v in vertex[field]),1,places=5)
                self.assertAlmostEqual(sum(a*b for a,b in zip(vertex[field],vertex['normal'])),0,places=5)
        self.setUp();IMPORT.alo(filepath=str(path),importAnimations=False)
        imported=next(o.data for o in bpy.context.scene.objects if o.type=='MESH')
        self.assertEqual(len(imported.uv_layers),4)
        self.assertIsNotNone(imported.color_attributes.active_color)
        _,again=export_file('seams_again.alo')
        # Unchanged imports retain source shading even if Blender quantizes it.
        for a,b in zip(sub['vertices'],again[0]['submeshes'][0]['vertices']):
            for field in ('position','uvs','color','normal','tangent','bitangent'):
                self.assertEqual(a[field],b[field])
        from io_alamo_tools import quality
        self.assertEqual(imported['alamo_basis_fingerprint'],quality.basis_fingerprint(imported))
        imported.vertices[0].co.z += 0.5
        imported.update()
        self.assertNotEqual(imported['alamo_basis_fingerprint'],quality.basis_fingerprint(imported))
        _,edited=export_file('edited_seams.alo')
        self.assertNotEqual(edited[0]['submeshes'][0]['vertices'][0]['position'],sub['vertices'][0]['position'])

    def test_full_quality_subdivision_simplify_and_preview(self):
        obj=make_mesh()
        mod=obj.modifiers.new('Detail','SUBSURF');mod.levels=0;mod.render_levels=2
        bpy.context.scene.render.use_simplify=True
        bpy.context.scene.render.simplify_subdivision=0
        path,low=export_file('low.alo',fullQuality=False)
        _,full=export_file('full.alo')
        low_count=low[0]['submeshes'][0]['triangle_count']
        full_count=full[0]['submeshes'][0]['triangle_count']
        self.assertEqual(low_count,12)
        self.assertEqual(full_count,192)
        self.assertTrue(bpy.context.scene.render.use_simplify)
        self.assertEqual(mod.levels,0)
        viewport.set_fast_preview(bpy.context,True)
        fast,_=export_file('full_fast.alo')
        self.assertEqual((OUTPUT/'full.alo').read_bytes(),fast.read_bytes())
        self.assertEqual(len(obj.modifiers),1)

    def test_render_disabled_decimation_is_not_baked(self):
        obj=make_mesh()
        mod=obj.modifiers.new('Preview reduction','DECIMATE');mod.ratio=0.2;mod.show_render=False
        _,full=export_file()
        self.assertEqual(full[0]['submeshes'][0]['triangle_count'],12)
        self.assertTrue(mod.show_viewport)
        self.assertFalse(mod.show_render)

    def test_full_quality_rejects_lossy_blended_weights(self):
        rig=make_rig();obj=make_mesh('RSkinGloss.fx',rig)
        obj.vertex_groups['Base'].add([0],0.6,'REPLACE')
        obj.vertex_groups.new(name='Tip').add([0],0.4,'REPLACE')
        with self.assertRaisesRegex(RuntimeError,'cannot preserve blended weights'):
            export_file('blended.alo')
        _,model=export_file('legacy_weights.alo',fullQuality=False)
        self.assertEqual(model[0]['submeshes'][0]['triangle_count'],12)

    def test_multimaterial_skinning_mapping(self):
        rig=make_rig()
        mesh=bpy.data.meshes.new('TwoBones')
        mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0),(2,0,0),(3,0,0),(2,1,0)],[],[(0,1,2),(3,4,5)])
        obj=bpy.data.objects.new('TwoBones',mesh);bpy.context.collection.objects.link(obj)
        mesh.uv_layers.new()
        for shader in ('RSkinGloss.fx','RSkinAlpha.fx'):
            mat=bpy.data.materials.new(shader);mat.shaderList.shaderList=shader;mesh.materials.append(mat)
        mesh.polygons[1].material_index=1
        # Group zero is deliberately unused and does not name a bone.
        obj.vertex_groups.new(name='Unused')
        obj.vertex_groups.new(name='Base').add([0,1,2],1,'REPLACE')
        obj.vertex_groups.new(name='Tip').add([3,4,5],1,'REPLACE')
        obj.modifiers.new('Rig','ARMATURE').object=rig
        path,models=export_file()
        self.assertEqual([s['mapping'] for s in models[0]['submeshes']],[[1],[2]])
        self.setUp();IMPORT.alo(filepath=str(path),importAnimations=False)
        obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
        for v in obj.data.vertices:
            group=obj.vertex_groups[v.groups[0].group].name
            self.assertEqual(group,'Base' if v.co.x<2 else 'Tip')

    def test_hidden_collection_included_and_multi_link_not_duplicated(self):
        obj=make_mesh()
        group=bpy.data.collections.new('Hidden');bpy.context.scene.collection.children.link(group)
        group.objects.link(obj)
        _,models=export_file()
        self.assertEqual(len(models),1)
        for coll in list(obj.users_collection):
            if coll!=group:coll.objects.unlink(obj)
        group.hide_viewport=True
        _,models=export_file()
        self.assertEqual(len(models),1)
        self.assertTrue(group.hide_viewport)
        _,models=export_file('visible_only.alo',exportHiddenObjects=False)
        self.assertEqual(models,[])

    def test_excluded_collection_and_evaluated_bounds(self):
        obj=make_mesh()
        group=bpy.data.collections.new('Excluded');bpy.context.scene.collection.children.link(group)
        group.objects.link(obj)
        for coll in list(obj.users_collection):
            if coll!=group:coll.objects.unlink(obj)
        layer=bpy.context.view_layer.layer_collection.children[group.name]
        layer.exclude=True
        mod=obj.modifiers.new('Render extent','SOLIDIFY');mod.thickness=4
        mod.show_viewport=False;mod.show_render=True
        _,models=export_file()
        self.assertEqual(len(models),1)
        points=[v['position'] for s in models[0]['submeshes'] for v in s['vertices']]
        bounds=tuple(min(p[i] for p in points) for i in range(3))+tuple(max(p[i] for p in points) for i in range(3))
        self.assertEqual(models[0]['bounds'],bounds)
        self.assertTrue(layer.exclude)
        self.assertFalse(mod.show_viewport)

    def test_16bit_index_overflow_splits_without_reducing_geometry(self):
        mesh=bpy.data.meshes.new('TooMany')
        coords=[];faces=[]
        for i in range(21846):
            coords.extend([(i*2,0,0),(i*2+1,0,0),(i*2,1,0)])
            faces.append((i*3,i*3+1,i*3+2))
        mesh.from_pydata(coords,[],faces);mesh.uv_layers.new()
        obj=bpy.data.objects.new('TooMany',mesh);bpy.context.collection.objects.link(obj)
        mat=bpy.data.materials.new('Surface');mat.shaderList.shaderList='MeshGloss.fx';mesh.materials.append(mat)
        path=OUTPUT/'overflow.alo';path.write_bytes(b'existing')
        _, models = export_file(path.name)
        self.assertEqual(len(models), 1)
        subs = models[0]['submeshes']
        self.assertEqual([s['vertex_count'] for s in subs], [65535, 3])
        self.assertEqual(sum(s['triangle_count'] for s in subs), len(faces))
        self.assertEqual([v['position'] for s in subs for i in s['indices']
                          for v in [s['vertices'][i]]], coords)
        self.assertEqual(len(mesh.vertices),65538)
        self.assertEqual(len(obj.modifiers), 0)
        self.setUp()
        IMPORT.alo(filepath=str(path), importAnimations=False)
        self.assertEqual(sum(len(o.data.polygons) for o in bpy.context.scene.objects if o.type == 'MESH'), len(faces))

    def test_partition_preserves_seams_skinning_and_materials(self):
        from unittest.mock import patch
        from io_alamo_tools.mesh_partition import partition_triangles
        rig = make_rig()
        obj = make_mesh('RSkinBumpColorize.fx', rig)
        mesh = obj.data
        obj.vertex_groups['Base'].remove([4, 5, 6, 7])
        obj.vertex_groups.new(name='Tip').add([4, 5, 6, 7], 1, 'REPLACE')
        mat = obj.active_material.copy()
        mat.BaseTexture = 'second.dds'
        mesh.materials.append(mat)
        for face in mesh.polygons:
            face.material_index = face.index % 2
        for channel in range(1, 4):
            uv = mesh.uv_layers.new(name='UV' + str(channel))
            for i, data in enumerate(uv.data):
                data.uv = (channel + i * 0.125, channel - i * 0.25)
        color = mesh.color_attributes.new(name='Paint', type='FLOAT_COLOR', domain='CORNER')
        mesh.color_attributes.active_color = color
        for i, data in enumerate(color.data):
            data.color = (i * 0.03, 0.2, 0.3, 0.5)
        _, baseline = export_file('partition_baseline.alo')
        with patch('io_alamo_tools.export_alo.partition_triangles',
                   side_effect=lambda v, i, **kw: partition_triangles(v, i, max_vertices=9, **kw)):
            path, split = export_file('partition_attributes.alo')
        def corners(model):
            return [(sub['material'], sub['mapping'], sub['vertices'][i])
                    for sub in model[0]['submeshes'] for i in sub['indices']]
        self.assertGreater(len(split[0]['submeshes']), len(baseline[0]['submeshes']))
        self.assertEqual(corners(split), corners(baseline))
        self.assertEqual(len(mesh.vertices), 8)
        self.assertEqual(len(obj.modifiers), 1)

    def test_collision_partitions_use_local_triangle_ids(self):
        import struct
        from unittest.mock import patch
        from io_alamo_tools.mesh_partition import partition_triangles
        from alo_binary import chunks
        obj = make_mesh()
        obj.HasCollision = True
        with patch('io_alamo_tools.export_alo.partition_triangles',
                   side_effect=lambda v, i, **kw: partition_triangles(v, i, max_triangles=11)):
            path, model = export_file('partition_collision.alo')
        self.assertEqual([s['triangle_count'] for s in model[0]['submeshes']], [11, 1])
        mesh_chunk = next(data for kind, data, _ in chunks(path.read_bytes()) if kind == 0x400)
        sub_chunks = [data for kind, data, _ in chunks(mesh_chunk) if kind == 0x10000]
        for sub, data in zip(model[0]['submeshes'], sub_chunks):
            collision = next(payload for kind, payload, _ in chunks(data) if kind == 0x1200)
            mapping = next(payload for kind, payload, _ in chunks(collision) if kind == 0x1203)
            ids = struct.unpack('<' + 'h' * (len(mapping) // 2), mapping)
            self.assertEqual(sorted(ids), list(range(sub['triangle_count'])))

    def test_shadow_partitions_preserve_stitch_triangles(self):
        from unittest.mock import patch
        from io_alamo_tools.mesh_partition import partition_triangles
        make_mesh('MeshShadowVolume.fx')
        _, baseline = export_file('shadow_partition_baseline.alo')
        with patch('io_alamo_tools.export_alo.partition_triangles',
                   side_effect=lambda v, i, **kw: partition_triangles(v, i, max_vertices=9, **kw)):
            _, split = export_file('shadow_partition.alo')
        def corners(model):
            return [sub['vertices'][i] for sub in model[0]['submeshes'] for i in sub['indices']]
        self.assertGreater(len(split[0]['submeshes']), 1)
        self.assertEqual(corners(split), corners(baseline))

    def test_failed_export_keeps_existing_file_and_full_detail_settings(self):
        rig=make_rig();obj=make_mesh('RSkinGloss.fx',rig);obj.vertex_groups.clear()
        mod=obj.modifiers.new('Detail','SUBSURF');mod.levels=0;mod.render_levels=1
        bpy.context.scene.render.use_simplify=True
        path=OUTPUT/'existing.alo';path.write_bytes(b'original-good-file')
        with self.assertRaisesRegex(RuntimeError,'Missing vertex group'):
            export_file(path.name)
        self.assertEqual(path.read_bytes(),b'original-good-file')
        self.assertEqual(mod.levels,0)
        self.assertTrue(bpy.context.scene.render.use_simplify)
        self.assertFalse(list(OUTPUT.glob(path.name+'.*.alo.tmp')))

    def test_constraint_bone_and_attachment_import(self):
        rig=make_rig();obj=make_mesh()
        obj.location=(4,5,6)
        bpy.context.view_layer.update()
        self.assertEqual(bpy.ops.create.constraint_bone(),{'FINISHED'})
        self.assertEqual(tuple(obj.location),(0,0,0))
        self.assertEqual(obj.constraints[0].target,rig)
        path,_=export_file()
        self.setUp();IMPORT.alo(filepath=str(path),importAnimations=False)
        obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
        self.assertEqual(obj.constraints[0].subtarget,'Hull')
        original=utils.findArmature()
        IMPORT.alo(filepath=str(path),importAnimations=False,parentName='Tip')
        rigs=[o for o in bpy.context.scene.objects if o.type=='ARMATURE' and o!=original]
        self.assertEqual(len(rigs),1)
        self.assertEqual(rigs[0].parent,original)
        self.assertEqual(rigs[0].parent_bone,'Tip')

    def test_bone_flags_billboards_and_long_proxy(self):
        rig=make_rig()
        bpy.context.view_layer.objects.active=rig;bpy.ops.object.mode_set(mode='EDIT')
        for index,name in enumerate(settings.billboard_array):
            bone=rig.data.edit_bones.new('Billboard'+str(index));bone.tail=(0,1,0)
            bone.billboardMode.billboardMode=name;bone.Visible=False
            bone.EnableProxy=True;bone.ProxyName='EFFECT_'+str(index);bone.altDecreaseStayHidden=True;bone.proxyIsHidden=True
        bpy.ops.object.mode_set(mode='OBJECT')
        make_mesh()
        path,_=export_file();self.setUp();IMPORT.alo(filepath=str(path),importAnimations=False)
        rig=utils.findArmature();bpy.context.view_layer.objects.active=rig;bpy.ops.object.mode_set(mode='EDIT')
        for index,name in enumerate(settings.billboard_array):
            bone=rig.data.edit_bones['Billboard'+str(index)]
            self.assertEqual(bone.billboardMode.billboardMode,name)
            self.assertFalse(bone.Visible)
            self.assertTrue(bone.EnableProxy and bone.altDecreaseStayHidden and bone.proxyIsHidden)
            self.assertEqual(bone.ProxyName,'EFFECT_'+str(index))
        bpy.ops.object.mode_set(mode='OBJECT')


if __name__=='__main__':
    addon.register()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FidelityTests))
    utils.setModeToObject();addon.unregister()
    if not result.wasSuccessful():raise RuntimeError('Fidelity checks failed')
    print('ALAMO_FIDELITY_OK',bpy.app.version_string)
