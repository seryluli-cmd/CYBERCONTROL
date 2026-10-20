# -*- mode: python ; coding: utf-8 -*-

import os

# La base va cifrada con la clave de clave_base.py (que NO está en git: la receta de armado la copia
# a esta carpeta antes de correr PyInstaller; ver CLAUDE.md, "La base de datos va cifrada"). Sin ese
# archivo el .exe sale igual, pero NO cifra: avisarlo fuerte para que nadie lo instale sin querer.
if not os.path.exists(os.path.join(SPECPATH, 'clave_base.py')):
    print()
    print('*' * 78)
    print('*** ATENCION: no hay clave_base.py. Este CyberBios.exe NO CIFRA la base de datos.')
    print('*' * 78)
    print()


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    # sqlcipher3: el SQLite con cifrado (motor_sql.py lo importa dentro de un try, así que se lo nombra acá).
    hiddenimports=['sqlcipher3', 'sqlcipher3.dbapi2'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    # Con el nombre con que lo usa el dueño (antes salía Kiosko.exe y había que
    # renombrarlo a mano en cada armado; revisión del 2026-10-17).
    name='CyberBios',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icono.ico'],
)
