"""Simulierter SSH-Switch (Cisco-IOS-Verhalten) zum Testen der Konfigurationssicherung.

  python fake_ssh_switch.py <benutzer> <passwort> <enable> 127.0.0.11:2222=CORE-SW01 127.0.0.13:2222=ACC-SW02

Jeder Abruf von 'show running-config' liefert eine leicht geaenderte Konfiguration (Zaehler),
damit Versionen und Vergleich getestet werden koennen.
"""

import socket
import sys
import threading

import paramiko

HOST_KEY = paramiko.RSAKey.generate(2048)
CALLS = {}


def config_text(name):
    CALLS[name] = CALLS.get(name, 0) + 1
    n = CALLS[name]
    lines = ["Building configuration...", "", "Current configuration : 4242 bytes", "!",
             "version 15.2", "hostname %s" % name, "!", "enable secret 9 $9$xxxxxxxxxxxxxx", "!"]
    for i in range(1, 9):
        lines += ["interface GigabitEthernet1/0/%d" % i, " description %s" % (
            "Server-%d (Rev %d)" % (i, n) if i == 1 else "Port %d" % i),
                  " switchport access vlan %d" % (10 if i < 5 else 20), " switchport mode access", "!"]
    if n % 2 == 0:
        lines += ["ip access-list standard MGMT", " permit 10.10.30.0 0.0.0.255", "!"]
    lines += ["snmp-server community ******** RO", "line vty 0 15", " transport input ssh", "!", "end"]
    return "\r\n".join(lines)


class Server(paramiko.ServerInterface):
    def __init__(self, user, pw):
        self.user, self.pw = user, pw
        self.event = threading.Event()

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username, password) == (self.user, self.pw) else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, *a):
        return True

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True


def session(chan, name, enable_pw):
    mode = ">"
    chan.send("\r\n%s%s" % (name, mode))
    buf = ""
    want_pw = False
    while True:
        data = chan.recv(1024)
        if not data:
            return
        for ch in data.decode("utf-8", "ignore"):
            if ch in "\r\n":
                if ch == "\n" and buf == "" and getattr(chan, "_last_cr", False):
                    chan._last_cr = False
                    continue
                chan._last_cr = ch == "\r"
                line, buf = buf.strip(), ""
                if want_pw:
                    want_pw = False
                    if line == enable_pw:
                        mode = "#"
                        chan.send("\r\n%s#" % name)
                    else:
                        chan.send("\r\n% Access denied\r\n%s>" % name)
                    continue
                chan.send("\r\n")
                if line == "":
                    pass
                elif line == "enable":
                    chan.send("Password: ")
                    want_pw = True
                    continue
                elif line.startswith("terminal"):
                    pass
                elif line in ("show running-config", "show run"):
                    if mode != "#":
                        chan.send("                ^\r\n% Invalid input detected at '^' marker.\r\n")
                    else:
                        chan.send(config_text(name) + "\r\n")
                elif line in ("exit", "logout"):
                    chan.close()
                    return
                else:
                    chan.send("% Invalid input detected at '^' marker.\r\n")
                chan.send("%s%s" % (name, mode))
            else:
                buf += ch
                if not want_pw:
                    chan.send(ch)  # Echo wie ein echtes Geraet


def serve(addr, port, name, user, pw, enable_pw):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((addr, port))
    s.listen(20)
    print("SSH-Simulator %s auf %s:%d" % (name, addr, port), flush=True)
    while True:
        client, _ = s.accept()
        threading.Thread(target=handle, args=(client, name, user, pw, enable_pw), daemon=True).start()


def handle(client, name, user, pw, enable_pw):
    t = paramiko.Transport(client)
    t.add_server_key(HOST_KEY)
    srv = Server(user, pw)
    try:
        t.start_server(server=srv)
        chan = t.accept(20)
        if chan is None:
            return
        srv.event.wait(10)
        session(chan, name, enable_pw)
    except Exception:
        pass
    finally:
        t.close()


if __name__ == "__main__":
    user, pw, enable_pw = sys.argv[1:4]
    for spec in sys.argv[4:]:
        hp, name = spec.split("=")
        h, p = hp.split(":")
        threading.Thread(target=serve, args=(h, int(p), name, user, pw, enable_pw), daemon=True).start()
    threading.Event().wait()
