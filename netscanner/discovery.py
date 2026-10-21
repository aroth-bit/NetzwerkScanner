"""Host-Erkennung: Ping-Sweep, TCP-Fallback, nmap, lokale ARP-Tabelle, DNS, NetBIOS."""

import ipaddress
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import xml.etree.ElementTree as ET

from .paths import IS_WINDOWS
from .snmp import normalize_mac

_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def _run(cmd, timeout):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                          creationflags=_NO_WINDOW)


# ---------------------------------------------------------------- Zielbereiche

def parse_targets(entries):
    """CIDR, Bereich (10.0.0.1-50 / 10.0.0.1-10.0.0.50) oder Einzel-IP -> Liste von ip_network/Tupeln."""
    nets = []
    for raw in entries or []:
        for e in re.split(r"[\s,;]+", str(raw).strip()):
            if not e or e.startswith("#"):
                continue
            try:
                if "-" in e:
                    a, b = e.split("-", 1)
                    start = ipaddress.ip_address(a)
                    end = ipaddress.ip_address(b) if "." in b else ipaddress.ip_address(a.rsplit(".", 1)[0] + "." + b)
                    nets.append(("range", int(start), int(end)))
                else:
                    nets.append(("net", ipaddress.ip_network(e, strict=False)))
            except ValueError:
                raise ValueError("Ungueltiger Eintrag: %s" % e)
    return nets


def expand_targets(include, exclude=None, limit=70000):
    excl = set()
    for t in parse_targets(exclude):
        excl |= set(_iter(t))
    out, seen = [], set()
    for t in parse_targets(include):
        for ip in _iter(t):
            if ip in excl or ip in seen:
                continue
            seen.add(ip)
            out.append(ip)
            if len(out) > limit:
                raise ValueError("Zu viele Ziel-Adressen (> %d). Bitte Bereiche einschraenken." % limit)
    return out


def _iter(t):
    if t[0] == "range":
        for i in range(t[1], t[2] + 1):
            yield str(ipaddress.ip_address(i))
    else:
        net = t[1]
        if net.version != 4:
            return
        hosts = list(net.hosts()) if net.num_addresses > 2 else list(net)
        for h in hosts:
            yield str(h)


# ---------------------------------------------------------------- Ping / TCP

def ping(ip, timeout_ms=800):
    """-> TTL (int) bei Antwort, sonst None."""
    if IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_ms)), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(round(timeout_ms / 1000.0)))), "-n", ip]
    try:
        r = _run(cmd, timeout=timeout_ms / 1000.0 + 3)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = r.stdout.decode("utf-8", "ignore") if r.stdout else ""
    m = re.search(r"ttl[=:\s]+(\d+)", out, re.I)
    if r.returncode == 0 and m:
        return int(m.group(1))
    return None


def tcp_probe(ip, ports, timeout=0.6):
    """-> Liste offener TCP-Ports."""
    open_ports = []
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            if s.connect_ex((ip, int(p))) == 0:
                open_ports.append(int(p))
        except OSError:
            pass
        finally:
            s.close()
    return open_ports


_REFUSED = (10061, 111, 61)  # Windows / Linux / macOS: Verbindung abgelehnt -> Host lebt


def tcp_alive(ip, ports, timeout=0.6):
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            rc = s.connect_ex((ip, int(p)))
            if rc == 0 or rc in _REFUSED:
                return True
        except OSError:
            pass
        finally:
            s.close()
    return False


def os_from_ttl(ttl):
    if not ttl:
        return ""
    if ttl <= 64:
        return "Linux/Unix/ESXi"
    if ttl <= 128:
        return "Windows"
    return "Netzwerkgeraet"


# ---------------------------------------------------------------- nmap

def nmap_path():
    p = shutil.which("nmap")
    if p:
        return p
    if IS_WINDOWS:
        for c in (r"C:\Program Files (x86)\Nmap\nmap.exe", r"C:\Program Files\Nmap\nmap.exe"):
            if os.path.exists(c):
                return c
    return None


def nmap_sweep(targets, timeout=3600):
    """nmap -sn auf eine Liste von Zielen. -> {ip: {mac, vendor, hostname}}"""
    exe = nmap_path()
    if not exe:
        return None
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(targets))
        lst = f.name
    try:
        r = _run([exe, "-sn", "-PE", "-PS22,80,135,443,445,3389", "-PA80,443", "-n", "--max-retries", "1",
                  "-T4", "-oX", "-", "-iL", lst], timeout=timeout)
    finally:
        os.unlink(lst)
    res = {}
    try:
        root = ET.fromstring(r.stdout.decode("utf-8", "ignore"))
    except ET.ParseError:
        return res
    for h in root.findall("host"):
        st = h.find("status")
        if st is None or st.get("state") != "up":
            continue
        ip, mac, vendor = None, "", ""
        for a in h.findall("address"):
            if a.get("addrtype") == "ipv4":
                ip = a.get("addr")
            elif a.get("addrtype") == "mac":
                mac = normalize_mac(a.get("addr"))
                vendor = a.get("vendor", "")
        if ip:
            res[ip] = {"mac": mac, "vendor": vendor, "reason": st.get("reason", "")}
    return res


