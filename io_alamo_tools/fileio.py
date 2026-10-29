"""Bounded binary records, atomic output and failed-import rollback."""
from contextlib import contextmanager
from pathlib import Path
import os
import struct
import tempfile


def chunks(data):
    data = memoryview(data)
    offset = 0
    while offset < len(data):
        if len(data)-offset < 8:
            raise RuntimeError('Truncated ALAMO chunk header')
        tag, size = struct.unpack_from('<II', data, offset)
        end = offset+8+(size & 0x7fffffff)
        if end > len(data):
            raise RuntimeError(f'Truncated ALAMO chunk 0x{tag:x}')
        yield tag, data[offset+8:end], bool(size & 0x80000000)
        offset = end


def mini_chunks(data):
    data = memoryview(data)
    offset = 0
    result = {}
    while offset < len(data):
        if len(data)-offset < 2:
            raise RuntimeError('Truncated ALAMO mini-chunk header')
        tag, size = data[offset:offset+2]
        end = offset+2+size
        if end > len(data):
            raise RuntimeError('Truncated ALAMO mini-chunk payload')
        if tag in result:
            raise RuntimeError(f'Duplicate ALAMO mini-chunk 0x{tag:x}')
        result[tag] = data[offset+2:end]
        offset = end
    return result


def cstring(data, label='ALAMO string'):
    data = bytes(data)
    if not data or data[-1] != 0:
        raise RuntimeError('Missing null terminator in ' + label)
    try:
        return data.split(b'\0', 1)[0].decode('utf8')
    except UnicodeDecodeError as exc:
        raise RuntimeError('Invalid UTF-8 in ' + label) from exc


def uint_field(fields, tag, label):
    value = fields.get(tag)
    if value is None or len(value) != 4:
        raise RuntimeError('Invalid ' + label + ' field')
    return struct.unpack('<I', value)[0]


def checked_alo(path):
    data = Path(path).read_bytes()
    roots = list(chunks(data))
    if not roots or roots[0][0] != 0x200 or sum(tag == 0x200 for tag, _, _ in roots) != 1:
        raise RuntimeError('Invalid ALO: expected one leading skeleton chunk')
    def walk(records, depth=0):
        if depth > 64:
            raise RuntimeError('ALAMO chunk nesting is too deep')
        for tag, payload, container in records:
            if container:
                walk(chunks(payload), depth+1)
    walk(roots)


def atomic_write(path, data):
    target = Path(path).absolute()
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.', suffix='.tmp', delete=False) as stream:
            temp = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        temp = None
    finally:
        if temp is not None:
            os.unlink(temp)


@contextmanager
def import_transaction(context, rig=None):
    """Remove newly created IDs and restore user state only if import fails."""
    import bpy
    from . import utils
    groups = ('objects', 'collections', 'meshes', 'armatures', 'materials', 'actions', 'images')
    before = {name: set(getattr(bpy.data, name)) for name in groups}
    scene = context.scene
    scene_state = (scene.frame_start, scene.frame_end, scene.frame_current, scene.frame_subframe,
                   scene.render.fps, scene.render.fps_base, scene.ActiveSkeleton.skeletonEnum, scene.modelFileName)
    active = context.view_layer.objects.active
    mode = active.mode if active else 'OBJECT'
    selected = list(context.selected_objects)
    had_animation = bool(rig and rig.animation_data)
    old_action = rig.animation_data.action if had_animation else None
    old_slot = rig.animation_data.action_slot if had_animation else None
    poses = [(p, p.rotation_mode, p.matrix_basis.copy(), p.proxyIsHiddenAnimation) for p in rig.pose.bones] if rig else []
    try:
        yield
    except Exception:
        utils.setModeToObject()
        if rig and rig.animation_data:
            if had_animation:
                rig.animation_data.action = old_action
                if old_action: rig.animation_data.action_slot = old_slot
            else:
                rig.animation_data_clear()
        for name in groups:
            collection = getattr(bpy.data, name)
            for item in list(collection):
                if item not in before[name]:
                    collection.remove(item, do_unlink=True)
        (scene.frame_start, scene.frame_end, frame, subframe, scene.render.fps,
         scene.render.fps_base, scene.ActiveSkeleton.skeletonEnum, scene.modelFileName) = scene_state
        for pose, rotation_mode, basis, hidden in poses:
            pose.rotation_mode = rotation_mode
            pose.matrix_basis = basis
            pose.proxyIsHiddenAnimation = hidden
        scene.frame_set(frame, subframe=subframe)
        for obj in context.selected_objects: obj.select_set(False)
        for obj in selected: obj.select_set(True)
        context.view_layer.objects.active = active
        if active and mode != 'OBJECT': bpy.ops.object.mode_set(mode=mode)
        raise
