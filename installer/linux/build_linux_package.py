"""Erzeugt dist/NetzwerkScanner-<version>-Linux.tar.gz (Quellpaket fuer install_kali.sh).

Aufruf: python installer/linux/build_linux_package.py [zielverzeichnis]
"""

import os
import re
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INCLUDE = ["netscanner", "installer", "tests", "requirements.txt", "run_netscanner.py", "README.md"]


def main(out_dir):
    with open(os.path.join(ROOT, "netscanner", "__init__.py"), encoding="utf-8") as f:
        version = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "NetzwerkScanner-%s-Linux.tar.gz" % version)
    prefix = "NetzwerkScanner-%s/" % version

    def filt(ti):
        if "__pycache__" in ti.name or ti.name.endswith(".pyc"):
            return None
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = "root"
        ti.mode = 0o755 if (ti.isdir() or ti.name.endswith(".sh")) else 0o644
        return ti

    with tarfile.open(out, "w:gz") as tar:
        for item in INCLUDE:
            tar.add(os.path.join(ROOT, item), arcname=prefix + item, filter=filt)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist"))
