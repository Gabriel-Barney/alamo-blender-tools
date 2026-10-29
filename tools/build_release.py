"""Build installable extension and legacy add-on ZIPs using only stdlib."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
import hashlib
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'io_alamo_tools'
DIST = ROOT / 'dist'


def build():
    manifest = tomllib.loads((SOURCE / 'blender_manifest.toml').read_text())
    version = manifest['version']
    DIST.mkdir(exist_ok=True)
    files = {p.name: p.read_bytes() for p in sorted(SOURCE.glob('*.py'))}
    files['LICENSE'] = (ROOT / 'LICENSE').read_bytes()
    files['README.md'] = (ROOT / 'README.md').read_bytes()
    checksums = []
    for kind in ('extension', 'legacy'):
        name = f'alamo-tools-{version}-blender-5.2-{kind}.zip'
        contents = dict(files)
        if kind == 'extension':
            contents['blender_manifest.toml'] = (SOURCE / 'blender_manifest.toml').read_bytes()
        with ZipFile(DIST / name, 'w', compression=ZIP_DEFLATED) as archive:
            for relative, data in sorted(contents.items()):
                path = relative if kind == 'extension' else 'io_alamo_tools/' + relative
                info = ZipInfo(path, date_time=(2026, 10, 27, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
        digest = hashlib.sha256((DIST / name).read_bytes()).hexdigest()
        checksums.append(f'{digest}  {name}')
        print(DIST / name)
    (DIST / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n')


if __name__ == '__main__':
    build()
