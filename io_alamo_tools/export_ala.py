import bpy
from . import settings, utils, animation, fileio

from bpy.props import (StringProperty,
                       BoolProperty,
                       IntProperty,
                       FloatProperty,
                       EnumProperty,
                       PointerProperty,
                       )
from bpy.types import (Panel,
                       Operator,
                       PropertyGroup,
                       )
import struct
import mathutils
import math
from math import pi
from mathutils import Vector
from bpy.props import *
from bpy_extras.io_utils import ExportHelper, ImportHelper
import sys
import os
import bmesh

def chunk_size(size):
            #high bit is used to determine if a chunk holds chunks or data
            #add 2147483648 instead of binary operation
            return size+2147483648

# Per-export pose samples: each scene frame is evaluated only once.
_sampled_transforms = {}


def calculateTranslationOffset(bone, armature, translationList):
    positions = [sample[0] for sample in _sampled_transforms[bone.name]]
    if bone.name not in translationList:
        return positions[0].copy()
    return mathutils.Vector(tuple(min(p[i] for p in positions) for i in range(3)))


def calculateTranslationScale(bone, offset, armature, translationList):
    if bone.name not in translationList:
        return mathutils.Vector((1,1,1))
    positions = [sample[0] for sample in _sampled_transforms[bone.name]]
    scale = tuple((max(abs(p[i]-offset[i]) for p in positions) or 1.0)/65535.0 for i in range(3))
    translationScaleDict[bone.name] = scale
    return scale


def create_translation_data(translationList, armature):
    chunk = bytearray()
    for frame in range(utils.getCurrentAction().AnimationEndFrame+1):
        for name in translationList:
            position = _sampled_transforms[name][frame][0]
            packed = [max(0,min(65535,round((position[i]-translationOffsetDict[name][i])/translationScaleDict[name][i]))) for i in range(3)]
            chunk.extend(struct.pack('<3H',*packed))
    return struct.pack('<II',0x100a,len(chunk))+chunk if chunk else b''


def create_rotation_data(rotationList, armature):
    chunk = bytearray()
    for frame in range(utils.getCurrentAction().AnimationEndFrame+1):
        for name in rotationList:
            rotation = _sampled_transforms[name][frame][1]
            chunk.extend(struct.pack('<4h',*(round(rotation[i]*32767) for i in (1,2,3,0))))
    return struct.pack('<II',0x1009,len(chunk))+chunk if chunk else b''

def create_animation():

    chunk = b''
    # get armature name
    armature = utils.findArmature()
    if armature == None:
        print("Warning: No armature found!")
        return b''

    _sampled_transforms.clear()
    for pose in armature.pose.bones:
        _sampled_transforms[pose.name] = []
    for frame in range(utils.getCurrentAction().AnimationEndFrame+1):
        bpy.context.scene.frame_set(frame)
        for pose in armature.pose.bones:
            matrix = pose.parent.matrix.inverted() @ pose.matrix if pose.parent else pose.matrix
            position,rotation,scale = matrix.decompose()
            _sampled_transforms[pose.name].append((position,rotation,pose.proxyIsHiddenAnimation))

    chunk += create_anim_info_chunk(armature)

    translationList, rotationList = animation.bone_tracks(armature)

    bpy.context.scene.frame_set(0)  # set scene to first frame, needed for default rotation/translation
    # add the bone data chunks for every bone
    for bone in armature.data.bones:
        if (bone.name != "Root"):
            chunk += create_bone_data(bone, translationList, rotationList, armature)

    chunk += create_translation_data(translationList, armature)  # add translation data chunk
    chunk += create_rotation_data(rotationList, armature)  # add rotation data chunk

    header = (b"\x00\x10\x00\00")
    header += struct.pack("<I", chunk_size(len(chunk))) # chunk size

    return header + chunk

