"""Full-detail mesh evaluation and per-corner vertex attributes."""
from contextlib import contextmanager
from array import array
import hashlib
import bpy


@contextmanager
def export_visibility(context):
    """Temporarily include scene collections for explicit export evaluation."""
    collections = [(c, c.hide_viewport) for c in context.scene.collection.children_recursive]
    layers = []
    def snapshot(layer):
        layers.append((layer, layer.exclude, layer.hide_viewport))
        for child in layer.children:
            snapshot(child)
    snapshot(context.view_layer.layer_collection)
    try:
        for collection, hidden in collections:
            if hidden: collection.hide_viewport = False
        for layer, excluded, hidden in layers:
            if excluded: layer.exclude = False
            if hidden: layer.hide_viewport = False
        context.view_layer.update()
        yield
    finally:
        for collection, hidden in collections:
            collection.hide_viewport = hidden
        # Parent exclusion assignments propagate to children: restore top-down.
        for layer, excluded, hidden in layers:
            layer.exclude = excluded
            layer.hide_viewport = hidden


@contextmanager
def evaluated_export_mesh(context, obj, full_quality):
    """The same undeformed, triangulated detail for validation and export."""
    triangle = obj.modifiers.new('Triangulate', 'TRIANGULATE')
    targets = [(m, m.object) for m in obj.modifiers if m.type == 'ARMATURE']
    hidden = obj.hide_viewport
    mesh = None
    try:
        for modifier, target in targets:
            modifier.object = None
        obj.hide_viewport = False
        with export_detail(context.scene, obj, full_quality):
            depsgraph = context.evaluated_depsgraph_get()
            mesh = bpy.data.meshes.new_from_object(
                obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)
        mesh['alamo_use_source_basis'] = (
            obj.data.get('alamo_basis_fingerprint') == basis_fingerprint(mesh))
        yield mesh
    finally:
        for modifier, target in targets:
            modifier.object = target
        obj.hide_viewport = hidden
        obj.modifiers.remove(triangle)
        if mesh is not None:
            bpy.data.meshes.remove(mesh)


def basis_fingerprint(mesh):
    """Invalidate source shading data after any geometry/normal/UV edit."""
    digest = hashlib.sha256()
    for collection, attribute, width, kind in (
        (mesh.vertices, 'co', 3, 'f'), (mesh.loops, 'vertex_index', 1, 'i'),
        (mesh.polygons, 'loop_total', 1, 'i'), (mesh.corner_normals, 'vector', 3, 'f'),
    ):
        buffer = array(kind, [0]) * (len(collection) * width)
        collection.foreach_get(attribute, buffer)
        digest.update(buffer.tobytes())
    primary = mesh.uv_layers.active
    if primary:
        buffer = array('f', [0]) * (len(primary.data)*2)
        primary.data.foreach_get('uv', buffer)
        digest.update(buffer.tobytes())
    return digest.hexdigest()


def source_vector(mesh, name, loop_index):
    source = mesh.attributes.get(name)
    if source is not None and source.domain == 'POINT' and source.data_type == 'FLOAT_VECTOR':
        return source.data[mesh.loops[loop_index].vertex_index].vector.copy()
    return None


def corner_normal(mesh, loop_index):
    if mesh.get('alamo_use_source_basis', False):
        original = source_vector(mesh, 'alamo_source_normal', loop_index)
        if original is not None:
            return original
    normal = mesh.corner_normals[loop_index].vector.copy()
    return normal


def corner_tangents(mesh, loop_index):
    if mesh.get('alamo_use_source_basis', False):
        tangent = source_vector(mesh, 'alamo_source_tangent', loop_index)
        bitangent = source_vector(mesh, 'alamo_source_bitangent', loop_index)
        if tangent is not None and bitangent is not None:
            return tangent, bitangent
    return mesh.loops[loop_index].tangent.copy(), mesh.loops[loop_index].bitangent.copy()


@contextmanager
def export_detail(scene, obj, enabled):
    """Use render visibility/subdivision detail without leaving scene changes.

    Blender still evaluates a viewport depsgraph. Render-only behavior of other
    modifier types (e.g. Geometry Nodes Is Viewport) is not emulated.
    """
    saved = []
    simplify = scene.render.use_simplify
    try:
        if enabled:
            scene.render.use_simplify = False
            for modifier in obj.modifiers:
                if modifier.type == 'ARMATURE':
                    continue
                saved.append((modifier, 'show_viewport', modifier.show_viewport))
                modifier.show_viewport = modifier.show_render
                if modifier.type == 'SUBSURF':
                    saved.append((modifier, 'levels', modifier.levels))
                    modifier.levels = modifier.render_levels
                elif modifier.type == 'MULTIRES':
                    saved.append((modifier, 'levels', modifier.levels))
                    modifier.levels = modifier.render_levels
        yield
    finally:
        for modifier, attribute, value in reversed(saved):
            setattr(modifier, attribute, value)
        scene.render.use_simplify = simplify


def corner_attributes(mesh, loop_index):
    primary = mesh.uv_layers.active
    layers = ([primary] if primary else []) + [layer for layer in mesh.uv_layers if layer != primary]
    if len(layers) > 4:
        raise RuntimeError('ALO supports at most four UV sets; remove unused layers before export')
    uvs = [tuple(layer.data[loop_index].uv) for layer in layers]
    uvs += [(0.0, 0.0)] * (4 - len(uvs))
    color = mesh.color_attributes.active_color
    if color is None:
        rgba = (1.0, 1.0, 1.0, 1.0)
    elif color.domain == 'CORNER':
        rgba = tuple(color.data[loop_index].color)
    elif color.domain == 'POINT':
        rgba = tuple(color.data[mesh.loops[loop_index].vertex_index].color)
    else:
        raise RuntimeError('Unsupported vertex-color domain: ' + color.domain)
    return tuple(uvs), rgba
