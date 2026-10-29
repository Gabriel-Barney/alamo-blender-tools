"""Frame ALAMO geometry without changing its game-space scale or transforms."""
import math
import json

from mathutils import Vector


_PREVIEW_KEY = 'alamo_fast_preview_v1'
_PREVIEW_SETTINGS = (
    ('shading', 'type', 'SOLID'),
    ('shading', 'show_shadows', False),
    ('shading', 'show_cavity', False),
    ('shading', 'show_xray', False),
    ('overlay', 'show_overlays', False),
    (None, 'show_gizmo', False),
)


def _preview_states(screen):
    try:
        return json.loads(screen.get(_PREVIEW_KEY, '{}'))
    except (ValueError, TypeError):
        return {}


def _area_key(area):
    return str(list(area.id_data.areas).index(area))


def is_fast_preview(area):
    return area is not None and area.type == 'VIEW_3D' and _area_key(area) in _preview_states(area.id_data)


def set_fast_preview(context, enabled):
    """A one-shot display preset; no timers, draw handlers, or geometry changes.

    Store the original display settings on the screen so they can be restored
    even after saving and reopening the blend file. Area indices are local to
    that screen; a non-viewport area is never changed on restore.
    """
    changed = False
    for area in viewport_areas(context):
        screen = area.id_data
        states = _preview_states(screen)
        key = _area_key(area)
        space = area.spaces.active
        if enabled:
            if key not in states:
                states[key] = [getattr(getattr(space, group) if group else space, prop)
                               for group, prop, value in _PREVIEW_SETTINGS]
            for group, prop, value in _PREVIEW_SETTINGS:
                setattr(getattr(space, group) if group else space, prop, value)
        else:
            old = states.pop(key, None)
            if old is None:
                continue
            for (group, prop, value), previous in zip(_PREVIEW_SETTINGS, old):
                setattr(getattr(space, group) if group else space, prop, previous)
        if states:
            screen[_PREVIEW_KEY] = json.dumps(states)
        elif _PREVIEW_KEY in screen:
            del screen[_PREVIEW_KEY]
        area.tag_redraw()
        changed = True
    return changed


def model_bounds(context, objects):
    depsgraph = context.evaluated_depsgraph_get()
    corners = []
    for obj in objects:
        if obj.type != 'MESH' or not obj.visible_get(view_layer=context.view_layer):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        if not evaluated.data.vertices:
            continue
        corners.extend(evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box)
    if not corners:
        return None
    lower = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    upper = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    return (lower + upper) * 0.5, max((upper - lower).length * 0.5, 0.001)


def viewport_areas(context):
    # Prefer the invoking viewport. File-browser imports may have a temporary
    # window, so fall back to the main window displaying this scene.
    if context.area is not None and context.area.type == 'VIEW_3D':
        return [context.area]
    if context.screen is not None:
        areas = [a for a in context.screen.areas if a.type == 'VIEW_3D']
        if areas:
            return areas
    for window in context.window_manager.windows:
        if window.scene == context.scene:
            areas = [a for a in window.screen.areas if a.type == 'VIEW_3D']
            if areas:
                return areas
    return []


def frame_model(context, objects):
    bounds = model_bounds(context, objects)
    if bounds is None:
        return False
    center, radius = bounds
    changed = False
    for area in viewport_areas(context):
        space = area.spaces.active
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None or space.region_3d is None:
            continue
        # Fit a bounding sphere, so rotating cannot push a corner behind the
        # far plane. Leave room to zoom out, without an extreme depth ratio.
        aspect = max(region.width, 1) / max(region.height, 1)
        half_fov = math.atan(16.0 / max(space.lens, 1.0) * min(1.0, 1.0 / aspect))
        distance = radius * 1.15 / math.sin(half_fov)
        space.clip_start = max(0.001, min(0.1, radius / 10000.0))
        space.clip_end = max(1000.0, distance + radius * 100.0)
        views = list(space.region_quadviews) or [space.region_3d]
        for view in views:
            if view.view_perspective == 'CAMERA':
                continue
            view.view_location = center
            view.view_distance = distance
            changed = True
        area.tag_redraw()
    return changed