def create_anim_info_chunk(armature):

    action = utils.getCurrentAction()
    animLength = action.AnimationEndFrame

    chunk = b'\x01\x04'  # mini chunk name and length
    chunk += struct.pack("<I", animLength + 1)  # number of animation frames

    chunk += b'\x02\x04'  # mini chunk length
    chunk += struct.pack("<f", bpy.context.scene.render.fps / bpy.context.scene.render.fps_base)

    chunk += b'\x03\x04'  # mini chunk length
    chunk += struct.pack("<I", sum(b.name != 'Root' for b in armature.data.bones))  # add number of bones

    translation, rotation = animation.bone_tracks(armature)
    locationTracks = len(translation) * 3
    rotationTracks = len(rotation) * 4

    # add rotationBlockSize
    chunk += b'\x0b\x04'  # mini chunk name and length
    chunk += struct.pack("<I", rotationTracks)

    # add translationBlockSize
    chunk += b'\x0c\x04'  # mini chunk name and length
    chunk += struct.pack("<I", locationTracks)

    # addScaleBlockSize, scale not supported set to 0
    chunk += b'\x0d\x04'  # mini chunk name and length
    chunk += struct.pack("<I", 0)

    chunkHeader = (b"\x01\x10\x00\00")  # chunk header
    chunkHeader += struct.pack("<I", len(chunk))  # add length

    return chunkHeader + chunk

def create_bone_data(bone, translationList, rotationList, armature):
    chunk = create_bone_animation_info_chunk(bone, translationList, rotationList, armature)
    header = (b"\x02\x10\x00\00")
    header += struct.pack("<I", chunk_size(len(chunk))) # add length
    return header + chunk
    # add support for step key track

def create_bone_animation_info_chunk(bone, translationList, rotationList, armature):

    # for animation data we have to go into pose mode
    utils.setModeToObject()

    # select the skeleton
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')  # enter pose mode
    pose = armature.pose.bones[bone.name]

    scene = bpy.context.scene
    scene.frame_set(0)
    translationOffset = calculateTranslationOffset(bone, armature, translationList)
    global translationOffsetDict
    translationOffsetDict[bone.name] = translationOffset
    translationScale = calculateTranslationScale(bone, translationOffset, armature, translationList)

    default_rotation = _sampled_transforms[bone.name][0][1]

    chunk = b'\x04'  # mini chunk name
    name = utils.clean_name(bone.name)
    chunk += struct.pack("<B", (len(name) + 1))  # size of name
    chunk += bytes(name, 'utf-8') + b"\x00"  # add bone name

    chunk += b'\x05\x04'  # mini chunk name and length

    # get the index of the current bone
    counter = 1 #start at because we ignore root bone
    for b in armature.data.bones:
        if (bone.name == b.name):
            index = counter
            break
        counter += 1
    chunk += struct.pack("<i", index)  # index of bone

    chunk += b'\x0a\x04'  # mini chunk name and length
    chunk += b'\x00\x00\00\00'  # unknown chunk

    chunk += b'\x06\x0c'  # mini chunk name and length
    # translation offset, is the location at the first frame, relative to the parent
    chunk += struct.pack("<f", translationOffset[0])
    chunk += struct.pack("<f", translationOffset[1])
    chunk += struct.pack("<f", translationOffset[2])

    chunk += b'\x07\x0c'  # mini chunk name and length
    # translation scale
    chunk += struct.pack("<f", translationScale[0])
    chunk += struct.pack("<f", translationScale[1])
    chunk += struct.pack("<f", translationScale[2])

    chunk += b'\x08\x0c'  # mini chunk name and length
    # scale offset, just 1 for now
    chunk += struct.pack("<f", 1)
    chunk += struct.pack("<f", 1)
    chunk += struct.pack("<f", 1)

    chunk += b'\x09\x0c'  # mini chunk name and length
    # scale scale, just 1 for now
    chunk += struct.pack("<f", 1)
    chunk += struct.pack("<f", 1)
    chunk += struct.pack("<f", 1)

    # add translation index
    chunk += b'\x0e\x02'  # mini chunk name and length
    if (bone.name in translationList):
        translationIndex = translationList.index(bone.name) * 3  # if bone is in location list use index in list as index
    else:
        translationIndex = -1  # if bone is not in location list use -1
    chunk += struct.pack("<h", translationIndex)

    # add scale index
    chunk += b'\x0f\x02'  # mini chunk name and length
    chunk += struct.pack("<h", -1)  # scale index, scale not implemented

    # add rotation index
    chunk += b'\x10\x02'  # mini chunk name and length
    if (bone.name in rotationList):
        rotationIndex = 4 * rotationList.index(
            bone.name)  # if bone is in rotation list use index in list as index
    else:
        rotationIndex = -1  # if bone is not in rotation list use -1

    chunk += struct.pack("<h", rotationIndex)

    # add default rotation
    chunk += b'\x11\x08'  # mini chunk name and length

    chunk += struct.pack("<h", int(default_rotation[1] * 32767))
    chunk += struct.pack("<h", int(default_rotation[2] * 32767))
    chunk += struct.pack("<h", int(default_rotation[3] * 32767))
    chunk += struct.pack("<h", int(default_rotation[0] * 32767))

    header = (b"\x03\x10\x00\00")
    header += struct.pack("<I", len(chunk))  # add length

    chunk = header + chunk

    visibility_chunk = create_visibility_chunk(armature, bone)

    return chunk + visibility_chunk

