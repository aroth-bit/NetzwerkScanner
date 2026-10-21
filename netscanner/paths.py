"""Pfade fuer Programmressourcen und Nutzdaten (Windows / Linux / PyInstaller)."""

import os
import sys

IS_WINDOWS = os.name == "nt"


def resource_dir() -> str:
    """Verzeichnis mit templates/ und static/ (auch im PyInstaller-Bundle)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "netscanner")
    return os.path.dirname(os.path.abspath(__file__))


def default_data_dir() -> str:
    env = os.environ.get("NETSCANNER_DATA")
    if env:
        return env
    if IS_WINDOWS:
        return os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "NetzwerkScanner")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return "/var/lib/netscanner"
    return os.path.join(os.path.expanduser("~"), ".netscanner")


_data_dir = None


def set_data_dir(path: str) -> None:
    global _data_dir
    _data_dir = os.path.abspath(path)


def data_dir() -> str:
    global _data_dir
    if _data_dir is None:
        _data_dir = default_data_dir()
    os.makedirs(_data_dir, exist_ok=True)
    return _data_dir


def data_path(*parts: str) -> str:
    p = os.path.join(data_dir(), *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p