# ---------------------------------------------------------------- lokale ARP-Tabelle

def local_arp():
    """ARP-/Neighbor-Cache des Scan-Rechners -> {ip: mac}"""
    res = {}
    try:
        if IS_WINDOWS:
            out = _run(["arp", "-a"], 15).stdout.decode("utf-8", "ignore")
            for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})", out):
                res[m.group(1)] = normalize_mac(m.group(2))
        else:
            if shutil.which("ip"):
                out = _run(["ip", "-4", "neigh"], 15).stdout.decode("utf-8", "ignore")
                for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+) .*lladdr ([0-9a-fA-F:]{17})", out):
                    res[m.group(1)] = normalize_mac(m.group(2))
            elif os.path.exists("/proc/net/arp"):
                with open("/proc/net/arp") as f:
                    for line in f.readlines()[1:]:
                        p = line.split()
                        if len(p) >= 4 and p[3] != "00:00:00:00:00:00":
                            res[p[0]] = normalize_mac(p[3])
    except Exception:
        pass
    return {k: v for k, v in res.items() if v and v != "ff:ff:ff:ff:ff:ff" and not v.startswith("01:00:5e")}


def local_addresses():
    """IPv4-Adressen/Netze des Scan-Rechners (fuer Vorschlaege im UI)."""
    nets = []
    try:
        if IS_WINDOWS:
            out = _run(["ipconfig"], 15).stdout.decode("cp850", "ignore")
            ips = re.findall(r"IPv4[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", out)
            masks = re.findall(r"(?:Subnet Mask|Subnetzmaske)[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", out)
            for ip, mask in zip(ips, masks):
                nets.append(str(ipaddress.ip_network("%s/%s" % (ip, mask), strict=False)))
        else:
            out = _run(["ip", "-4", "-o", "addr"], 15).stdout.decode("utf-8", "ignore")
            for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", out):
                if not m.group(1).startswith("127."):
                    nets.append(str(ipaddress.ip_network(m.group(1), strict=False)))
    except Exception:
        pass
    return sorted(set(nets))


# ---------------------------------------------------------------- Namen

def reverse_dns(ip):
    try:
        name = socket.gethostbyaddr(ip)[0]
        return name if name != ip else ""
    except (OSError, UnicodeError):
        return ""


def _nb_encode(name="*"):
    raw = name.ljust(16, "\x00")[:16] if name != "*" else "*" + "\x00" * 15
    enc = "".join(chr(0x41 + (ord(c) >> 4)) + chr(0x41 + (ord(c) & 0x0F)) for c in raw)
    return b"\x20" + enc.encode("ascii") + b"\x00"


def netbios_status(ip, timeout=1.0):
    """NetBIOS Node Status Request (UDP 137). -> {name, domain, mac} oder None"""
    tid = random.randint(0, 0xFFFF)
    pkt = struct.pack(">HHHHHH", tid, 0x0000, 1, 0, 0, 0) + _nb_encode() + struct.pack(">HH", 0x21, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (ip, 137))
        data, _ = s.recvfrom(2048)
    except OSError:
        return None
    finally:
        s.close()
    try:
        if len(data) < 57 or struct.unpack(">H", data[:2])[0] != tid:
            return None
        num = data[56]
        off = 57
        name = domain = ""
        for _ in range(num):
            n = data[off:off + 15].decode("latin-1").strip()
            suffix = data[off + 15]
            flags = struct.unpack(">H", data[off + 16:off + 18])[0]
            group = bool(flags & 0x8000)
            if suffix == 0x00 and not group and not name:
                name = n
            elif suffix == 0x00 and group and not domain:
                domain = n
            off += 18
        mac = data[off:off + 6]
        mac_s = ":".join("%02x" % b for b in mac) if len(mac) == 6 and any(mac) else ""
        return {"name": name, "domain": domain, "mac": mac_s}
    except (IndexError, struct.error):
        return None


COMMON_SERVICES = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP", 110: "POP3", 135: "RPC",
    139: "NetBIOS", 143: "IMAP", 161: "SNMP", 389: "LDAP", 443: "HTTPS", 445: "SMB", 636: "LDAPS",
    1433: "MSSQL", 1521: "Oracle", 2049: "NFS", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    5900: "VNC", 5985: "WinRM", 8080: "HTTP-Alt", 8443: "HTTPS-Alt", 9100: "Drucker",
}
