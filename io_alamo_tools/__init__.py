bl_info = {
    "name": "ALAMO Tools",
    "author": "Gaukler",
    "version": (1, 2, 2),
    "blender": (5, 2, 0),
    "category": "Import-Export"
}

if "bpy" in locals():
    import importlib
    from . import fileio, foc_animation, alo_skeleton
    importlib.reload(fileio)
    importlib.reload(alo_skeleton)
    importlib.reload(foc_animation)
    importlib.reload(import_alo)
    importlib.reload(import_ala)
    importlib.reload(export_alo)
    importlib.reload(export_ala)
    importlib.reload(settings)
    importlib.reload(utils)
    importlib.reload(animation)
    importlib.reload(viewport)
    importlib.reload(quality)
    importlib.reload(validation)
else:
    from . import import_alo
    from . import import_ala
    from . import export_alo
    from . import export_ala
    from . import settings
    from . import utils
    from . import animation
    from . import viewport
    from . import quality
    from . import validation
    from . import fileio, foc_animation, alo_skeleton

import bpy
import mathutils
from bpy.props import *
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

class createConstraintBoneButton(bpy.types.Operator):
    bl_idname = "create.constraint_bone"
    bl_label = "Create constraint bone"

    def execute(self, context):
        object = bpy.context.view_layer.objects.active
        armature = utils.findArmature()

        bpy.context.view_layer.objects.active = armature
        utils.setModeToEdit()

        bone = armature.data.edit_bones.new(object.name)
        bone.tail = bone.head +  mathutils.Vector((0, 0, 1))
        bone.matrix = object.matrix_world
        object.location = mathutils.Vector((0.0, 0.0, 0.0))
        object.rotation_euler = mathutils.Euler((0.0, 0.0, 0.0), 'XYZ')
        constraint = object.constraints.new('CHILD_OF')
        constraint.target = armature
        constraint.subtarget = bone.name

        utils.setModeToObject()
        bpy.context.view_layer.objects.active = object
        return {'FINISHED'}

def skeletonEnumCallback(scene, context):
    armatures = [('None', 'None', '', '', 0)]
    counter = 1
    for arm in bpy.data.objects:  # test if armature exists
        if arm.type == 'ARMATURE':
            armatures.append((arm.name, arm.name, '', '', counter))
            counter += 1

    global _skeleton_enum_items
    _skeleton_enum_items = armatures
    return _skeleton_enum_items

class skeletonEnumClass(PropertyGroup):
    skeletonEnum : EnumProperty(
        name='Active Skeleton',
        description = "skeleton that is exported",
        items = skeletonEnumCallback
    )

class ALAMO_OT_frame_model(bpy.types.Operator):
    """Center the model and fit viewport clipping to its size"""
    bl_idname = "view3d.alamo_frame_model"
    bl_label = "Frame ALAMO Model"

    def execute(self, context):
        armature = utils.findArmature()
        target = armature if armature is not None else context.object
        if target is None:
            self.report({'WARNING'}, "Select an ALAMO mesh or Active Skeleton")
            return {'CANCELLED'}
        objects = {obj for collection in target.users_collection for obj in collection.all_objects}
        if not viewport.frame_model(context, objects):
            self.report({'WARNING'}, "No visible model geometry or usable viewport found")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALAMO_OT_fast_preview(bpy.types.Operator):
    """Toggle lightweight solid preview; restore your previous viewport settings when switched off"""
    bl_idname = "view3d.alamo_fast_preview"
    bl_label = "ALAMO Fast Preview"

    def execute(self, context):
        areas = viewport.viewport_areas(context)
        if not areas:
            self.report({'WARNING'}, "Open a 3D viewport to change preview settings")
            return {'CANCELLED'}
        enabled = not viewport.is_fast_preview(areas[0])
        viewport.set_fast_preview(context, enabled)
        self.report({'INFO'}, "Fast Preview enabled; overlays hidden" if enabled else "Previous viewport settings restored")
        return {'FINISHED'}


