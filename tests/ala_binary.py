"""Independent decoder/comparison for FOC translation, rotation and visibility."""
import math
import struct
from pathlib import Path
from alo_binary import chunks, string


def mini(data):
    offset=0
    while offset<len(data):
        tag,size=struct.unpack_from('<BB',data,offset)
        assert offset+2+size<=len(data)
        yield tag,data[offset+2:offset+2+size]
        offset+=2+size


def read_animation(path):
    payload=next(d for t,d,_ in chunks(Path(path).read_bytes()) if t==0x1000)
    result={'bones':[], 'rotation':b'', 'translation':b''}
    def records(data):
        for tag,value,container in chunks(data):
            if tag==0x1002:
                yield from records(value)
            else:
                yield tag,value,container
    for tag,data,_ in records(payload):
        if tag==0x1001:
            values=dict(mini(data))
            result['frames']=struct.unpack('<I',values[1])[0]
            result['fps']=struct.unpack('<f',values[2])[0]
            result['bone_count']=struct.unpack('<I',values[3])[0]
            result['rotation_stride']=struct.unpack('<I',values[11])[0]
            result['translation_stride']=struct.unpack('<I',values[12])[0]
            assert struct.unpack('<I',values[13])[0]==0,'Scale tracks unsupported'
        elif tag==0x1003:
            values=dict(mini(data))
            result['bones'].append(dict(name=string(values[4]),
                offset=struct.unpack('<3f',values[6]),scale=struct.unpack('<3f',values[7]),
                translation_index=struct.unpack('<h',values[14])[0],
                rotation_index=struct.unpack('<h',values[16])[0],
                default_rotation=struct.unpack('<4h',values[17]),visibility=None))
        elif tag==0x1007: result['bones'][-1]['visibility']=data
        elif tag==0x1009: result['rotation']=data
        elif tag==0x100a: result['translation']=data
    assert len(result['bones'])==result['bone_count']
    return result


def sample(clip,bone,frame):
    offset=bone['translation_index']
    packed=(0,0,0) if offset<0 else struct.unpack_from('<3H',clip['translation'],2*(frame*clip['translation_stride']+offset))
    position=tuple(a+b*c for a,b,c in zip(bone['offset'],bone['scale'],packed))
    offset=bone['rotation_index']
    rotation=bone['default_rotation'] if offset<0 else struct.unpack_from('<4h',clip['rotation'],2*(frame*clip['rotation_stride']+offset))
    length=math.sqrt(sum(q*q for q in rotation))
    rotation=tuple(q/length for q in rotation)
    bits=bone['visibility']
    visible=None if bits is None else bool(bits[frame//8] & (1<<(frame%8)))
    return position,rotation,visible


def compare(original,exported):
    a,b=read_animation(original),read_animation(exported)
    assert a['frames']==b['frames'] and abs(a['fps']-b['fps'])<0.0001
    assert [x['name'] for x in a['bones']]==[x['name'] for x in b['bones']]
    position_error=angle_error=0
    for x,y in zip(a['bones'],b['bones']):
        for frame in range(a['frames']):
            p,q,v=sample(a,x,frame);r,s,w=sample(b,y,frame)
            assert v==w,(x['name'],frame,'visibility')
            position_error=max(position_error,math.dist(p,r))
            angle_error=max(angle_error,2*math.acos(min(1,abs(sum(i*j for i,j in zip(q,s))))))
    result=dict(frames=a['frames'],bones=len(a['bones']),fps=a['fps'],all_frames_checked=True,
        max_translation_error=position_error,max_angle_radians=angle_error)
    assert position_error<0.2,result
    assert angle_error<0.002,result
    return result


if __name__=='__main__':
    import sys,json
    print(json.dumps(compare(*sys.argv[1:3]),indent=2))
