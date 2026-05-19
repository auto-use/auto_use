# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['_embedded_resources', 'interception', 'comtypes', 'comtypes.client', 'comtypes.stream', 'win32api', 'win32con', 'win32gui', 'pydoc', 'Auto_Use.windows_use.llm_provider.openrouter.view', 'Auto_Use.windows_use.llm_provider.groq.view', 'Auto_Use.windows_use.llm_provider.openai.view', 'Auto_Use.windows_use.llm_provider.anthropic.view', 'Auto_Use.windows_use.llm_provider.google.view']
datas += collect_data_files('webview')
hiddenimports += collect_submodules('pywinauto')
hiddenimports += collect_submodules('webview')
hiddenimports += collect_submodules('flask')
tmp_ret = collect_all('Auto_Use')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\admin\\Desktop\\autouse_public_version\\Auto-Use\\app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pytest', 'scipy', 'networkx'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AutoUse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\admin\\Desktop\\autouse_public_version\\Auto-Use\\auto_use.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AutoUse',
)
