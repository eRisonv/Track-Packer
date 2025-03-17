# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

a = Analysis(
    ['Voiceover.py'],
    pathex=['G:\\AUDIO SKLEISCHIK\\GUI\\Compile'],
    binaries=[],
    datas=[
        ('ffmpeg.exe', '.'),
        *collect_data_files('tkinterdnd2'),
        ('tcl\\tkdnd2.8', 'tcl\\tkdnd2.8')
    ],
    hiddenimports=['tkinterdnd2'],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Track-Packer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)