"""Access animation channels belonging to one object in slotted Actions."""


def action_curves(action, slot):
    if action is None or slot is None:
        return
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type == 'KEYFRAME':
                bag = strip.channelbag(slot)
                if bag is not None:
                    yield from bag.fcurves


def object_curves(obj):
    data = obj.animation_data
    if data is not None:
        yield from action_curves(data.action, data.action_slot)


def bone_tracks(armature):
    """Count bone tracks, not curve components (Euler and partial keys work)."""
    paths = {curve.data_path for curve in object_curves(armature)}
    translation, rotation = [], []
    for pose in armature.pose.bones:
        if pose.name == 'Root':
            continue
        if pose.path_from_id('location') in paths:
            translation.append(pose.name)
        if any(pose.path_from_id(prop) in paths for prop in
               ('rotation_quaternion', 'rotation_euler', 'rotation_axis_angle')):
            rotation.append(pose.name)
    return translation, rotation


def matching_slots(action, armature):
    """Only slots whose bone channels can be evaluated on this skeleton."""
    prefixes = tuple(pose.path_from_id() + '.' for pose in armature.pose.bones)
    for slot in action.slots:
        if slot.target_id_type != 'OBJECT':
            continue
        paths = [curve.data_path for curve in action_curves(action, slot)]
        bone_paths = [path for path in paths if path.startswith('pose.bones[')]
        if bone_paths and all(path.startswith(prefixes) for path in bone_paths):
            yield slot


def export_jobs(armature, model_path):
    """Choose deterministic, case-insensitively unique batch filenames."""
    import os
    import bpy
    stem = os.path.splitext(model_path)[0]
    used = set()
    jobs = []
    for action in bpy.data.actions:
        slots = list(matching_slots(action, armature))
        for slot in slots:
            suffix = '_' + slot.identifier if len(slots) > 1 else ''
            name = bpy.path.clean_name(action.name + suffix)
            candidate = stem + '_' + name + '.ALA'
            number = 2
            while candidate.casefold() in used:
                candidate = stem + '_' + name + '_' + str(number) + '.ALA'
                number += 1
            used.add(candidate.casefold())
            jobs.append((candidate, action, slot))
    return jobs
