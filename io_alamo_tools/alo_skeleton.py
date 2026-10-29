"""Read both legacy and billboard-aware ALO bone records by chunk boundaries."""
import math
import struct
from .fileio import chunks, cstring


def read(payload):
    count = None
    bones = []
    for tag, data, _ in chunks(payload):
        if tag == 0x201:
            if count is not None or len(data) != 128:
                raise RuntimeError('Invalid ALO skeleton bone-count record')
            count = struct.unpack_from('<I', data)[0]
        elif tag == 0x202:
            bone = {}
            for kind, value, _ in chunks(data):
                if kind == 0x203:
                    if 'name' in bone: raise RuntimeError('Duplicate ALO bone name record')
                    bone['name'] = cstring(value, 'bone name')
                elif kind in (0x205, 0x206):
                    if 'matrix' in bone: raise RuntimeError('Duplicate ALO bone transform record')
                    offset = 12 if kind == 0x206 else 8
                    if len(value) != offset+48:
                        raise RuntimeError('Invalid ALO bone transform length')
                    parent, visible = struct.unpack_from('<iI', value)
                    billboard = struct.unpack_from('<I', value, 8)[0] if kind == 0x206 else 0
                    values = struct.unpack_from('<12f', value, offset)
                    if parent < -1 or parent >= len(bones):
                        raise RuntimeError('Invalid ALO bone parent index')
                    if billboard > 7:
                        raise RuntimeError('Unsupported ALO billboard mode: ' + str(billboard))
                    if not all(math.isfinite(v) for v in values):
                        raise RuntimeError('Non-finite ALO bone matrix')
                    bone.update(parent=parent, visible=visible, billboard=billboard,
                                matrix=(values[:4], values[4:8], values[8:12], (0, 0, 0, 1)))
            if not bone.get('name') or 'matrix' not in bone:
                raise RuntimeError('Incomplete ALO bone record')
            bones.append(bone)
    if count is None or count != len(bones) or not bones:
        raise RuntimeError('ALO skeleton bone count does not match its records')
    return bones
