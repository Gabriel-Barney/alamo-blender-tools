"""Optional local-asset audit. Pass -- model.alo [animation.ala]; never writes source files."""
import sys, json, math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_smoke import *
from alo_binary import read_model, read_bones, chunks
from ala_binary import compare as compare_animation_bytes
from mathutils.kdtree import KDTree


def audit(source, clip=None):
    sys.stdout.reconfigure(line_buffering=True)
    addon.register()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    IMPORT.alo(filepath=str(source),importAnimations=False)
    arm=utils.findArmature()
    output=OUTPUT/(source.stem+'_quality_audit.alo')
    bpy.ops.export.alo(filepath=str(output),exportAnimations=False)
    a,b=read_model(source),read_model(output)
    report={'source':str(source),'output':str(output),'meshes':len(a),
            'triangles_in':sum(s['triangle_count'] for m in a for s in m['submeshes']),
            'triangles_out':sum(s['triangle_count'] for m in b for s in m['submeshes']),
            'checks':[], 'shadow_position_error':0, 'max_error':dict(position=0,normal=0,uvs=0,color=0)}
    assert len(a)==len(b)
    assert report['triangles_in']==report['triangles_out']
    for original,exported in zip(a,b):
        assert original['name']==exported['name']
        assert original['hidden']==exported['hidden']
        assert original['collision']==exported['collision']
        assert len(original['submeshes'])==len(exported['submeshes'])
        for x,y in zip(original['submeshes'],exported['submeshes']):
            assert x['material']==y['material'],original['name']
            assert x['triangle_count']==y['triangle_count'],original['name']
            if 'ShadowVolume' in x['material']['shader']:
                # Shadow extrusion stitches are rebuilt from the welded manifold.
                original_positions={v['position'] for v in x['vertices']}
                exported_positions={v['position'] for v in y['vertices']}
                assert len(original_positions)==len(exported_positions)
                tree=KDTree(len(exported_positions))
                for i,point in enumerate(exported_positions):tree.insert(point,i)
                tree.balance()
                error=max(tree.find(point)[2] for point in original_positions)
                report['shadow_position_error']=max(report['shadow_position_error'],error)
                assert error<0.001,(original['name'],error)
                continue
            for i,j in zip(x['indices'],y['indices']):
                v,w=x['vertices'][i],y['vertices'][j]
                if x['mapping']:
                    assert y['mapping']
                    assert x['mapping'][v['bones'][0]]==y['mapping'][w['bones'][0]],original['name']
                for field in report['max_error']:
                    error=max(abs(k-l) for k,l in zip(v[field],w[field]))
                    report['max_error'][field]=max(report['max_error'][field],error)
            # All vertex attributes are checked at each indexed triangle corner.
    assert report['max_error']['position']<0.0001,report
    assert report['max_error']['uvs']<0.000001,report
    assert report['max_error']['color']<0.000001,report
    assert report['max_error']['normal']<0.001,report
    report['checks'] += ['mesh and triangle counts','all materials and texture references','indexed position/normal/UV/color fidelity','shadow positions and triangle counts']
    original_bones,exported_bones=read_bones(source),read_bones(output)
    assert len(original_bones)==len(exported_bones)
    rest_error=0
    for x,y in zip(original_bones,exported_bones):
        for field in ('name','parent','visible','billboard'): assert x[field]==y[field],(field,x,y)
        rest_error=max(rest_error,max(abs(a-b) for a,b in zip(x['matrix'],y['matrix'])))
    assert rest_error<0.001,rest_error
    report['bones']=len(original_bones)
    report['max_rest_matrix_error']=rest_error
    report['checks'].extend(['bone hierarchy/rest matrices/visibility/billboards','mesh flags and bone assignments','attachment/proxy chunks'])
    # Skeleton and connection bytes include hierarchy, rest matrices, billboards,
    # visibility and proxies. Float matrix recomposition may not be bit-identical.
    for name,tag in [('skeleton',0x200),('connections',0x600)]:
        first=next(p for t,p,c in chunks(source.read_bytes()) if t==tag)
        second=next(p for t,p,c in chunks(output.read_bytes()) if t==tag)
        report[name+'_byte_identical']=first==second
    assert report['connections_byte_identical']
    viewport.set_fast_preview(bpy.context,True)
    fast=OUTPUT/(source.stem+'_fast_audit.alo')
    bpy.ops.export.alo(filepath=str(fast),exportAnimations=False)
    assert output.read_bytes()==fast.read_bytes()
    report['checks'].append('Fast Preview byte-identical ALO')
    if clip is not None:
        print('Model checks passed; checking complete animation',flush=True)
        # Mesh fidelity was checked above. Animation comparison needs only bones;
        # avoid repeatedly deforming thousands of vertices while sampling poses.
        for obj in list(bpy.context.scene.objects):
            if obj.type=='MESH': bpy.data.objects.remove(obj,do_unlink=True)
        import_ala.AnimationImporter().loadAnimation(str(clip))
        print('Imported source animation',flush=True)
        utils.setModeToObject()
        action=utils.getCurrentAction()
        count=action.AnimationEndFrame+1
        frames=sorted({0,count//4,count//2,3*count//4,count-1})
        def sample():
            result=[]
            for f in frames:
                bpy.context.scene.frame_set(f)
                result.append([(p.matrix.copy(),p.proxyIsHiddenAnimation) for p in arm.pose.bones])
            return result
        expected=sample()
        dest=OUTPUT/(clip.stem+'_quality_audit.ala')
        export_ala.AnimationExporter().exportAnimation(str(dest))
        print('Exported animation',flush=True)
        report['animation_binary']=compare_animation_bytes(clip,dest)
        import_ala.AnimationImporter().loadAnimation(str(dest))
        actual=sample()
        max_translation=0; max_angle=0
        for a_frame,b_frame in zip(expected,actual):
            for (matrix,hidden),(other,hidden2) in zip(a_frame,b_frame):
                max_translation=max(max_translation,(matrix.translation-other.translation).length)
                max_angle=max(max_angle,matrix.to_quaternion().rotation_difference(other.to_quaternion()).angle)
                assert hidden==hidden2
        report['animation']={'source':str(clip),'frames':count,'bones':len(arm.data.bones),'sampled_frames':frames,'max_translation_error':max_translation,'max_angle_radians':max_angle}
        assert max_translation<0.2,report['animation']
        assert max_angle<0.002,report['animation']
    (OUTPUT/(source.stem+'_audit.json')).write_text(json.dumps(report,indent=2))
    print('GAME_ASSET_FIDELITY_OK',json.dumps(report,indent=2))
    utils.setModeToObject();addon.unregister()


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:]
    audit(Path(args[0]),Path(args[1]) if len(args)>1 else None)
