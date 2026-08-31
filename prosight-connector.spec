# PyInstaller spec — gera um executável standalone (sem exigir Python no cliente).
# IMPORTANTE: PyInstaller é por-plataforma → para gerar prosight-connector.exe (Windows),
# rode ESTE spec NUMA MÁQUINA WINDOWS:
#   pip install pyinstaller cryptography
#   pyinstaller prosight-connector.spec
# O binário sai em dist/prosight-connector.exe

block_cipher = None

a = Analysis(
    ['prosight_connector.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['cryptography'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='prosight-connector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
