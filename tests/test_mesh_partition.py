"""Pure Python boundary checks; no Blender installation required."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('mesh_partition', Path(__file__).resolve().parents[1] / 'io_alamo_tools/mesh_partition.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
partition = module.partition_triangles


class PartitionTests(unittest.TestCase):
    def test_exact_16bit_limit_and_cross_boundary_shared_vertices(self):
        vertices = list(range(65537))
        indices = list(range(65535)) + [65534, 65535, 0]
        parts = list(partition(vertices[:65536], indices))
        self.assertEqual(len(parts), 1)
        self.assertEqual(max(parts[0][1]), 65535)
        indices += [65535, 65536, 0]
        parts = list(partition(vertices, indices))
        self.assertEqual([len(v) for v, _ in parts], [65536, 3])
        self.assertEqual([v[i] for v, ids in parts for i in ids], indices)

    def test_collision_node_limit(self):
        vertices = [object(), object(), object()]
        indices = [0, 1, 2] * 16385
        parts = list(partition(vertices, indices, max_triangles=16384))
        self.assertEqual([len(ids) // 3 for _, ids in parts], [16384, 1])
        self.assertTrue(all(v[i] is vertices[index] for v, ids in parts
                            for i, index in zip(ids, [0, 1, 2] * (len(ids) // 3))))


if __name__ == '__main__':
    unittest.main()
