"""Verify the actual user-installed extension in a disposable background scene."""
import importlib
import tomllib
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'bl_ext.user_default.io_alamo_tools'
assert MODULE in bpy.context.preferences.addons
addon = importlib.import_module(MODULE)
installed = Path(addon.__file__).parent
version = tomllib.loads((ROOT/'io_alamo_tools/blender_manifest.toml').read_text())['version']
assert tomllib.loads((installed/'blender_manifest.toml').read_text())['version'] == version
for source in (ROOT/'io_alamo_tools').glob('*.py'):
    assert source.read_bytes() == (installed/source.name).read_bytes(), source.name
assert hasattr(bpy.types, 'ALAMO_PT_export_validation')
# Factory-settings loading disables registered extensions. Clear only this
# disposable background scene, keeping the installed add-on actually enabled.
if bpy.context.object and bpy.context.object.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
for existing in list(bpy.context.scene.objects):
    bpy.data.objects.remove(existing, do_unlink=True)
bpy.context.scene.ActiveSkeleton.skeletonEnum = 'None'
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
mat = bpy.data.materials.new('Installed validation test')
mat.shaderList.shaderList = 'MeshGloss.fx'
obj.data.materials.append(mat)
assert bpy.ops.alamo.validate_export() == {'FINISHED'}
assert not any(i.severity == 'ERROR' for i in bpy.context.scene.alamo_validation.issues)
path = ROOT/'tests/output/installed_validation.alo'
assert bpy.ops.export.alo(filepath=str(path), exportAnimations=False) == {'FINISHED'}
original = path.read_bytes()
obj.data.materials.clear()
try:
    bpy.ops.export.alo(filepath=str(path), exportAnimations=False)
except RuntimeError as exc:
    assert 'Missing material' in str(exc)
else:
    raise AssertionError('Invalid export was not blocked')
assert path.read_bytes() == original
assert any(i.code == 'MATERIAL' for i in bpy.context.scene.alamo_validation.issues)
print('INSTALLED_VALIDATION_OK', version, installed)

# Also exercise the installed animation reader's failure path.
bpy.ops.object.armature_add()
rig = bpy.context.object
bpy.context.scene.ActiveSkeleton.skeletonEnum = rig.name
pose = rig.pose.bones[0]
pose.keyframe_insert('location', frame=0)
pose.location.x = 1
pose.keyframe_insert('location', frame=1)
action = rig.animation_data.action
action.AnimationEndFrame = 1
clip = ROOT/'tests/output/installed_reliability.ala'
assert bpy.ops.export.ala(filepath=str(clip)) == {'FINISHED'}
clip.write_bytes(clip.read_bytes()[:-1])
count = len(bpy.data.actions)
try:
    getattr(bpy.ops, 'import').ala(filepath=str(clip))
except RuntimeError as exc:
    assert 'Truncated' in str(exc)
else:
    raise AssertionError('Truncated ALA was accepted')
assert len(bpy.data.actions) == count and rig.animation_data.action == action
print('INSTALLED_RELIABILITY_OK', version)