class ALAMO_PT_ToolsPanel(bpy.types.Panel):

    bl_label = "ALAMO properties"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ALAMO"

    def draw(self, context):
        object = context.object
        layout = self.layout
        scene = context.scene
        c = layout.column()

        c.prop(scene.ActiveSkeleton, 'skeletonEnum')
        c.operator("view3d.alamo_frame_model", icon='VIEWZOOM')
        fast_preview = viewport.is_fast_preview(context.area)
        c.operator("view3d.alamo_fast_preview",
                   text="Restore Editing View" if fast_preview else "Fast Preview",
                   icon='HIDE_ON' if fast_preview else 'SHADING_SOLID', depress=fast_preview)
        if fast_preview:
            c.label(text="Overlays hidden for navigation")

        if type(object) != type(None):
            if(object.type == 'MESH'):
                if bpy.context.mode == 'OBJECT':
                    c.prop(object, "HasCollision")
                    c.prop(object, "Hidden")

                    armature = utils.findArmature()
                    if armature != None:
                        hasChildConstraint = False
                        for constraint in object.constraints:
                            if constraint.type == 'CHILD_OF':
                                hasChildConstraint = True
                        if not hasChildConstraint:
                            self.layout.operator("create.constraint_bone", text = 'Create Constraint Bone')

            action = utils.getCurrentAction()
            if(action != None):
                c.prop(action, "AnimationEndFrame")


        bone = bpy.context.active_bone
        if type(bone) != type(None):
            if(type(bpy.context.active_bone ) is bpy.types.EditBone):
                c.prop(bone.billboardMode, "billboardMode")
                c.prop(bone, "Visible")
                c.prop(bone, "EnableProxy")
                if bone.EnableProxy:
                    c.prop(bone, "proxyIsHidden")
                    c.prop(bone, "altDecreaseStayHidden")
                    c.prop(bone, "ProxyName")

            elif (type(bpy.context.active_bone) is bpy.types.Bone and bpy.context.mode == 'POSE'):
                poseBone = object.pose.bones[bone.name]
                c.prop(poseBone, "proxyIsHiddenAnimation")

class ALAMO_PT_materialPropertyPanel(bpy.types.Panel):
    bl_label = "Alamo material properties"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    def draw(self, context):
        object = context.object
        layout = self.layout
        c = layout.column()

        if type(object) != type(None):
            if(object.type == 'MESH'):
                material = bpy.context.active_object.active_material
                if (material != None):
                    c.prop(material.shaderList, "shaderList")
                    shaderProps = settings.material_parameter_dict[material.shaderList.shaderList]
                    if material.shaderList.shaderList != 'alDefault.fx':
                        for property in shaderProps:
                            if property == 'BaseTexture':
                                layout.prop_search(material, "BaseTexture", bpy.data, "images")
                            elif property == 'CloudTexture':
                                layout.prop_search(material, "CloudTexture", bpy.data, "images")
                            elif property == 'DetailTexture':
                                layout.prop_search(material, "DetailTexture", bpy.data, "images")
                            elif property == 'CloudNormalTexture':
                                layout.prop_search(material, "CloudNormalTexture", bpy.data, "images")
                            elif property == 'NormalTexture':
                                layout.prop_search(material, "NormalTexture", bpy.data, "images")
                            elif property == 'NormalDetailTexture':
                                layout.prop_search(material, "NormalDetailTexture", bpy.data, "images")
                            elif property == 'GlossTexture':
                                layout.prop_search(material, "GlossTexture", bpy.data, "images")
                            elif property == 'WaveTexture':
                                layout.prop_search(material, "WaveTexture", bpy.data, "images")
                            elif property == 'DistortionTexture':
                                layout.prop_search(material, "DistortionTexture", bpy.data, "images")
                            else:
                                c.prop(material, property)

def createShaderModeOptions():
    mode_options = []

    for index, shader_name in enumerate(settings.material_parameter_dict):
        mode_options.append((shader_name, shader_name, '', '', index))

    return mode_options

class shaderListProperties(bpy.types.PropertyGroup):
    mode_options = createShaderModeOptions()

    shaderList : bpy.props.EnumProperty(
        items=mode_options,
        description="Choose ingame Shader",
        default="alDefault.fx",
    )

