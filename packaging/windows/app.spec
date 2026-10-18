from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parents[1]
datas = [(str(root / 'frontend/dist'), 'frontend/dist'),
         (str(root / 'frontend/src/assets/icon/webIcon.png'), 'backend')]
binaries = []
hiddenimports = collect_submodules('backend.app')
for package in ('psycopg', 'psycopg_binary', 'redis', 'uvicorn', 'opencc', 'litellm', 'tiktoken'):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
a = Analysis([str(root / 'desktop_app.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['pytest', 'matplotlib', 'IPython', 'notebook'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='KikoeruManager',
          console=False, icon=str(root / 'packaging/windows/assets/app.ico'))
coll = COLLECT(exe, a.binaries, a.datas, name='KikoeruManager')
