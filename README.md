# ALAMO Tools for Blender 5.2

A plugin that allow reading and writing of ALAMO-Engine model(.alo) and animation(.ala) files.  
Specifically designed to work with Empire at War: Forces of Corruption.

# Getting Started

This is a compatibility update of [Gaukler's original add-on](https://github.com/Gaukler/Blender-ALAMO-Plugin), retaining its MIT license. Version **1.2.2** targets **Blender 5.2+** and has been tested with **Blender 5.2.3 LTS on Windows x64**. Other Blender versions and operating systems have not been runtime-tested.

1. In Blender, disable/remove any older **ALAMO Tools** installation first.
2. Open **Edit > Preferences > Add-ons**, open the menu at the top right, and choose **Install from Disk**.
3. Choose `dist/alamo-tools-1.2.2-blender-5.2-extension.zip` without extracting it, then enable **ALAMO Tools** if needed.
4. Find the `.ALO` and `.ALA` entries under **File > Import / Export**. The **ALAMO** sidebar tab holds skeleton and object settings.

The `legacy.zip` package is an alternative installation format containing the `io_alamo_tools` folder. Install only one package. It also requires Blender 5.2; "legacy" describes the package layout, not support for older Blender versions.

Import a model before importing its animation, then select its armature as **Active Skeleton**. Set **AnimationEndFrame** on the active action before exporting (frames 0 through that frame are included).

## Model compatibility and reliability fixes (1.2.2)

- Supports legacy bone transforms without billboard fields, and skips unknown skeleton/bone records by their declared lengths. Legacy 128-byte and newer 144-byte vertex buffers are both covered by tests.
- Duplicate bone names retain their indexed parent relationships. Mesh attachments target the actual newly created object even when Blender assigns a different name because another object already exists. Ignored lights retain their place in file indices so subsequent mesh attachments stay correct; light data itself is still unsupported and is not preserved on export.
- Proxy names support the full unsigned mini-chunk length: up to 254 ASCII characters plus the terminator. Unknown proxy fields are skipped and malformed required fields are rejected.
- Texture names are decoded without introducing Python escape sequences. Extensionless names and non-DDS extensions are converted correctly to DDS references. Unreadable local images produce warnings while retaining the model and texture reference.
- Consecutive empty submeshes no longer shift polygon material assignments. Invalid vertex counts, triangle indices, bone mappings, attachments and non-finite geometry are rejected with import rollback.

Verified with 67 Blender integration tests (10 new model-compatibility tests) and two pure-Python partition tests. Full Quality export behavior is retained. Unknown records are skipped rather than retained for re-export; this does not add support for every ALAMO variant or certify in-game behavior.

## Import and animation reliability fixes (1.2.1)

- ALO chunk boundaries are checked before creating scene data. Unknown top-level, material and submesh records are skipped by their declared size. Unknown data is not retained for re-export.
- The FOC animation reader validates record boundaries, track offsets, frame rate, bone counts, visibility lengths, and animation buffer lengths before creating an action. Unsupported animated scale is rejected explicitly instead of silently discarded. Duplicate bone names are resolved consistently even when visibility tracks are absent. Padded visibility buffers and unused default quaternions on animated tracks are accepted.
- Failed model/animation imports remove newly created data and restore the previous selection and timeline state. Failed animation creation also restores the original action, slot and pose. Standalone skeleton mismatches report failure; automatic animation discovery skips bad/incompatible clips with a warning and keeps the valid imported model.
- Imported quaternions are normalized and use consistent signs across frames, preventing interpolation flips when rotations cross 180 degrees.
- ALA files are written to a temporary file and replaced atomically only after a complete write. Batch animation filenames are unique even when action names sanitize to the same name or differ only by case. Atomic replacement is per file; a batch is not a single filesystem transaction.

Verified in Blender 5.2.3 with 57 integration tests (13 new reliability tests), two pure-Python partition tests, and the supplied destroyed Star Destroyer plus its complete 811-frame/187-bone animation. All frames passed independent binary motion/visibility comparisons; the 16 meshes and 22,755 triangles are preserved. This remains a Blender/file-format verification, not an in-game certification or a claim of support for every ALAMO variant.

## Export Validation (1.2.0)

Open the 3D Viewport sidebar with **N**, select **ALAMO**, and expand **Export Validation**. Choose Full Quality, Export Hidden Objects and Export Animations, then click **Validate Model**. The panel lists errors, warnings and information; select a row to see a specific fix. **Select / Reveal Object** selects the affected object and material, revealing hidden objects/collections when necessary. Validation itself does not change selection or fix model data.

**Errors block export. Warnings do not.** Every ALO export reruns validation with the current export options before opening an output file. A previous clean report cannot bypass a newly introduced problem. The file browser also offers Validate Model and displays the last report. Run checks again after edits; the report is a snapshot, not a live monitor. Standalone ALA export retains its existing checks; this panel focuses on models and warns about unsupported animated scale when batch animation export is selected.

Checks include missing materials/UVs, empty material slots, more than four UV sets, modifier-generated material/UV problems, normal-map tangent failures, non-finite geometry/attributes, rigid bone weights, skeleton mismatches, invalid attachments, unsupported proxy names, and manifold shadow volumes before and after modifiers. Unapplied transforms, unsupported scale animation, default shaders and texture references produce actionable warnings. Large meshes are informational because the exporter already partitions oversized buffers without decimating them.

Set the optional **Texture Folder** to your mod's texture directory to resolve external filenames. Missing local textures are warnings because textures may legitimately live in game archives or another mod directory. Finding a local filename does not prove the game can load it, and packed/generated Blender images are not embedded into ALO exports.

Full Quality checks the same evaluated, triangulated, undeformed mesh used by export, including render subdivision and modifier visibility. Temporary evaluation meshes and settings are restored even when a check fails. Edit Mode requires switching to Object Mode to include current edits; Pose Mode is supported. Validation runs only on request or export, with no mesh scans in viewport draw callbacks or background polling.

Validation is not a guarantee of in-game correctness: filesystem write failures, unsupported file features and engine-specific behavior still require normal error handling and game testing. The existing output file is preserved when preflight blocks an export. Version 1.2.0 passes 44 Blender integration tests (including 14 dedicated validation tests), plus two pure-Python partition tests.

## Large-mesh export fix (1.1.1)

Oversized material buffers are automatically divided into ALO submeshes after UV, normal, and color splitting. Each buffer stays within the 65,536-vertex index limit. Triangle order, winding, shading attributes, materials and rigid bone mappings are retained; the Blender objects and mesh detail are unchanged. Shadow stitch triangles are partitioned after construction. Collision buffers also respect the signed collision-tree node limit and use triangle IDs local to each submesh. No manual object splitting or decimation is needed for this limit.

Regression checks cover an actual 65,538-vertex export and reimport, the exact 65,536-vertex boundary, shared vertices across boundaries, all four UV channels, vertex colors, normal/tangent data, multiple materials, skinning, shadow stitching and collision triangle mappings. These tests do not constitute in-game validation of this specific ship.

## Full Quality export and original feature audit (1.1.0)

**Full Quality** is enabled by default in the ALO export dialog. It temporarily disables scene Simplify and evaluates modifiers using their render visibility and subdivision levels, then restores the scene settings. Fast Preview changes only viewport display: it does not decimate meshes, resize textures, or reduce export detail. Render-enabled Decimate modifiers still intentionally affect the export. Geometry Nodes and other modifiers still use a viewport dependency graph; render-specific branches such as Is Viewport are not emulated.

The exporter now preserves up to four UV sets, active linear RGBA vertex colors, and the original normal/tangent basis on unchanged imported meshes. Geometry, normal, or primary UV edits invalidate the saved shading basis. Edited meshes use Blender's current shading data. Bounds are calculated from the final exported mesh. Texture references are exported; texture image files remain separate and are neither embedded nor downscaled.

The audit fixed missing shader parameters (including Diffuse1 and CloudScale), the wrong BlendSharpness value, the TerrainMeshBump spelling, material value clamping, per-submesh bone mappings, hidden/excluded collection export, duplicate exports of multiply linked meshes, and corrupted proxy visibility bit patterns. ALO output is written to a temporary file and replaces the destination only after a successful export.

| Original feature | Verification in Blender 5.2.3 |
| --- | --- |
| ALO/ALA import/export and Create Constraint Bone | All five upstream operators retained; exercised in integration tests |
| Scene, object, bone, animation and material controls | All 51 upstream registered properties retained |
| Shader settings and texture references | All 29 configured shaders tested through export and import, including signed/HDR parameter values |
| Static/skinned meshes and multiple materials | Generated round trips, seam tests, and supplied Star Destroyer assets |
| Skeleton hierarchy, attachments, proxies, billboards and visibility | Generated flag/attachment tests and real-model binary comparison |
| Collision and shadow volumes | Generated integration tests plus real-model geometry/count checks; existing manifold rules retained |
| ALA animation and batch export | Quaternion/Euler, partial channels, visibility, fractional FPS and multiple action slots tested |
| Full-detail output independent of preview | Render subdivision/Simplify, render-disabled decimation and byte-identical Fast Preview export tests |
| Invalid exports | Settings restored and existing destination preserved; oversized index buffers automatically partitioned in 1.1.1 |

Animation import now writes sampled curves directly and export evaluates each scene frame once for all bones. Numeric imported channels use linear interpolation between the stored frame samples; proxy visibility uses constant interpolation. No frames are dropped.

The inventory baseline is upstream commit `04932aaa40dadbfc37922c42abb5ba7fe690803b`. Retaining an operator/property is an inventory check, complemented by the behavioral tests above; it is not a claim that every possible game asset has been tested.

Full Quality rejects blended vertex weights because this exporter supports rigid single-bone skinning only. Disabling Full Quality retains the original strongest-weight export behavior. Each submesh may contain at most 65,536 serialized vertices after UV/normal/color splits; larger buffers are automatically partitioned, and are never silently reduced. At most four UV sets and one active color attribute are written. Unknown shaders still fall back to alDefault on import, and arbitrary shader parameters, lights and other unsupported ALO chunks are not preserved. These are not a universal lossless-file conversion guarantee.

## Fast Preview (1.0.2)

Use **ALAMO > Fast Preview**, or search **ALAMO Fast Preview** with F3, for lightweight solid shading with overlays, gizmos, cavity, shadows, and X-ray disabled. Click **Restore Editing View** to restore the previous display settings, including after saving and reopening the blend. The original settings are stored per viewport area in the screen; restore before rearranging/splitting the screen layout. An optional **Fast Preview** checkbox is also available on ALO import. It is off by default.

This is a one-shot viewport preset: it adds no redraw handlers, background polling, or geometry modifiers. It does not decimate meshes, disable animation, modify textures, or change exported data. Tests verify byte-identical ALO exports with the preset on and off. It is most useful when switching from Material Preview/Rendered mode or when overlays are costly; gains in an already simple solid view can be small.

On the supplied Star Destroyer, a scripted 3150 x 1832 OpenGL redraw benchmark on an RX 9070 XT measured roughly 3.8-4.0 ms with normal overlays/8-sample AA and 3.6 ms with overlays off/FXAA. These are scripted redraw timings, **not measured mouse-orbit FPS**; severe interactive stutter was not reproduced. FXAA is a separate Blender-wide preference under Preferences > Viewport > Anti-Aliasing; the plug-in toggle does not change global preferences.

## Viewport clipping fix (1.0.1)

ALO imports now frame the visible model and adjust the viewport clipping range to its size. This prevents large ships from being cut off by the default 1,000-unit far plane during zooming or orbiting. Hidden collision/shadow meshes and proxy bones are excluded from framing. Game-space geometry and transforms are unchanged.

For an already imported model, choose its **Active Skeleton**, then click **Frame ALAMO Model** in the **ALAMO** sidebar (or search for it with F3). New imports have **Frame Imported Model** enabled by default; disable it to retain your current view. Camera views are not reframed.

## Compatibility changes

- Uses layered Actions and the active object's action slot instead of the removed `Action.fcurves` API. Batch export handles matching skeleton slots, skips unrelated object actions, and restores the original action/slot.
- Supports quaternion, Euler, and axis-angle rotation tracks and partially keyed vector channels when writing the sampled animation format.
- Uses current mesh corner normals, preserves imported custom normals, and keeps normal/tangent seams when deduplicating export vertices. Removes the obsolete `use_auto_smooth` check.
- Replaces obsolete viewport operator overrides with direct object visibility updates. Import only hides/merges objects it created and preserves the current render engine.
- Fixes fractional frame rates, constant bone translation import, portable file paths, material node output, RNA property cleanup, and temporary export mesh/modifier cleanup.
- Adds a modern extension manifest, reproducible release packaging, and background Blender integration tests.

## Validation and remaining limits

Sixty-seven integration tests pass in Blender 5.2.3, covering registration/re-registration; static and skinned model round trips; split normals and normal-mapped materials; collision and shadow geometry; quaternion/Euler animations, partial channels and proxy visibility; fractional FPS; multiple action slots; export validation; legacy model records; and cleanup after invalid imports and exports. Two pure-Python tests check mesh partitioning. The extension manifest and release ZIP are checked with Blender's extension validator.

The suite uses generated assets and a separate independent binary decoder. The supplied imperial_i-class_star_destroyer.alo additionally preserves all 21 meshes and 47,568 triangles, all material values/texture references, UVs/colors, bone hierarchy/flags and attachment/proxy data. Normal, vertex and rest-matrix differences are checked numerically; shadow stitching is rebuilt and its positions checked within 0.001 game units. Fast Preview produces byte-identical model exports. The destroyed variant preserves all 16 meshes and 22,755 triangles. Its 811-frame, 187-bone DIE_00 clip passed independent binary comparisons at every frame for translation, rotation and proxy visibility, plus a Blender pose round trip at five sampled frames. Maximum local translation error was approximately 0.00230 game units and angular error 0.000035 radians; maximum sampled global pose translation error was 0.0103 game units. Optional local-asset results are saved in tests/output/*_audit.json; game assets are not included in the release. The output has **not been verified inside Empire at War**. Check a copy of a representative model and animation in your mod before replacing production assets. Original format limits still apply: Forces of Corruption animations only, no animated scale, rigid single-bone vertex weighting, and the existing material/shadow-volume restrictions. Constraint/NLA-driven motion without corresponding bone animation channels is not automatically baked.

## Building and testing

Build both ZIPs and SHA-256 checksums using Python 3.11 or newer:

```powershell
python tools/build_release.py
```

Run the integration tests using Blender 5.2 (test artifacts are written to `tests/output/`):

```powershell
python tools/check_upstream_parity.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_fidelity.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_validation.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_reliability.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_model_compatibility.py
python tests/test_mesh_partition.py
blender --background --factory-startup --command extension validate dist/alamo-tools-1.2.2-blender-5.2-extension.zip
```

The tests reset their background Blender session to an empty scene. Do not run the test script inside an interactive session with unsaved work.

## Supported formats 

The exporter supports the .alo model format used in both Empire at War and it's addon Forces of Corruption.  
The animation format differs between the base game and the addon. Only the latter is supported.  
If necessary animations can be converted with an external [tool](https://modtools.petrolution.net/tools/AnimationConverter).

# Exporting Objects 

When exporting or importing it's a good idea to open the Blender [console](https://docs.blender.org/manual/en/latest/advanced/command_line/introduction.html). 
Warnings and errors are displayed here.   
Common issues when exporting include missing UVs or vertex weights when using shaders that need them and not assigning a material.  

## Transform

Every object should remain without an object level transformation, so the origin should remain at the center without rotation
and scaling.  
Object transforms will be ignored when exporting. To move an object to a specific location it has to be attached to a bone.  
This is done by using a [child of constraint](https://docs.blender.org/manual/en/latest/animation/constraints/relationship/child_of.html).  
To automate this process the 'Create Constraint Bone' button can be used. An active armature has to be selected and the selected 
object must not have a child of constraint. This will create a new bone in the active skeleton at using the transform of the object. The object will be constrained to the bone and the transform will be reset. As a result the object should remain at the same position and rotation. 

## Shadow meshes

Shadow meshes are used ingame to render shadows using [shadow volumes](https://en.wikipedia.org/wiki/Shadow_volume).  
A mesh is considered a shadow mesh when it uses the corresponding shader: 'MeshShadowVolume.fx' or 'RSkinShadowVolume.fx'.  
Shadow volumes have strict requirements. They need to be water tight, otherwise artifacts will occur.  
Furthermore the exporter requires the mesh to be manifold.
When trying to export a non manifold shadow mesh the exporter will fail 
with an appropriate error message and automatically select the problematic geometry.  
The problematic geometry can be manually selected using a Blender 
[function](https://docs.blender.org/manual/en/latest/modeling/meshes/selecting.html#select-all-by-trait).  
Note that the exporter is stricter than the game when it comes to shadow meshes. 
That means imported models might not be exportable without manually fixing the shadow mesh. 
However it also means that an exported shadow mesh should not be able to cause artifacts ingame.  

# UI

## Sidebar

The sidebar(default hotkey: 'N') offers an ALAMO properties option. 
This lists the file format specific properties of the active object.  
The avaible properties change depending on the mode and object type.

Scene propierties(always avaible): 
 - ActiveSkeleton: Files can only contain a single skeleton. Choose the skeleton that is used when exporting
 - AnimationEndFrame: per action, length of the animation

Object properties(Mesh in object-mode): 
 - HasCollision: treated as collider ingame
 - Hidden: invisible ingame
 
Bone properties (Bone in edit-mode): 
 - Visible: Visibility of attached object
 - EnableProxy: bone is a proxy to spawn effects ingame, enables additional options: 
 - proxyIsHidden: flag that determines if the proxy is initially hidden
 - altDecreaseStayHidden: prevents proxies to become visible when the alt level decreases
 - ProxyName: name of the effect to be attached to the proxy
 
 Bone properties (Bone in pose-mode):
  - proxyIsHiddenAnimation: animated visibility of the proxy, when hovering over it with mouse: press 'I' to set keyframe 
 
 ## Alamo material properties

Section in the Material Properties tab dedicated to shader settings, including textures.  
The shader to be used ingame can be selected from the shaderList. The avaible options change depending on the shader.  
Most options can be left at default values, however textures should be chosen.  
To do this load the texture into Blender as an image. The texture options offer an dropdown menu with all avaible images.  
Note that only the texture name is written to the file, the texture itself must be placed in the appropriate 
mod directory in order to be found by the game.  

# Animations 

When exporting an animation the current animation from the 3D-view is exported. 
Multiple animations can be stored in Blender using the [action editor](https://docs.blender.org/manual/en/latest/editors/dope_sheet/action.html).  
Animations can be exported in bulk by checking the 'Export Animations' property when exporting a model. This will export every 
compatible action slot into a separate animation file. Multi-slot actions include the slot identifier in the filename.

Scaling in animations is unsupported at the moment. 

# Adding custom shaders 

All shader settings are stored in 'settings.py'.  
The 'material_parameter_dict' contains a shader name as a key. The corresponding item is a list of strings. 
Every string is a shader parameter. Every paramater name needs to match the shaders HLSL parameter name exactly.  
If a new parameter is used that is not yet used by another shader it has to be added to Blenders material properties.  
This is done in 'register()' function in '__init__.py'. Adding the property is a single line of code, for reference look at the 
existing code and the Blender [documentation](https://docs.blender.org/api/current/bpy.props.html). 

Every shader also needs a vertex format. This tells the engine what vertex data to pass to the vertex shader. 
This is implemented with a second dictionary called 'vertex_format_dict', with the key being the shader name and the item the formats name as a string.  

If a shader uses normal mapping its name has to be added to the 'bumpMappingList' list.  

# References 

[Breakdown](https://modtools.petrolution.net/docs/AlaFileFormat) of the Alamo Object File Format.  
[Breakdown](https://modtools.petrolution.net/docs/AloFileFormat) of the Alamo Animation File Format.
