import bpy
from . import settings, utils, fileio, foc_animation

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
import binascii

class animation_data():
        def __init__(self):

            self.num_frames = 0
            self.fps = 0
            self.num_bones = 0

            self.bone_name_list = []
            self.bone_index = []

            self.translation_offset = []
            self.translation_index = []
            self.translation_data = []
            self.translation_block_size = 0
            self.translation_scale = []
            self.translation_data = []

            self.scaleIndex = []
            self.scale_offset = []

            self.rotation_index = []
            self.default_rotation = []
            self.rotation_block_size = 0
            self.rotation_data = []

            self.visibilityAnimation = []
            self.visibilityDict = {}

def read_visibility_data(data, bone_Name):
    length = struct.unpack("<I",file.read(4))[0]

    packed = file.read(length)
    binary = ''.join(f'{value:08b}'[::-1] for value in packed)

    if bone_Name in data.visibilityDict:
        bone_Name += ".001"
        counter = 2
        while bone_Name in data.visibilityDict:
            if counter < 10:
                bone_Name = bone_Name[0:len(bone_Name)-4] + ".00" + str(counter)
            elif counter < 100:
                bone_Name = bone_Name[0:len(bone_Name)-4] +".0" + str(counter)
            else:
                bone_Name = bone_Name[0:len(bone_Name)-4] + "." + str(counter)
            counter += 1
    data.visibilityDict[bone_Name] = binary