class billboardListProperties(bpy.types.PropertyGroup):
    mode_options = [
        ("Disable", "Disable", 'Description WIP', '', 0),
        ("Parallel", "Parallel", 'Description WIP', '', 1),
        ("Face", "Face", 'Description WIP', '', 2),
        ("ZAxis View", "ZAxis View", 'Description WIP', '', 3),
        ("ZAxis Light", "ZAxis Light", 'Description WIP', '', 4),
        ("ZAxis Wind", "ZAxis Wind", 'Description WIP', '', 5),
        ("Sunlight Glow", "Sunlight Glow", 'Description WIP', '', 6),
        ("Sun", "Sun", 'Description WIP', '', 7),
    ]

    billboardMode : bpy.props.EnumProperty(
        items = mode_options,
        description = "billboardMode",
        default="Disable",
    )

def proxy_name_update(self, context):
    if self.ProxyName != self.ProxyName.upper():    #prevents endless recursion
        self.ProxyName = self.ProxyName.upper()

#blender registration
def menu_func_import(self, context):
    self.layout.operator(import_alo.ALO_Importer.bl_idname, text=".ALO Importer")
    self.layout.operator(import_ala.ALA_Importer.bl_idname, text=".ALA Importer")

def menu_func_export(self, context):
    self.layout.operator(export_alo.ALO_Exporter.bl_idname, text=".ALO Exporter")
    self.layout.operator(export_ala.ALA_Exporter.bl_idname, text=".ALA Exporter")

from . import_alo import ALO_Importer
from . import_ala import ALA_Importer
from . export_alo import ALO_Exporter
from . export_ala import ALA_Exporter

classes = validation.classes + (
    skeletonEnumClass,
    billboardListProperties,
    shaderListProperties,
    ALO_Importer,
    ALA_Importer,
    ALO_Exporter,
    ALA_Exporter,
    ALAMO_PT_materialPropertyPanel,
    ALAMO_OT_frame_model,
    ALAMO_OT_fast_preview,
    createConstraintBoneButton,
    ALAMO_PT_ToolsPanel
)

