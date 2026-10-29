"""Check that upstream operators and registered properties remain available.

This static inventory complements Blender integration tests; it does not prove
behavioral equivalence on its own. Requires the original commit in local Git.
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = '04932aaa40dadbfc37922c42abb5ba7fe690803b'


def inventory(source):
    props, operators = set(), set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = ast.unparse(target)
                if name.startswith('bpy.types.'):
                    props.add(name)
                if name == 'bl_idname' and isinstance(node.value, ast.Constant):
                    operators.add(node.value.value)
    return props, operators


def main():
    old_props, old_ops, new_props, new_ops = set(), set(), set(), set()
    names = subprocess.check_output(['git','ls-tree','-r','--name-only',UPSTREAM,'io_alamo_tools'],cwd=ROOT,text=True).splitlines()
    for name in names:
        if not name.endswith('.py'): continue
        original = subprocess.check_output(['git','show',UPSTREAM+':'+name],cwd=ROOT,text=True)
        props, ops = inventory(original)
        old_props.update(props);old_ops.update(ops)
    for path in (ROOT/'io_alamo_tools').glob('*.py'):
        props, ops = inventory(path.read_text())
        new_props.update(props);new_ops.update(ops)
    assert not old_props-new_props, old_props-new_props
    assert not old_ops-new_ops, old_ops-new_ops
    print(f'Upstream {UPSTREAM}: all {len(old_props)} properties and {len(old_ops)} operators retained')


if __name__ == '__main__': main()
