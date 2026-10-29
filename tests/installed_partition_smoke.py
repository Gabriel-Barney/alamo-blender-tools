"""Validate the user's installed extension in a separate background process."""
import importlib
from pathlib import Path
import sys
import tomllib
import bpy

ROOT = Path(__file__).resolve().parents[1]
module = 'bl_ext.user_default.io_alamo_tools'
assert module in bpy.context.preferences.addons
addon = importlib.import_module(module)
installed = Path(addon.__file__).parent
assert tomllib.loads((installed / 'blender_manifest.toml').read_text())['version'] == '1.1.1'
for name in ('__init__.py', 'export_alo.py', 'mesh_partition.py', 'blender_manifest.toml'):
    assert (installed / name).read_bytes() == (ROOT / 'io_alamo_tools' / name).read_bytes(), name
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
mesh = bpy.data.meshes.new('Installed large mesh')
coords = []
faces = []
for i in range(21846):
    coords.extend([(i * 2, 0, 0), (i * 2 + 1, 0, 0), (i * 2, 1, 0)])
    faces.append((i * 3, i * 3 + 1, i * 3 + 2))
mesh.from_pydata(coords, [], faces)
mesh.uv_layers.new()
obj = bpy.data.objects.new('Installed large mesh', mesh)
bpy.context.collection.objects.link(obj)
mat = bpy.data.materials.new('Surface')
mat.shaderList.shaderList = 'MeshGloss.fx'
mesh.materials.append(mat)
path = ROOT / 'tests/output/installed_1.1.1_large.alo'
assert bpy.ops.export.alo(filepath=str(path), exportAnimations=False) == {'FINISHED'}
sys.path.insert(0, str(ROOT / 'tests'))
from alo_binary import read_model
model = read_model(path)
assert [s['vertex_count'] for s in model[0]['submeshes']] == [65535, 3]
assert sum(s['triangle_count'] for s in model[0]['submeshes']) == 21846
print('INSTALLED_1.1.1_LARGE_EXPORT_VERIFIED', installed)