def create_visibility_chunk(armature, bone):
    path = armature.pose.bones[bone.name].path_from_id('proxyIsHiddenAnimation')
    dataExists = any(curve.data_path == path for curve in animation.object_curves(armature))

    if not dataExists:
        return b''

    binary = ''.join('0' if sample[2] else '1' for sample in _sampled_transforms[bone.name])

    while len(binary)%8 != 0:
        binary += '0'

    chunk = b''

    while len(binary) > 1:
        binaryReverse = binary[0:8][::-1] #file is little endian, reverse byte
        int_value = int(binaryReverse, 2)
        chunk += struct.pack('<B', int_value)
        binary = binary[8:]
    chunkHeader = b'\x07\x10\x00\00'
    chunkHeader += struct.pack('<I', len(chunk))
    return chunkHeader + chunk

class AnimationExporter():

    def exportAnimation(self, path):
        armature = utils.findArmature()
        if armature is None or utils.getCurrentAction() is None:
            raise RuntimeError('Select an Active Skeleton with an active animation action')
        if armature.animation_data.action_slot is None:
            raise RuntimeError('Select an action slot for the Active Skeleton')
        scene = bpy.context.scene
        old_frame = scene.frame_current
        old_subframe = scene.frame_subframe
        old_active = bpy.context.view_layer.objects.active
        old_mode = old_active.mode if old_active is not None else 'OBJECT'
        old_selected = list(bpy.context.selected_objects)
        global translationOffsetDict, translationScaleDict
        translationOffsetDict = {}
        translationScaleDict = {}
        try:
            data = create_animation()
            fileio.atomic_write(path, data)
        finally:
            _sampled_transforms.clear()
            utils.setModeToObject()
            for obj in bpy.context.selected_objects:
                obj.select_set(False)
            for obj in old_selected:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = old_active
            if old_active is not None and old_mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=old_mode)
            scene.frame_set(old_frame, subframe=old_subframe)

class ALA_Exporter(bpy.types.Operator):

    """ALA Exporter"""  # blender will use this as a tooltip for menu items and buttons.
    bl_idname = "export.ala"  # unique identifier for buttons and menu items to reference.
    bl_label = "Export ALA File"  # display name in the interface.
    bl_options = {'REGISTER', 'UNDO'}  # enable undo for the operator.
    bl_info = {
        "name": "ALA Exporter",
        "category": "Export",
    }
    filename_ext = ".ala"
    filter_glob : StringProperty(default="*.ala", options={'HIDDEN'})

    filepath : StringProperty(name="File Path", description="Filepath used for exporting the ALO file", maxlen=1024,
                              default="")


    def execute(self, context):

        path = self.properties.filepath

        exporter = AnimationExporter()
        try:
            exporter.exportAnimation(path)
        except (RuntimeError, OSError, ValueError, struct.error) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        return {'FINISHED'}  # this lets blender know the operator finished successfully.

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
