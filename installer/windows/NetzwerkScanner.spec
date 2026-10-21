# PyInstaller-Spezifikation fuer NetzwerkScanner.exe (onedir)
# Aufruf aus dem Projektverzeichnis:  pyinstaller installer\windows\NetzwerkScanner.spec
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = [
    (os.path.join(ROOT, "netscanner", "templates"), "netscanner/templates"),
    (os.path.join(ROOT, "netscanner", "static"), "netscanner/static"),
    (os.path.join(ROOT, "netscanner", "data"), "netscanner/data"),
]
binaries = []
hiddenimports = []
for pkg in ("pysnmp", "pyasn1", "netmiko", "ntc_templates", "textfsm", "paramiko"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("reportlab")

a = Analysis(
    [os.path.join(ROOT, "run_netscanner.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["waitress", "openpyxl", "reportlab.graphics.barcode.common"],
    excludes=["tkinter", "matplotlib", "numpy", "PIL.ImageQt", "pymupdf", "fitz", "snmpsim", "pysmi"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NetzwerkScanner",
    console=True,
    icon=os.path.join(SPECPATH, "netscanner.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NetzwerkScanner")
