"""Run in an isolated Blender profile after installing/enabling the release ZIP."""
from pathlib import Path
import importlib
import bpy

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'bl_ext.alamo_test.io_alamo_tools'
assert MODULE in bpy.context.preferences.addons, 'Installed extension is not enabled'
addon = importlib.import_module(MODULE)
assert Path(addon.__file__).is_relative_to(ROOT / '.tools'), addon.__file__
assert bpy.app.version >= (5, 2, 0)
path = ROOT / 'tests' / 'output' / 'installed.alo'
path.parent.mkdir(parents=True, exist_ok=True)
# Factory startup cube already has UVs and a material.
assert bpy.ops.export.alo(filepath=str(path), exportAnimations=False) == {'FINISHED'}
assert getattr(bpy.ops, 'import').alo(filepath=str(path), importAnimations=False) == {'FINISHED'}
addon.unregister()
addon.register()
print('ALAMO_INSTALLED_EXTENSION_OK', bpy.app.version_string, addon.__file__)
