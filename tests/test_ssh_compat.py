"""Prueft, dass die Konfigurationssicherung mit alten UND neuen Switches funktioniert.

Startet den SSH-Simulator zweimal im Hintergrund:
  - moderner Switch (curve25519, rsa-sha2, aes-ctr ...)
  - alter Switch, der nur diffie-hellman-group1/14-sha1, ssh-rsa, CBC und hmac-sha1 anbietet
    (Fehlerbild sonst: "Incompatible ssh peer (no acceptable kex algorithm)")

Aufruf: python tests/test_ssh_compat.py
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "sim"))

import paramiko  # noqa: E402

import fake_ssh_switch  # noqa: E402
from netscanner.configbackup import fetch_config  # noqa: E402

USER, PW, ENABLE = "backup", "sim-ssh-pass-1", "sim-enable-1"
FAILED = []


def check(cond, msg):
    print(("OK    " if cond else "FEHLER") + "  " + msg, flush=True)
    if not cond:
        FAILED.append(msg)


class _KexLog(logging.Handler):
    """Merkt sich das ausgehandelte Kex-Verfahren aus dem Paramiko-Protokoll ("Kex: ...")."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.kex = None

    def emit(self, record):
        msg = record.getMessage()
        if msg.startswith("Kex: "):
            self.kex = msg[5:].strip()


def negotiated(port):
    """Mit Paramiko-Standardeinstellungen verbinden und die ausgehandelten Verfahren zurueckgeben."""
    log = logging.getLogger("paramiko.transport")
    handler = _KexLog()
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.DEBUG)
    t = paramiko.Transport(("127.0.0.1", port))
    try:
        t.start_client(timeout=10)
        return handler.kex, t.host_key_type, t.local_cipher, t.local_mac
    finally:
        t.close()
        log.removeHandler(handler)
        log.setLevel(old_level)


def main():
    print("paramiko %s" % paramiko.__version__)
    for legacy, name in ((False, "NEW-SW01"), (True, "OLD-SW01")):
        port = fake_ssh_switch.start(name, USER, PW, ENABLE, legacy=legacy)
        label = "alter Switch" if legacy else "neuer Switch"
        try:
            kex, key, cipher, mac = negotiated(port)
            print("        %s: kex=%s hostkey=%s cipher=%s mac=%s" % (label, kex, key, cipher, mac))
            if legacy:
                check(kex in fake_ssh_switch.LEGACY_KEX, "%s: alte Verfahren werden ausgehandelt" % label)
            else:
                check("sha1" not in kex and key != "ssh-rsa",
                      "%s: moderne Verfahren werden bevorzugt (keine SHA-1-Aushandlung)" % label)
        except Exception as e:
            check(False, "%s: SSH-Aushandlung fehlgeschlagen: %s" % (label, e))
            continue
        cred = {"username": USER, "password": PW, "secret": ENABLE, "port": port}
        try:
            text, dtype = fetch_config("127.0.0.1", cred, "cisco_ios", timeout=15)
            check("hostname %s" % name in text and dtype == "cisco_ios", "%s: Konfiguration gesichert" % label)
        except Exception as e:
            check(False, "%s: Sicherung fehlgeschlagen: %s" % (label, e))

    print()
    if FAILED:
        print("%d Pruefung(en) fehlgeschlagen" % len(FAILED))
        sys.exit(1)
    print("Alle Pruefungen bestanden")


if __name__ == "__main__":
    main()
