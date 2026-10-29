import bpy
from . import settings, utils, import_ala, viewport, quality, fileio, alo_skeleton

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
from os import listdir
import bmesh

def boneEnumCallback(scene, context):
    bones = [('None', 'None', '', '', 0)]
    counter = 1
    armature = utils.findArmature()
    if(armature != None):
        for bone in armature.data.bones:
            bones.append((bone.name, bone.name, '', '', counter))
            counter += 1
    bones.sort(key=lambda tup : tup[0])
    global _bone_enum_items
    _bone_enum_items = bones
    return _bone_enum_items

class ALO_Importer(bpy.types.Operator):
    """ALO Importer"""      # blender will use this as a tooltip for menu items and buttons.
    bl_idname = "import.alo"        # unique identifier for buttons and menu items to reference.
    bl_label = "Import ALO File"         # display name in the interface.
    bl_options = {'REGISTER', 'UNDO'}  # enable undo for the operator.
    filename_ext = ".alo"
    filter_glob : StringProperty(default="*.alo", options={'HIDDEN'})
    bl_info = {
        "name": "ALO Importer",
        "category": "Import",
    }

    parentName : EnumProperty(
        name='Attachment Bone',
        description = "Bone that imported models are attached to",
        items = boneEnumCallback
    )

    importAnimations : BoolProperty(
            name="Import Animations",
            description="Import the model's animations from the same path",
            default=True,
            )

    frameImportedModel : BoolProperty(
            name="Frame Imported Model",
            description="Center the viewport and adjust clipping to the model's size",
            default=True,
            )

    fastPreview : BoolProperty(
            name="Fast Preview",
            description="Use lightweight solid shading and hide overlays; restore from the ALAMO sidebar",
            default=False,
            )

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "importAnimations")
        layout.prop(self, "frameImportedModel")
        layout.prop(self, "fastPreview")
        layout.prop(self, "parentName")

    filepath : StringProperty(name="File Path", description="Filepath used for importing the ALO file", maxlen=1024, default="")

    def execute(self, context):
        try:
            fileio.checked_alo(self.filepath)
            with fileio.import_transaction(context):
                return self._execute(context)
        except (RuntimeError, OSError, ValueError, struct.error) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def _execute(self, context):

        #main structure

        def process_active_junk():
            meshNameList = []
            #loop over file until end is reached
            while(file.tell() < os.path.getsize(self.properties.filepath)):
                active_chunk = file.read(4)
                #print(active_chunk)
                if active_chunk == b"\x00\x02\x00\00":
                    armatureData = createArmature()
                elif active_chunk == b"\x00\x04\x00\00":
                    file.seek(4, 1) #skip size
                    meshName = processMeshChunk()
                    meshNameList.append(meshName)
                elif active_chunk == b"\x00\x13\x00\00":    #light chunk is irrelevant
                    self.report({'WARNING'}, 'Light object skipped; mesh attachment indices are preserved')
                    meshNameList.append(None)
                    size = read_chunk_length()
                    file.seek(size, 1)  #skip to next chunk
                elif active_chunk == b"\x00\x06\x00\00":
                    file.seek(8, 1)  # skip size and next header
                    n_objects_proxies = get_n_objects_n_proxies()
                    n_objects = n_objects_proxies['n_objects']
                    n_proxies = n_objects_proxies['n_proxies']
                    print('Found Connection Chunk')
                elif active_chunk == b"\x02\x06\x00\00":
                    read_conncetion(armatureData, meshNameList)
                elif active_chunk == b"\x03\x06\x00\00":
                    read_proxy()
                else:
                    file.seek(read_chunk_length(), 1)

        #armature and bones

        class Armature():
            def __init__(self):
                self.bones = []
                self.boneCount = 0

        class Bone():
            def __init__(self):
                self.name = ''
                self.parentIndex = 0
                self.visible = 0
                self.billboard = 0
                self.matrix = None

        def removeShadowDoubles():
            for object in importCollection.objects:
                if(object.type == 'MESH'):
                    if(len(object.material_slots) <= 0): continue; #already existing objects might not have a material
                    shader = object.material_slots[0].material.shaderList.shaderList
                    if (shader == 'MeshCollision.fx' or shader == 'RSkinShadowVolume.fx' or shader == 'MeshShadowVolume.fx'):
                        bpy.ops.object.select_all(action='DESELECT')

                        bpy.context.view_layer.objects.active = object
                        object.select_set(True)
                        bpy.ops.object.mode_set(mode='EDIT')
                        bpy.ops.mesh.select_all(action='SELECT')
                        bpy.ops.mesh.remove_doubles()
                        bpy.ops.object.mode_set(mode='OBJECT')

        def createArmature():

            global fileName

            #create armature
            armatureBlender = bpy.data.armatures.new(fileName + "Armature")

            #create object
            armatureObj = bpy.data.objects.new(fileName + "Rig", object_data=armatureBlender)

            # Link object to collection
            importCollection.objects.link(armatureObj)
            bpy.context.view_layer.objects.active = armatureObj
            bpy.context.view_layer.update()

            #adjust settings and enter edit-mode
            armatureObj = bpy.context.object
            armatureObj.show_in_front = True
            utils.setModeToEdit()

            armatureBlender.display_type = 'STICK'
            armatureData = Armature()

            records = alo_skeleton.read(file.read(read_chunk_length()))
            for record in records:
                bone = Bone()
                bone.name = cut_string(record['name'])
                bone.parentIndex = record['parent']
                bone.visible = record['visible']
                bone.billboard = record['billboard']
                bone.matrix = record['matrix']
                armatureData.bones.append(bone)
            armatureData.boneCount = len(records)

            for bone in armatureData.bones:
                createBone(bone, armatureBlender, armatureData)

            bpy.ops.object.mode_set(mode = 'OBJECT')

            bpy.context.scene.ActiveSkeleton.skeletonEnum = armatureObj.name

            return armatureData

        def createBone(boneData, armatureBlender, armatureData):
            billboardModeArray = ["Disable", "Parallel", "Face", "ZAxis View", "ZAxis Light", "ZAxis Wind", "Sunlight Glow", "Sun"]

            bone_matrix = []  # initialize for use
            bone = armatureBlender.edit_bones.new(boneData.name)
            bone.tail = mathutils.Vector([0, 1, 0])

            if boneData.visible == 1:
                bone.Visible = True
            else:
                bone.Visible = False

            parent = (armatureData.bones[boneData.parentIndex].blenderName
                      if boneData.parentIndex >= 0 else None)
            if parent is not None and parent != 'Root':
                bone.parent = armatureBlender.edit_bones[parent]
                bone.matrix = bone.parent.matrix @ mathutils.Matrix(boneData.matrix)
            else:
                bone.matrix = mathutils.Matrix(boneData.matrix)
            boneData.blenderName = bone.name

            bone.billboardMode.billboardMode = billboardModeArray[boneData.billboard]

            bpy.ops.object.mode_set(mode='EDIT')

        #mesh and material

        class meshClass():
            def __init__(self):
                self.name = ''
                self.isHidden = False
                self.collision = False
                self.nMaterials = 0
                self.subMeshList = []

            def getNVerts(self):
                nVerts = 0
                for subMesh in self.subMeshList:
                    nVerts += subMesh.nVertices
                return nVerts

        class subMeshClass():
            def __init__(self):
                self.nVertices = 0
                self.nFaces = 0
                self.shader = None
                self.vertices = []
                self.faces = []
                self.faceOffset = 0
                self.UVs = []
                self.normals = []
                self.extraUVs = []
                self.colors = []
                self.tangents = []
                self.bitangents = []
                self.material = None
                self.animationMapping = []
                self.boneIndex = []

        def construct_mesh(currentMesh):

            vertices = []
            faces = []
            UVs = []
            animationMapping = []
            normals = []
            extra_uvs = []
            colors = []
            tangents = []
            bitangents = []
            for subMesh in currentMesh.subMeshList:
                vertices += subMesh.vertices
                faces += subMesh.faces
                UVs += subMesh.UVs
                normals += subMesh.normals
                extra_uvs += subMesh.extraUVs
                colors += subMesh.colors
                tangents += subMesh.tangents
                bitangents += subMesh.bitangents
                animationMapping += subMesh.animationMapping

            for vectors in (vertices, normals, UVs, tangents, bitangents, colors):
                if any(not math.isfinite(c) for vector in vectors for c in vector):
                    raise RuntimeError('Non-finite ALO vertex attributes on ' + currentMesh.name)
            if any(not math.isfinite(c) for sets in extra_uvs for uv in sets for c in uv):
                raise RuntimeError('Non-finite ALO UV coordinates on ' + currentMesh.name)
            mesh.from_pydata(vertices, [], faces)

            # Update mesh with new data
            mesh.update(calc_edges=True)

            polys = mesh.polygons
            for p in polys:
                p.use_smooth = True

            mesh.normals_split_custom_set_from_vertices(normals)
            for name, vectors in [('normal', normals), ('tangent', tangents), ('bitangent', bitangents)]:
                source_vectors = mesh.attributes.new(name='alamo_source_' + name, type='FLOAT_VECTOR', domain='POINT')
                source_vectors.data.foreach_set('vector', [c for vector in vectors for c in vector])

            #assign materials correctly
            if currentMesh.nMaterials > 1:
                currentSubMeshMaxFaceIndex = currentMesh.subMeshList[0].nFaces
                subMeshCounter = 0
                for face in mesh.polygons:
                    while face.index >= currentSubMeshMaxFaceIndex and subMeshCounter < len(currentMesh.subMeshList)-1:
                        subMeshCounter += 1
                        currentSubMeshMaxFaceIndex += currentMesh.subMeshList[subMeshCounter].nFaces
                    face.material_index = subMeshCounter

            # create UVs
            createUVLayer("MainUV", UVs)
            for channel in range(3):
                values = [uv[channel] for uv in extra_uvs]
                if any(u != 0 or v != 0 for u, v in values):
                    # Keep channel positions even if intervening channels are zero.
                    while len(mesh.uv_layers) <= channel + 1:
                        index = len(mesh.uv_layers) - 1
                        createUVLayer('UV' + str(index + 2), [uv[index] for uv in extra_uvs])
            mesh.uv_layers.active_index = 0
            if any(color != (1.0, 1.0, 1.0, 1.0) for color in colors):
                attribute = mesh.color_attributes.new(name='ALAMO Color', type='FLOAT_COLOR', domain='POINT')
                attribute.data.foreach_set('color', [c for rgba in colors for c in rgba])
                mesh.color_attributes.active_color = attribute
            assign_vertex_groups(animationMapping, currentMesh)
            mesh['alamo_basis_fingerprint'] = quality.basis_fingerprint(mesh)

            return mesh

        def readMeshInfo(currentMesh):
            file.seek(8, 1)  # skip size and header

            nMaterials = struct.unpack("I", file.read(4))[0]
            currentMesh.nMaterials = nMaterials

            file.seek(24 + 4, 1)  # skip bounding box size and unused
            isHidden = struct.unpack("<I", file.read(4))[0]

            if isHidden == 1:
                currentMesh.isHidden = True

            collision = struct.unpack("<I", file.read(4))[0]
            if collision == 1:
                currentMesh.collision = True

            file.seek(88, 1)
            create_object(currentMesh)

        def get_mesh_name():
            file.seek(4, 1)
            return cut_string(read_string())

        def get_n_vertices_n_primitives(currentSubMesh):
            currentSubMesh.nVertices = struct.unpack("<I", file.read(4))[0]
            currentSubMesh.nFaces = struct.unpack("<I", file.read(4))[0]
            file.seek(120, 1)

        def processMeshChunk():
            #name chunk
            currentMesh = meshClass()
            meshList.append(currentMesh)
            currentMesh.name = get_mesh_name()

            readMeshInfo(currentMesh)

            counter = 0
            faceOffset = 0
            while (counter < currentMesh.nMaterials):
                currentSubMesh = subMeshClass()
                currentMesh.subMeshList.append(currentSubMesh)

                currentSubMesh.faceOffset = faceOffset
                read_material_info_chunk(currentSubMesh)
                read_mesh_data(currentSubMesh)
                faceOffset += currentSubMesh.nVertices
                counter += 1

            contructed_mesh = construct_mesh(currentMesh)
            return currentMesh.objectName

        def read_mesh_data(currentSubMesh):
            file.seek(4,1)  #skip header
            meshDataChunkSize = read_chunk_length()
            currentPosition = file.tell()
            while (file.tell() < currentPosition + meshDataChunkSize):
                active_chunk = file.read(4)
                if active_chunk == b"\x01\x00\x01\00":
                    if read_chunk_length() != 128:
                        raise RuntimeError('Invalid ALO submesh information size')
                    get_n_vertices_n_primitives(currentSubMesh)
                elif active_chunk == b"\x02\x00\x01\00":
                    size = read_chunk_length()
                    file.seek(size, 1)  # skip to next chunk
                elif active_chunk == b"\x04\x00\x01\00":
                    if read_chunk_length() != currentSubMesh.nFaces * 6:
                        raise RuntimeError('ALO triangle count does not match index buffer size')
                    faces = process_index_buffer(currentSubMesh)
                elif active_chunk == b"\x06\x00\x01\00":
                    read_animation_mapping(currentSubMesh)
                elif active_chunk == b"\x07\x00\x01\00":
                    if read_chunk_length() != currentSubMesh.nVertices * 144:
                        raise RuntimeError('ALO vertex count does not match vertex buffer size')
                    vertex_data = process_vertex_buffer_2(False, currentSubMesh)
                elif active_chunk == b"\x05\x00\x01\00":
                    if read_chunk_length() != currentSubMesh.nVertices * 128:
                        raise RuntimeError('ALO vertex count does not match legacy vertex buffer size')
                    # old version of the chunk
                    vertex_data = process_vertex_buffer_2(True, currentSubMesh)
                elif active_chunk == b"\x00\x12\x00\00":
                    size = read_chunk_length()
                    file.seek(size, 1)  # skip to next chunk
                else:
                    file.seek(read_chunk_length(), 1)

        def read_material_info_chunk(currentSubMesh):
            file.seek(4,1) #skip header
            materialChunkSize = read_chunk_length()
            currentPosition = file.tell()
            while (file.tell() < currentPosition + materialChunkSize):
                active_chunk = file.read(4)
                if active_chunk == b"\x01\x01\x01\00":
                    create_material(currentSubMesh)
                elif active_chunk == b"\x02\x01\x01\00":
                    read_int(currentSubMesh.material)
                elif active_chunk == b"\x03\x01\x01\00":
                    read_float(currentSubMesh.material)
                elif active_chunk == b"\x04\x01\x01\00":
                    read_float3(currentSubMesh.material)
                elif active_chunk == b"\x05\x01\x01\00":
                    process_texture_chunk(currentSubMesh.material)
                elif active_chunk == b"\x06\x01\x01\00":
                    read_float4(currentSubMesh.material)
                else:
                    file.seek(read_chunk_length(), 1)
            set_up_textures(currentSubMesh.material)

        def read_animation_mapping(currentSubMesh):
            chunk_size = read_chunk_length()  # read chunk size
            if chunk_size % 4:
                raise RuntimeError('Invalid ALO bone mapping size')
            read_counter = chunk_size / 4
            counter = 0
            animation_mapping = []
            while counter < read_counter:
                index = struct.unpack('<I', file.read(4))[0]
                if index >= len(utils.findArmature().data.bones):
                    raise RuntimeError('ALO bone mapping index is out of range')
                currentSubMesh.animationMapping.append(index)
                counter += 1
            return animation_mapping

        def set_up_textures(material):

            material.use_nodes = True
            nt = material.node_tree
            nodes = nt.nodes
            links = nt.links

            #clean up
            while(nodes): nodes.remove(nodes[0])

            output  = nodes.new("ShaderNodeOutputMaterial")
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")

            base_image_node = nodes.new("ShaderNodeTexImage")
            normal_image_node = nodes.new("ShaderNodeTexImage")

            normal_map_node = nodes.new("ShaderNodeNormalMap")
            normal_map_node.space = 'TANGENT'
            normal_map_node.uv_map = 'MainUV'

            uvmap   = nodes.new("ShaderNodeUVMap")
            uvmap.uv_map = "MainUV"

            links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
            bsdf.inputs['Base Color'].default_value = (*material.Diffuse[:3], 1.0)
            if material.BaseTexture != 'None':
                links.new(bsdf.inputs['Base Color'],   base_image_node.outputs['Color'])
                links.new(bsdf.inputs['Alpha'],   base_image_node.outputs['Alpha'])
                links.new(base_image_node.inputs['Vector'],    uvmap.outputs['UV'])

                if material.BaseTexture in bpy.data.images:
                    diffuse_texture = bpy.data.images[material.BaseTexture]
                    base_image_node.image = diffuse_texture

            if material.NormalTexture != 'None':
                links.new(normal_image_node.outputs['Color'], normal_map_node.inputs['Color'])
                links.new(normal_map_node.outputs['Normal'], bsdf.inputs['Normal'])
                links.new(normal_image_node.inputs['Vector'],    uvmap.outputs['UV'])

                if material.NormalTexture in bpy.data.images:
                    normal_texture = bpy.data.images[material.NormalTexture]
                    normal_image_node.image = normal_texture
                    normal_image_node.image.colorspace_settings.name = 'Non-Color'

            # distribute nodes along the x axis
            for index, node in enumerate((uvmap, base_image_node, bsdf, output)):
                node.location.x = 200.0 * index

            normal_map_node.location = bsdf.location
            normal_map_node.location.y += 300.0

            output.location.x += 200.0
            bsdf.location.x += 200.0

            normal_image_node.location = base_image_node.location
            normal_image_node.location.y += 300.0

        def create_object(currentMesh):
            global mesh
            mesh = bpy.data.meshes.new(currentMesh.name)
            object = bpy.data.objects.new(mesh.name, mesh)
            global MeshNameList
            MeshNameList.append(object.name)
            currentMesh.objectName = object.name

            # Link object to collection
            importCollection.objects.link(object)
            bpy.context.view_layer.objects.active = object
            bpy.context.view_layer.update()

            context.view_layer.objects.active = object  # make created object active
            object.show_transparent = True

            if (currentMesh.isHidden == 1):
                object.Hidden = True

            if (currentMesh.collision == 1):
                object.HasCollision = True

            #create vertex groups
            armature = utils.findArmature()
            for bone in armature.data.bones:
                vertgroup = object.vertex_groups.new(name=bone.name)

        def process_vertex_buffer_2(legacy, currentSubMesh):
            f = struct.Struct('<f')
            i = struct.Struct('<I')
            counter = 0
            while counter < currentSubMesh.nVertices:
                coX = f.unpack(file.read(4))[0]
                coY = f.unpack(file.read(4))[0]
                coZ = f.unpack(file.read(4))[0]
                currentSubMesh.vertices.append(mathutils.Vector((coX, coY, coZ)))
                currentSubMesh.normals.append(struct.unpack('<3f', file.read(12)))
                UV = []
                UV.append(f.unpack(file.read(4))[0])
                UV.append(f.unpack(file.read(4))[0] * (-1))
                currentSubMesh.UVs.append(UV)
                packed_uvs = struct.unpack('<6f', file.read(24))
                currentSubMesh.extraUVs.append(tuple((packed_uvs[j], -packed_uvs[j+1]) for j in (0, 2, 4)))
                currentSubMesh.tangents.append(struct.unpack('<3f', file.read(12)))
                currentSubMesh.bitangents.append(struct.unpack('<3f', file.read(12)))
                currentSubMesh.colors.append(struct.unpack('<4f', file.read(16)))
                if not legacy:
                    file.seek(16, 1)
                currentSubMesh.boneIndex.append(i.unpack(file.read(4))[0])
                file.seek(28, 1)
                counter += 1

        def process_index_buffer(currentSubMesh):
            h = struct.Struct('<H')
            counter = 0
            while counter < currentSubMesh.nFaces:
                face = []
                face.append(h.unpack(file.read(2))[0] + currentSubMesh.faceOffset)
                face.append(h.unpack(file.read(2))[0] + currentSubMesh.faceOffset)
                face.append(h.unpack(file.read(2))[0] + currentSubMesh.faceOffset)
                if any(i < currentSubMesh.faceOffset or i >= currentSubMesh.faceOffset + currentSubMesh.nVertices for i in face):
                    raise RuntimeError('ALO triangle vertex index is out of range')
                currentSubMesh.faces.append(face)
                counter += 1

        def process_texture_chunk(material):
            fields = fileio.mini_chunks(file.read(read_chunk_length()))
            function = fileio.cstring(fields.get(1, b''), 'texture parameter')
            texture_name = fileio.cstring(fields.get(2, b''), 'texture filename')
            if texture_name != 'None' and not texture_name.lower().endswith('.dds'):
                texture_name = os.path.splitext(texture_name)[0] + '.dds'
            load_image(texture_name)
            if validate_material_prop(function):
                setattr(material, function, texture_name)

        def createUVLayer(layerName, uv_coordinates):
            vert_uvs = uv_coordinates
            mesh.uv_layers.new(name = layerName)
            mesh.uv_layers[-1].data.foreach_set("uv", [uv for pair in [vert_uvs[l.vertex_index] for l in mesh.loops] for uv in pair])

        def create_material(currentSubMesh):  # create material and assign
            shaderName = read_string()
            obj = bpy.context.object
            mat = bpy.data.materials.new(obj.name + "Material")

            #find shader, ignoring case
            currentKey = None
            for key in settings.material_parameter_dict:
                if(key.lower() == shaderName.lower()):
                    currentKey = key
                    break

            if currentKey == None:
                print("Warning: unknown shader: " + shaderName + " setting shader to alDefault.fx")
                currentKey = "alDefault.fx"

            mat.shaderList.shaderList = currentKey

            obj.data.materials.append(mat)
            currentSubMesh.material = mat

        def assign_vertex_groups(animation_mapping, currentMesh):
            # assign vertex groups
            object = bpy.context.view_layer.objects.active
            armatureObject = utils.findArmature()
            if not any(sub.animationMapping for sub in currentMesh.subMeshList):
                return
            mod = object.modifiers.new('MyRigModif', 'ARMATURE')
            mod.object = armatureObject
            mod.use_bone_envelopes = False
            mod.use_vertex_groups = True
            groups = {}
            for sub in currentMesh.subMeshList:
                for index, mapped in enumerate(sub.boneIndex):
                    if not sub.animationMapping:
                        continue
                    if mapped >= len(sub.animationMapping):
                        raise RuntimeError('ALO vertex bone mapping index is out of range')
                    bone = sub.animationMapping[mapped]
                    groups.setdefault(bone, []).append(sub.faceOffset + index)
            for bone, vertices in groups.items():
                object.vertex_groups[bone].add(vertices, 1, 'REPLACE')

        #proxy and connection functions

        def get_n_objects_n_proxies():
            size = read_chunk_length()
            file.seek(2, 1)
            n_objects = struct.unpack("l", file.read(4))
            file.seek(2, 1)
            n_proxies = struct.unpack("l", file.read(4))
            n_objects_proxies = {"n_objects": n_objects[0], "n_proxies": n_proxies[0]}

            #some .alo formats have an additional unspecified value at this position
            #to read the rest correctly this code checks if this is the case here and skips appropriately
            size -= 12
            file.seek(size, 1)

            return n_objects_proxies

        def read_conncetion(armatureData, meshNameList):
            fields = fileio.mini_chunks(file.read(read_chunk_length()))
            mesh_index = fileio.uint_field(fields, 2, 'connection object index')
            bone_index = fileio.uint_field(fields, 3, 'connection bone index')
            if mesh_index >= len(meshNameList) or bone_index >= len(armatureData.bones):
                raise RuntimeError('ALO connection index is out of range')
            name = meshNameList[mesh_index]
            if name is None: return  # ignored light, still counted in file indices
            obj = bpy.data.objects[name]
            armatureBlender = utils.findArmature()
            bone_name = armatureData.bones[bone_index].blenderName
            if bone_name != 'Root':
                constraint = obj.constraints.new('CHILD_OF')
                constraint.target = armatureBlender
                constraint.subtarget = bone_name

        def read_proxy():
            fields = fileio.mini_chunks(file.read(read_chunk_length()))
            proxy_name = fileio.cstring(fields.get(5, b''), 'proxy name')
            index = fileio.uint_field(fields, 6, 'proxy bone index')
            armatureBlender = utils.findArmature()
            if index >= len(armatureBlender.data.bones):
                raise RuntimeError('ALO proxy bone index is out of range')
            bone_name = armatureBlender.data.bones[index].name
            bpy.context.view_layer.objects.active = armatureBlender
            bpy.ops.object.mode_set(mode='EDIT')
            bone = armatureBlender.data.edit_bones[bone_name]
            bone.EnableProxy = True
            bone.ProxyName = proxy_name
            bone.proxyIsHidden = fileio.uint_field(fields, 7, 'proxy visibility') == 1 if 7 in fields else False
            bone.altDecreaseStayHidden = fileio.uint_field(fields, 8, 'proxy altitude visibility') == 1 if 8 in fields else False
            bpy.ops.object.mode_set(mode='OBJECT')

        #Utility functions

        def read_chunk_length():
            #the hight bit is used to tell if chunk holds data or chunks, so if it is set it has to be ignored when calculating length
            length = struct.unpack("<I", file.read(4))[0]
            if length >= 2147483648:
                length -= 2147483648
            return length

        def cut_string(string):
            #bones have a 63 character limit, this function cuts longer strings with space for .xyz end used by blender to distinguish double name
            if(len(string)> 63):
                return string[0:59]
            else:
                return string

        def read_string():
            return fileio.cstring(file.read(read_chunk_length()))

        def read_string_mini_chunk():
            header = file.read(2)
            if len(header) != 2:
                raise RuntimeError('Truncated string mini-chunk')
            return fileio.cstring(file.read(header[1]))

        def hideObject(object):

            object.hide_set(True)

        def hideLODs():
            #hides all but the most detailed LOD in Blender
            for object in importCollection.objects:
                if(object.type == 'MESH'):
                    #check if name ends with LOD
                    if object.name[len(object.name)-4:len(object.name)-1] == 'LOD':
                        #check for hightest LOD
                        lodCounter = 0
                        while (object.name[:-1]+str(lodCounter) in importCollection.objects):
                            lodCounter += 1
                        #hide smaller LODS
                        counter = 0
                        while(counter < lodCounter-1):
                            hideObject(importCollection.objects[object.name[:-1] + str(counter)])
                            counter += 1

            #hide object if its a shadow or a collision
            for object in importCollection.objects:
                if object.type == 'MESH':
                    if len(object.material_slots) != 0:
                        shader = object.material_slots[0].material.shaderList.shaderList
                        if(shader == 'MeshCollision.fx' or shader == 'RSkinShadowVolume.fx' or shader == 'MeshShadowVolume.fx'):
                            hideObject(object)

            #hide objects that are set to not visible
            for object in importCollection.objects:
                if (object.type == 'MESH'):
                    if object.Hidden == True:
                        hideObject(object)

        def deleteRoot():
            armature = utils.findArmature()
            armature.select_set(True)  # select the skeleton
            context.view_layer.objects.active  = armature

            if bpy.context.mode != 'EDIT_ARMATURE':
                bpy.ops.object.mode_set(mode='EDIT')
            if 'Root' in armature.data.edit_bones:
                armature.data.edit_bones.remove(armature.data.edit_bones['Root'])
            bpy.ops.object.mode_set(mode='OBJECT')

        # material utility functions

        def load_image(texture_name):
            if texture_name == 'None':
                return
            elif (texture_name in bpy.data.images):
                img = bpy.data.images[texture_name]
            else:
                path = file.name
                path = os.path.split(path)[0]
                path = os.path.split(path)[0] + "/TEXTURES/" + texture_name
                if os.path.isfile(path):
                    try:
                        img = bpy.data.images.load(path)
                    except (RuntimeError, OSError) as exc:
                        self.report({'WARNING'}, 'Could not load texture ' + texture_name + ': ' + str(exc))
                else:
                    print("Couldn't find texture: " + texture_name)
                    return

        def validate_material_prop(name):
            material_props = {p for parameters in settings.material_parameter_dict.values() for p in parameters if p}

            if(name in material_props):
                return True
            else:
                print("Unknown material porperty: " + name)
                return False

        def read_int(material):
            file.seek(4, 1)  # skip size
            name = read_string_mini_chunk()
            file.seek(2, 1)  # skip mini header and size
            value = struct.unpack('<I', file.read(4))[0]

            if validate_material_prop(name):
                setattr(material, name, value)

        def read_float(material):
            file.seek(4, 1)  # skip size
            name = read_string_mini_chunk()
            file.seek(2, 1)  # skip mini header and size
            value = struct.unpack('<f', file.read(4))[0]

            if validate_material_prop(name):
                setattr(material, name, value)

        def read_float3(material):
            file.seek(4, 1)  # skip size
            name = read_string_mini_chunk()
            file.seek(2, 1)  # skip mini header and size
            value1 = struct.unpack('<f', file.read(4))[0]
            value2 = struct.unpack('<f', file.read(4))[0]
            value3 = struct.unpack('<f', file.read(4))[0]

            value = (value1, value2, value3)

            if validate_material_prop(name):
                setattr(material, name, value)

        def read_float4(material):
            file.seek(4, 1)  # skip size
            name = read_string_mini_chunk()
            file.seek(2, 1)  # skip mini header and size
            value1 = struct.unpack('<f', file.read(4))[0]
            value2 = struct.unpack('<f', file.read(4))[0]
            value3 = struct.unpack('<f', file.read(4))[0]
            value4 = struct.unpack('<f', file.read(4))[0]

            value = (value1, value2, value3, value4)

            if validate_material_prop(name):
                setattr(material, name, value)

        def loadAnimations(filePath):
            #remove ending
            path = os.path.dirname(os.path.abspath(filePath))
            fileName = os.path.splitext(os.path.basename(filePath))[0]
            bpy.context.scene.modelFileName = fileName

            animationFiles = []

            for file in listdir(path):
                fileExt = file[-4:]
                if(fileExt.lower() == ".ala" and file[0:len(fileName)] == fileName):
                    animationFiles.append(file)

            importer = import_ala.AnimationImporter()
            arm = utils.findArmature()
            arm.animation_data_create()

            for animFile in sorted(animationFiles, key=str.casefold):
                try:
                    importer.loadAnimation(os.path.join(path, animFile))
                except (RuntimeError, OSError) as exc:
                    self.report({'WARNING'}, 'Skipped animation ' + animFile + ': ' + str(exc))

        global assignedVertexGroups
        assignedVertexGroups = []
        global MeshNameList
        MeshNameList=[]
        global doubleMeshes
        doubleMeshes=[]
        global boneNameListALO
        boneNameListALO = []
        global boneConnectedDict
        boneConnectedDict = {}

        global meshList
        meshList = []

        global fileName
        fileName = os.path.splitext(os.path.basename(self.properties.filepath))[0]

        global importCollection
        importCollection = bpy.data.collections.new(fileName)
        bpy.context.scene.collection.children.link(importCollection)

        #is changed due to implementation details in the enum callback
        activeArmatureBackup = 'None'
        originalArmature = utils.findArmature()
        if(originalArmature != None):
            activeArmatureBackup = originalArmature.name

        global file
        filepath = self.properties.filepath
        file = open(filepath, 'rb') #open file in read binary mode
        try:
            process_active_junk()
        finally:
            file.close()
        removeShadowDoubles()
        hideLODs()
        deleteRoot()
        if(self.importAnimations):
            loadAnimations(filepath)

        #restore previous active armature
        if(activeArmatureBackup != 'None'):
            createdArmature = utils.findArmature() #get new armature
            bpy.context.scene.ActiveSkeleton.skeletonEnum = activeArmatureBackup #restore
            armature = utils.findArmature()
            #set parent
            if(self.parentName != 'None' and armature != None):
                parentBone = armature.data.bones[self.parentName]
                if(parentBone != None):
                    createdArmature.parent = armature
                    createdArmature.parent_bone = self.parentName
                    createdArmature.parent_type = 'BONE'

        if self.frameImportedModel:
            context.view_layer.update()
            viewport.frame_model(context, importCollection.all_objects)
        if self.fastPreview:
            viewport.set_fast_preview(context, True)

        return {'FINISHED'}            # this lets blender know the operator finished successfully.

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

