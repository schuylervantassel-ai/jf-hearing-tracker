# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Jamestown Hearing Tracker.
Build:  pyinstaller hearingtracker.spec
Output: dist/Hearing Tracker.app  (macOS)
"""

import os

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # Bundle the Jinja2 templates folder
        ("templates", "templates"),
        # Bundle comit.py so it can be imported at runtime
        ("comit.py", "."),
    ],
    hiddenimports=[
        "feedparser",
        "openpyxl",
        "openpyxl.cell._writer",
    ],
    hookspath=[],
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
    [],
    exclude_binaries=True,
    name="Hearing Tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # no terminal window on macOS
    icon=None,       # set to "icon.icns" if you add an icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Hearing Tracker",
)

# macOS .app bundle
app = BUNDLE(
    coll,
    name="Hearing Tracker.app",
    icon=None,          # set to "icon.icns" to add a custom icon
    bundle_identifier="org.jamestown.hearingtracker",
    info_plist={
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleName": "Hearing Tracker",
        "LSUIElement": False,   # show in Dock
        "NSHighResolutionCapable": True,
    },
)
