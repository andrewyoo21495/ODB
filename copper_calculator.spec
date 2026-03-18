# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Copper Ratio Calculator.

Build with:
    pip install pyinstaller
    pyinstaller copper_calculator.spec
"""

import os
import sys

block_cipher = None

# Collect all src/ modules needed
src_path = os.path.join(os.path.dirname(os.path.abspath(SPECPATH)), 'src')

a = Analysis(
    ['copper_calculator_app.py'],
    pathex=[os.path.dirname(os.path.abspath(SPECPATH))],
    binaries=[],
    datas=[],
    hiddenimports=[
        'src',
        'src.models',
        'src.odb_loader',
        'src.cache_manager',
        'src.copper_reporter',
        'src.visualizer',
        'src.visualizer.copper_utils',
        'src.visualizer.layer_renderer',
        'src.visualizer.symbol_renderer',
        'src.visualizer.renderer',
        'src.visualizer.fid_lookup',
        'src.visualizer.component_overlay',
        'src.parsers',
        'src.parsers.matrix_parser',
        'src.parsers.feature_parser',
        'src.parsers.profile_parser',
        'src.parsers.font_parser',
        'src.parsers.stephdr_parser',
        'src.parsers.symbol_parser',
        'src.parsers.base_parser',
        'src.parsers.symbol_resolver',
        'src.parsers.misc_parser',
        # Required by matplotlib TkAgg backend
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends._backend_tk',
        # Numerical
        'numpy',
        'openpyxl',
        'shapely',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unused heavy modules to reduce exe size
        'scipy',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'IPython',
        'notebook',
        'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CopperCalculator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window (GUI-only)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',      # Uncomment and provide an .ico file if desired
)
