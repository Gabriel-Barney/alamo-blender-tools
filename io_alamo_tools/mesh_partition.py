"""Partition serialized triangles without changing their corner attributes."""


def partition_triangles(vertices, indices, max_vertices=65536, max_triangles=None):
    """Yield local vertex/index buffers, retaining triangle order and winding.

    Vertices are already split for shading/UV seams. Reuse those records verbatim;
    only duplicate references across buffer boundaries, never weld or simplify.
    """
    if len(indices) % 3:
        raise ValueError('Expected triangulated index data')
    if max_vertices < 3 or (max_triangles is not None and max_triangles < 1):
        raise ValueError('Invalid triangle buffer limits')
    if len(vertices) <= max_vertices and (max_triangles is None or len(indices) <= max_triangles * 3):
        yield vertices, indices
        return
    local_vertices, local_indices, remap = [], [], {}
    for offset in range(0, len(indices), 3):
        triangle = indices[offset:offset + 3]
        added = len(set(triangle).difference(remap))
        if local_indices and (len(local_vertices) + added > max_vertices or
                              (max_triangles is not None and len(local_indices) >= max_triangles * 3)):
            yield local_vertices, local_indices
            local_vertices, local_indices, remap = [], [], {}
        for index in triangle:
            if index not in remap:
                remap[index] = len(local_vertices)
                local_vertices.append(vertices[index])
            local_indices.append(remap[index])
    if local_indices:
        yield local_vertices, local_indices
