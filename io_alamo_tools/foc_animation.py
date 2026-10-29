"""Read FOC animation records before creating Blender data. Unknown chunks skip safely."""
from pathlib import Path
import math
import struct
from .fileio import chunks, mini_chunks


def _value(fields, tag, format):
    value = fields.get(tag)
    if value is None or len(value) != struct.calcsize(format):
        raise RuntimeError(f'Invalid ALA field 0x{tag:x}')
    return struct.unpack(format, value)


def read(path):
    roots = list(chunks(Path(path).read_bytes()))
    if len(roots) != 1 or roots[0][0] != 0x1000:
        raise RuntimeError('Invalid ALA animation container')
    records = list(chunks(roots[0][1]))
    headers = [payload for tag, payload, _ in records if tag == 0x1001]
    if len(headers) != 1:
        raise RuntimeError('ALA must contain one animation header')
    fields = mini_chunks(headers[0])
    if not {11, 12, 13} <= fields.keys():
        raise RuntimeError('Base EaW animation format not supported, use converter')
    frames = _value(fields, 1, '<I')[0]
    fps = _value(fields, 2, '<f')[0]
    count = _value(fields, 3, '<I')[0]
    rotations = _value(fields, 11, '<I')[0]
    translations = _value(fields, 12, '<I')[0]
    scales = _value(fields, 13, '<I')[0]
    if not frames or not math.isfinite(fps) or fps <= 0:
        raise RuntimeError('Invalid ALA frame count or frame rate')
    if rotations % 4 or translations % 3:
        raise RuntimeError('Invalid ALA animation block size')
    if scales:
        raise RuntimeError('ALA scale animation is unsupported; import cancelled to avoid losing motion')
    result = dict(frames=frames, fps=fps, rotation_stride=rotations//4,
                  translation_stride=translations//3, bones=[])
    buffers = {}
    names = set()
    for tag, payload, _ in records:
        if tag in (0x1009, 0x100a):
            if tag in buffers: raise RuntimeError('Duplicate ALA animation buffer')
            buffers[tag] = payload
        elif tag == 0x1002:
            parts = list(chunks(payload))
            infos = [p for t, p, _ in parts if t == 0x1003]
            vis = [p for t, p, _ in parts if t == 0x1007]
            if len(infos) != 1 or len(vis) > 1:
                raise RuntimeError('Invalid ALA bone records')
            fields = mini_chunks(infos[0])
            raw_name = fields.get(4)
            if not raw_name or raw_name[-1] != 0:
                raise RuntimeError('Invalid ALA bone name')
            try: name = bytes(raw_name[:-1]).decode('utf8')
            except UnicodeDecodeError as exc: raise RuntimeError('Invalid ALA bone-name encoding') from exc
            base = name
            index = 1
            while name in names:
                name = f'{base}.{index:03d}'
                index += 1
            names.add(name)
            bone = dict(name=name, index=_value(fields, 5, '<I')[0],
                        offset=_value(fields, 6, '<3f'), scale=_value(fields, 7, '<3f'),
                        translation_index=_value(fields, 14, '<h')[0],
                        rotation_index=_value(fields, 16, '<h')[0],
                        rotation=_value(fields, 17, '<4h'), visibility=None)
            scale_index = _value(fields, 15, '<h')[0]
            if scale_index != -1:
                raise RuntimeError('ALA scale animation is unsupported')
            for field, width, stride in (('translation_index', 3, translations), ('rotation_index', 4, rotations)):
                offset = bone[field]
                if offset != -1 and (offset < 0 or offset % width or offset+width > stride):
                    raise RuntimeError('ALA bone track index is outside its animation buffer')
            if not all(math.isfinite(value) for value in bone['offset']+bone['scale']):
                raise RuntimeError('Non-finite ALA translation values')
            if bone['rotation_index'] == -1 and not any(bone['rotation']):
                raise RuntimeError('Invalid zero ALA quaternion')
            if vis:
                needed = (frames+7)//8
                if len(vis[0]) < needed:
                    raise RuntimeError('ALA visibility buffer length does not match frame count')
                bone['visibility'] = ''.join(f'{value:08b}'[::-1] for value in vis[0][:needed])
            result['bones'].append(bone)
    if len(result['bones']) != count:
        raise RuntimeError('ALA bone count does not match bone records')
    for tag, stride, field, format in ((0x1009, rotations, 'rotation', '<4h'), (0x100a, translations, 'translation', '<3H')):
        buffer = buffers.get(tag, b'')
        if len(buffer) != frames*stride*2:
            raise RuntimeError('ALA animation buffer length does not match frame count')
        result[field] = list(struct.iter_unpack(format, buffer))
    if any(not any(q) for q in result['rotation']):
        raise RuntimeError('Invalid zero ALA quaternion')
    return result