def read_next_chunk(path):
    parsed = foc_animation.read(path)
    data = animation_data()
    data.num_frames, data.fps = parsed['frames'], parsed['fps']
    data.num_bones = len(parsed['bones'])
    data.rotation_block_size = parsed['rotation_stride']
    data.translation_block_size = parsed['translation_stride']
    for bone in parsed['bones']:
        data.bone_name_list.append(bone['name'])
        data.bone_index.append(bone['index'])
        data.translation_offset.append(Vector(bone['offset']))
        data.translation_scale.append(Vector(bone['scale']))
        data.translation_index.append(bone['translation_index'])
        offset = bone['rotation_index']
        data.rotation_index.append(offset//4 if offset >= 0 else -1)
        x,y,z,w = bone['rotation']
        data.default_rotation.append(mathutils.Quaternion((w,x,y,z)).normalized() if any((w,x,y,z)) else mathutils.Quaternion())
        if bone['visibility'] is not None: data.visibilityDict[bone['name']] = bone['visibility']
    data.translation_data = [Vector(value) for value in parsed['translation']]
    data.rotation_data = [mathutils.Quaternion((w,x,y,z)).normalized() for x,y,z,w in parsed['rotation']]
    return data

def create_animation(data):
    action = utils.getCurrentAction()
    action.AnimationEndFrame = data.num_frames-1
    action.use_fake_user = True

    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = data.num_frames-1
    scene.render.fps = max(1, round(data.fps))
    scene.render.fps_base = scene.render.fps / data.fps
    scene.frame_set(0)

    utils.setModeToObject()

    armature = utils.findArmature()
    armature.select_set(True)  # select the skeleton
    bpy.context.view_layer.objects.active = armature

    bpy.ops.object.mode_set(mode='POSE')  # enter pose mode

    bpy.ops.pose.rot_clear()
    bpy.ops.pose.scale_clear()
    bpy.ops.pose.transforms_clear()

    # Build channels directly. Updating the scene for every bone/frame makes
    # long clips prohibitively expensive and is unnecessary with explicit poses.
    samples = {}
    def append(path, values, frame):
        for index,value in enumerate(values):
            samples.setdefault((path,index),[]).extend((frame,float(value)))

    previous_rotations = {}
    for frame in range(data.num_frames):
        local = {}
        for index,name in enumerate(data.bone_name_list):
            rotation = (data.rotation_data[frame*data.rotation_block_size+data.rotation_index[index]]
                        if data.rotation_index[index] != -1 else data.default_rotation[index])
            position = data.translation_offset[index].copy()
            if data.translation_index[index] != -1:
                packed = data.translation_data[frame*data.translation_block_size+data.translation_index[index]//3]
                for axis in range(3): position[axis] += packed[axis]*data.translation_scale[index][axis]
            local[name] = mathutils.Matrix.Translation(position) @ rotation.to_matrix().to_4x4()
        global_pose = {}
        def pose_matrix(name):
            if name in global_pose: return global_pose[name]
            bone = armature.data.bones[name]
            parent = pose_matrix(bone.parent.name) if bone.parent else None
            if name in local:
                matrix = parent @ local[name] if parent is not None else local[name]
            else:
                kwargs = dict(parent_matrix=parent,parent_matrix_local=bone.parent.matrix_local) if bone.parent else {}
                matrix = bone.convert_local_to_pose(mathutils.Matrix.Identity(4),bone.matrix_local,**kwargs)
            global_pose[name] = matrix
            return matrix
        for index,name in enumerate(data.bone_name_list):
            bone = armature.data.bones[name]
            pose = armature.pose.bones[name]
            pose.rotation_mode = 'QUATERNION'
            kwargs = dict(parent_matrix=pose_matrix(bone.parent.name),parent_matrix_local=bone.parent.matrix_local) if bone.parent else {}
            basis = bone.convert_local_to_pose(pose_matrix(name),bone.matrix_local,invert=True,**kwargs)
            location,rotation,scale = basis.decompose()
            previous = previous_rotations.get(name)
            if previous is not None and rotation.dot(previous) < 0:
                rotation.negate()
            previous_rotations[name] = rotation.copy()
            append(pose.path_from_id('location'),location,frame)
            if data.rotation_index[index] != -1 or frame in (0,data.num_frames-1):
                append(pose.path_from_id('rotation_quaternion'),rotation,frame)
            if name in data.visibilityDict:
                append(pose.path_from_id('proxyIsHiddenAnimation'),(data.visibilityDict[name][frame]=='0',),frame)

    layer = action.layers.new('ALAMO Animation')
    strip = layer.strips.new(type='KEYFRAME')
    bag = strip.channelbag(armature.animation_data.action_slot,ensure=True)
    for (path,index),coordinates in samples.items():
        curve = bag.fcurves.new(data_path=path,index=index)
        curve.keyframe_points.add(len(coordinates)//2)
        curve.keyframe_points.foreach_set('co',coordinates)
        for point in curve.keyframe_points:
            point.interpolation = 'CONSTANT' if path.endswith('proxyIsHiddenAnimation') else 'LINEAR'
        curve.update()
        curve.update_autoflags(armature)
    scene.frame_set(0)
    bpy.context.view_layer.update()

def validate(data):
    if data.num_frames-1 > bpy.types.Scene.bl_rna.properties['frame_end'].hard_max:
        raise RuntimeError('ALA frame count exceeds Blender timeline limits')
    armature = utils.findArmature()
    missing = [name for name in data.bone_name_list if name not in armature.data.bones]
    if missing:
        raise RuntimeError('Animation bones do not match Active Skeleton: ' + ', '.join(missing[:5]))
    return True


class AnimationImporter():
    def loadAnimation(self, filePath):
        arm = utils.findArmature()
        if arm is None:
            raise RuntimeError('Select an Active Skeleton before importing an ALA file')
        data = read_next_chunk(filePath)
        validate(data)
        with fileio.import_transaction(bpy.context, rig=arm):
            fileName = os.path.splitext(os.path.basename(filePath))[0]
            modelName = bpy.context.scene.modelFileName
            if modelName and fileName.startswith(modelName + '_'):
                fileName = fileName[len(modelName)+1:]
            action = bpy.data.actions.new(fileName)
            arm.animation_data_create()
            arm.animation_data.action = action
            arm.animation_data.action_slot = action.slots.new(id_type='OBJECT', name=arm.name)
            create_animation(data)
        return action


class ALA_Importer(bpy.types.Operator):
    """ALA Importer"""      # blender will use this as a tooltip for menu items and buttons.
    bl_idname = "import.ala"        # unique identifier for buttons and menu items to reference.
    bl_label = "Import ALA File"         # display name in the interface.
    bl_options = {'REGISTER', 'UNDO'}  # enable undo for the operator.
    filename_ext = ".ala"
    filter_glob : StringProperty(default="*.ala", options={'HIDDEN'})
    bl_info = {
        "name": "ALA Importer",
        "category": "Import",
    }

    filepath : StringProperty(name="File Path", description="Filepathused for importing the ALA file", maxlen=1024, default="")

    def execute(self, context):        # execute() is called by blender when running the operator.

        importer = AnimationImporter()
        animPath = self.properties.filepath
        try:
            importer.loadAnimation(animPath)
        except (RuntimeError, OSError, ValueError, struct.error) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        utils.setModeToObject()
        return {'FINISHED'}            # this lets blender know the operator finished successfully.

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