def register():

    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

    bpy.types.Scene.alamo_validation = PointerProperty(type=validation.ALAMO_PG_validation)
    bpy.types.Scene.ActiveSkeleton = PointerProperty(type=skeletonEnumClass)
    bpy.types.Scene.modelFileName  = StringProperty(name="")

    bpy.types.Action.AnimationEndFrame = IntProperty(default=24, min=0)

    bpy.types.EditBone.Visible = BoolProperty(default=True)
    bpy.types.EditBone.EnableProxy = BoolProperty()
    # Bone and EditBone expose the same stored RNA values. These mirrors let
    # preflight inspect proxies without entering Edit Mode or touching the rig.
    bpy.types.Bone.EnableProxy = BoolProperty()
    bpy.types.Bone.ProxyName = StringProperty()
    bpy.types.EditBone.proxyIsHidden = BoolProperty()
    bpy.types.PoseBone.proxyIsHiddenAnimation = BoolProperty()
    bpy.types.EditBone.altDecreaseStayHidden = BoolProperty()
    bpy.types.EditBone.ProxyName = StringProperty(update=proxy_name_update)
    bpy.types.EditBone.billboardMode = bpy.props.PointerProperty(type=billboardListProperties)

    bpy.types.Object.HasCollision = BoolProperty()
    bpy.types.Object.Hidden = BoolProperty()

    bpy.types.Material.BaseTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.DetailTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.NormalDetailTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.NormalTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.GlossTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.WaveTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.DistortionTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.CloudTexture = bpy.props.StringProperty(default='None')
    bpy.types.Material.CloudNormalTexture = bpy.props.StringProperty(default='None')

    bpy.types.Material.shaderList = bpy.props.PointerProperty(type=shaderListProperties)
    bpy.types.Material.Emissive = bpy.props.FloatVectorProperty(soft_min = 0, soft_max = 1, size = 4, default=(0,0,0,0))
    bpy.types.Material.Diffuse = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(1,1,1,0))
    bpy.types.Material.Specular = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(1,1,1,0))
    bpy.types.Material.Shininess = bpy.props.FloatProperty(soft_min=0, soft_max=255, default = 32)
    bpy.types.Material.Colorization = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(1,1,1,0))
    bpy.types.Material.DebugColor = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(0,1,0,0))
    bpy.types.Material.UVOffset = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(0,0,0,0))
    bpy.types.Material.Color = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(1,1,1,1))
    bpy.types.Material.UVScrollRate = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(0,0,0,0))
    bpy.types.Material.DiffuseColor = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=3, default=(0.5,0.5,0.5))
    #shield shader properties
    bpy.types.Material.EdgeBrightness = bpy.props.FloatProperty(soft_min=0, soft_max=255, default=0.5)
    bpy.types.Material.BaseUVScale = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=1)
    bpy.types.Material.WaveUVScale = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=1)
    bpy.types.Material.DistortUVScale = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=1)
    bpy.types.Material.BaseUVScrollRate = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=-0.15)
    bpy.types.Material.WaveUVScrollRate = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=-0.15)
    bpy.types.Material.DistortUVScrollRate = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=-0.25)
    #tree properties
    bpy.types.Material.BendScale = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=0.4)
    #grass properties
    bpy.types.Material.Diffuse1 = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(1,1,1,1))
    #skydome.fx properties
    bpy.types.Material.CloudScrollRate = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=0.001)
    bpy.types.Material.CloudScale = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=1)
    #nebula.fx properties
    bpy.types.Material.SFreq = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=0.002)
    bpy.types.Material.TFreq = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=0.005)
    bpy.types.Material.DistortionScale = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=1)
    #planet.fx properties
    bpy.types.Material.Atmosphere = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(0.5, 0.5, 0.5, 0.5))
    bpy.types.Material.CityColor = bpy.props.FloatVectorProperty(soft_min=0, soft_max=1, size=4, default=(0.5, 0.5, 0.5, 0.5))
    bpy.types.Material.AtmospherePower = bpy.props.FloatProperty(soft_min=-255, soft_max=255, default=1)
    #tryplanar mapping properties
    bpy.types.Material.MappingScale = bpy.props.FloatProperty(soft_min=0, soft_max=255, default=0.1)
    bpy.types.Material.BlendSharpness = bpy.props.FloatProperty(soft_min=0, soft_max=255, default=0.1)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

    del bpy.types.Material.BlendSharpness
    del bpy.types.Material.MappingScale
    del bpy.types.Material.AtmospherePower
    del bpy.types.Material.CityColor
    del bpy.types.Material.Atmosphere
    del bpy.types.Material.DistortionScale
    del bpy.types.Material.TFreq
    del bpy.types.Material.SFreq
    del bpy.types.Material.CloudScale
    del bpy.types.Material.CloudScrollRate
    del bpy.types.Material.Diffuse1
    del bpy.types.Material.BendScale
    del bpy.types.Material.DistortUVScrollRate
    del bpy.types.Material.WaveUVScrollRate
    del bpy.types.Material.BaseUVScrollRate
    del bpy.types.Material.DistortUVScale
    del bpy.types.Material.WaveUVScale
    del bpy.types.Material.BaseUVScale
    del bpy.types.Material.EdgeBrightness
    del bpy.types.Material.DiffuseColor
    del bpy.types.Material.UVScrollRate
    del bpy.types.Material.Color
    del bpy.types.Material.UVOffset
    del bpy.types.Material.DebugColor
    del bpy.types.Material.Colorization
    del bpy.types.Material.Shininess
    del bpy.types.Material.Specular
    del bpy.types.Material.Diffuse
    del bpy.types.Material.Emissive
    del bpy.types.Material.shaderList
    del bpy.types.Material.CloudNormalTexture
    del bpy.types.Material.CloudTexture
    del bpy.types.Material.DistortionTexture
    del bpy.types.Material.WaveTexture
    del bpy.types.Material.GlossTexture
    del bpy.types.Material.NormalTexture
    del bpy.types.Material.NormalDetailTexture
    del bpy.types.Material.DetailTexture
    del bpy.types.Material.BaseTexture
    del bpy.types.Object.Hidden
    del bpy.types.Object.HasCollision
    del bpy.types.EditBone.billboardMode
    del bpy.types.EditBone.ProxyName
    del bpy.types.EditBone.altDecreaseStayHidden
    del bpy.types.PoseBone.proxyIsHiddenAnimation
    del bpy.types.EditBone.proxyIsHidden
    del bpy.types.EditBone.EnableProxy
    del bpy.types.Bone.EnableProxy
    del bpy.types.Bone.ProxyName
    del bpy.types.EditBone.Visible
    del bpy.types.Action.AnimationEndFrame
    del bpy.types.Scene.modelFileName
    del bpy.types.Scene.alamo_validation
    del bpy.types.Scene.ActiveSkeleton

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
