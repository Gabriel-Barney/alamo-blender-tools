"""Independent, read-only ALO decoder for checking actual exported bytes."""
import struct
from pathlib import Path


def chunks(data):
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError('Truncated chunk header')
        kind, size = struct.unpack_from('<II', data, offset)
        end = offset + 8 + (size & 0x7fffffff)
        if end > len(data):
            raise ValueError(f'Truncated chunk {kind:x}')
        yield kind, data[offset + 8:end], bool(size & 0x80000000)
        offset = end


def string(data):
    return data.rstrip(b'\0').decode('utf8')


def read_model(path):
    meshes = []
    for kind, payload, container in chunks(Path(path).read_bytes()):
        if kind != 0x400:
            continue
        mesh = {'name': None, 'submeshes': []}
        material = None
        for child, data, nested in chunks(payload):
            if child == 0x401:
                mesh['name'] = string(data)
            elif child == 0x402:
                mesh['submesh_count'] = struct.unpack_from('<I',data)[0]
                mesh['bounds'] = struct.unpack_from('<6f',data,4)
                mesh['hidden'], mesh['collision'] = struct.unpack_from('<II',data,32)
            elif child == 0x10100:
                material = {'parameters': {}}
                for tag, value, _ in chunks(data):
                    if tag == 0x10101:
                        material['shader'] = string(value)
                    else:
                        length = value[1]
                        name = string(value[2:2+length])
                        rest = value[2+length:]
                        if tag == 0x10105:
                            material['parameters'][name] = string(rest[2:])
                        else:
                            material['parameters'][name] = struct.unpack('<' + 'f'*((len(rest)-2)//4),rest[2:])
            elif child == 0x10000:
                sub = {'material': material, 'vertices': [], 'indices': [], 'mapping': []}
                for tag, value, _ in chunks(data):
                    if tag == 0x10001:
                        sub['vertex_count'],sub['triangle_count'] = struct.unpack_from('<II',value)
                    elif tag == 0x10002:
                        sub['format'] = string(value)
                    elif tag in (0x10005,0x10007):
                        stride = 144 if tag == 0x10007 else 128
                        assert len(value) % stride == 0
                        for pos in range(0,len(value),stride):
                            floats = struct.unpack_from('<24f',value,pos)
                            bones = struct.unpack_from('<4I',value,pos+(112 if stride==144 else 96))
                            weights = struct.unpack_from('<4f',value,pos+(128 if stride==144 else 112))
                            sub['vertices'].append({'position':floats[:3],'normal':floats[3:6],
                                'uvs':floats[6:14],'tangent':floats[14:17],'bitangent':floats[17:20],
                                'color':floats[20:24],'bones':bones,'weights':weights})
                    elif tag == 0x10004:
                        sub['indices'] = list(struct.unpack('<'+'H'*(len(value)//2),value))
                    elif tag == 0x10006:
                        sub['mapping'] = list(struct.unpack('<'+'I'*(len(value)//4),value))
                assert len(sub['vertices']) == sub['vertex_count']
                assert len(sub['indices']) == sub['triangle_count']*3
                assert all(i < sub['vertex_count'] for i in sub['indices'])
                mesh['submeshes'].append(sub)
        assert len(mesh['submeshes']) == mesh['submesh_count']
        meshes.append(mesh)
    return meshes


def read_bones(path):
    skeleton = next(data for kind,data,_ in chunks(Path(path).read_bytes()) if kind == 0x200)
    bones = []
    for kind,data,_ in chunks(skeleton):
        if kind != 0x202: continue
        bone = {}
        for tag,value,_ in chunks(data):
            if tag == 0x203: bone['name'] = string(value)
            elif tag in (0x205,0x206):
                bone['parent'],bone['visible'] = struct.unpack_from('<iI',value)
                bone['billboard'] = struct.unpack_from('<I',value,8)[0] if tag==0x206 else 0
                bone['matrix'] = struct.unpack_from('<12f',value,12 if tag==0x206 else 8)
        bones.append(bone)
    return bones
