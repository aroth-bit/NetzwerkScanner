"""Erzeugt snmpsim-Daten fuer drei simulierte Switches (Test & Demo).

  CORE-SW01  127.0.0.11  Aruba-artig, Q-BRIDGE, L3 (Vlan10/20/30), LLDP, LAG zu ESXi-Host
  ACC-SW01   127.0.0.12  Aruba-artig, Q-BRIDGE, LLDP zum Core, Clients + Telefon
  ACC-SW02   127.0.0.13  Cisco-artig, MAC-Tabelle nur per community@vlan, kein LLDP

Aufruf: python make_snmprec.py <ausgabeverzeichnis>
"""

import os
import sys


def mac(n, prefix="00:1a:2b"):
    return "%s:%02x:%02x:%02x" % (prefix, (n >> 16) & 255, (n >> 8) & 255, n & 255)


def mac_bytes(m):
    return [int(x, 16) for x in m.split(":")]


def mac_idx(m):
    return ".".join(str(b) for b in mac_bytes(m))


def mac_hex(m):
    return m.replace(":", "")


def portlist(ports, size=8):
    b = bytearray(size)
    for p in ports:
        b[(p - 1) // 8] |= 0x80 >> ((p - 1) % 8)
    return b.hex()


class Rec:
    def __init__(self):
        self.rows = []

    def add(self, oid, typ, val):
        self.rows.append((oid, typ, val))

    def write(self, path):
        rows = sorted(self.rows, key=lambda r: [int(x) for x in r[0].split(".")])
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for oid, typ, val in rows:
                f.write("%s|%s|%s\n" % (oid, typ, val))


def system(r, name, descr, oid, location):
    r.add("1.3.6.1.2.1.1.1.0", "4", descr)
    r.add("1.3.6.1.2.1.1.2.0", "6", oid)
    r.add("1.3.6.1.2.1.1.3.0", "67", "123456789")
    r.add("1.3.6.1.2.1.1.4.0", "4", "netzwerk@firma.local")
    r.add("1.3.6.1.2.1.1.5.0", "4", name)
    r.add("1.3.6.1.2.1.1.6.0", "4", location)
    r.add("1.3.6.1.2.1.1.7.0", "2", "6")


def iface(r, idx, name, typ=6, oper=1, alias="", speed=1000, m=None):
    r.add("1.3.6.1.2.1.2.2.1.1.%d" % idx, "2", idx)
    r.add("1.3.6.1.2.1.2.2.1.2.%d" % idx, "4", name)
    r.add("1.3.6.1.2.1.2.2.1.3.%d" % idx, "2", typ)
    r.add("1.3.6.1.2.1.2.2.1.5.%d" % idx, "66", min(speed * 1000000, 4294967295))
    r.add("1.3.6.1.2.1.2.2.1.6.%d" % idx, "4x", mac_hex(m) if m else "")
    r.add("1.3.6.1.2.1.2.2.1.7.%d" % idx, "2", 1 if oper != 99 else 2)
    r.add("1.3.6.1.2.1.2.2.1.8.%d" % idx, "2", 2 if oper == 99 else oper)
    r.add("1.3.6.1.2.1.31.1.1.1.1.%d" % idx, "4", name)
    r.add("1.3.6.1.2.1.31.1.1.1.15.%d" % idx, "66", speed)
    r.add("1.3.6.1.2.1.31.1.1.1.18.%d" % idx, "4", alias)


def entity(r, model, serial, sw):
    r.add("1.3.6.1.2.1.47.1.1.1.1.2.1", "4", model + " Chassis")
    r.add("1.3.6.1.2.1.47.1.1.1.1.5.1", "2", 3)
    r.add("1.3.6.1.2.1.47.1.1.1.1.10.1", "4", sw)
    r.add("1.3.6.1.2.1.47.1.1.1.1.11.1", "4", serial)
    r.add("1.3.6.1.2.1.47.1.1.1.1.13.1", "4", model)


def lldp_rem(r, lport, idx, chassis_mac, port_id, sysname, caps, mgmt_ip=None, port_desc=""):
    base = "1.0.8802.1.1.2.1.4.1.1"
    k = "0.%d.%d" % (lport, idx)
    r.add("%s.4.%s" % (base, k), "2", 4)
    r.add("%s.5.%s" % (base, k), "4x", mac_hex(chassis_mac))
    r.add("%s.6.%s" % (base, k), "2", 5)
    r.add("%s.7.%s" % (base, k), "4", port_id)
    r.add("%s.8.%s" % (base, k), "4", port_desc or port_id)
    r.add("%s.9.%s" % (base, k), "4", sysname)
    r.add("%s.10.%s" % (base, k), "4", sysname + " system")
    r.add("%s.12.%s" % (base, k), "4x", "%02x00" % caps)
    if mgmt_ip:
        r.add("1.0.8802.1.1.2.1.4.2.1.3.%s.1.4.%s" % (k, mgmt_ip), "2", 2)


BRIDGE, ROUTER, PHONE, STATION = 0x20, 0x08, 0x04, 0x01

# ------------------------------------------------------------------ Geraete
CORE_MAC = "00:0b:86:00:00:01"
ACC1_MAC = "00:0b:86:00:00:02"
ACC2_MAC = "00:1e:bd:00:00:03"
FW_MAC = "00:09:0f:aa:00:01"          # Fortinet
DB_MAC = "00:25:b5:00:10:20"           # Cisco UCS / Server
ESX_MAC = "ec:f4:bb:00:00:50"          # Dell
VM_MACS = ["00:50:56:a1:00:%02x" % i for i in range(1, 4)]  # VMware
PHONE_MAC = "00:04:f2:00:00:11"        # Polycom
CLIENTS1 = [("CL-%03d" % i, mac(0x100 + i, "3c:52:82"), "10.10.20.%d" % (100 + i)) for i in range(1, 11)]
SERVERS2 = [("SRV-APP%02d" % i, mac(0x200 + i, "d0:94:66"), "10.10.10.%d" % (30 + i)) for i in range(1, 6)]
CLIENTS2 = [("CL-%03d" % (20 + i), mac(0x300 + i, "3c:52:82"), "10.10.20.%d" % (130 + i)) for i in range(1, 4)]
PRINTER = ("PRN-ETAGE1", "00:00:aa:12:34:56", "10.10.20.250")  # Xerox


def core():
    r = Rec()
    system(r, "CORE-SW01", "Aruba JL659A 6300M 48SR5 CL6 PoE 4SFP56 Swch, FL.10.13", "1.3.6.1.4.1.47196.4.1.1.1.1",
           "RZ Frankfurt, Rack A01, HE 40")
    entity(r, "JL659A 6300M", "SG0ABC1234", "FL.10.13.1000")
    names = ["1/1/%d" % i for i in range(1, 9)]
    aliases = {1: "Uplink ACC-SW01", 2: "Uplink ACC-SW02", 3: "FW01 inside", 4: "SRV-DB01",
               6: "Backup-Server (aus)", 7: "esx01 vmnic0", 8: "esx01 vmnic1"}
    for i, n in enumerate(names, 1):
        oper = 2 if i == 6 else 1
        iface(r, i, n, 6, oper, aliases.get(i, ""), 10000 if i in (1, 2, 7, 8) else 1000,
              "00:0b:86:00:01:%02x" % i)
    iface(r, 100, "lag1", 161, 1, "esx01 LACP", 20000)
    for idx, vid in ((1010, 10), (1020, 20), (1030, 30)):
        iface(r, idx, "vlan%d" % vid, 136, 1, "", 1000, CORE_MAC)
    # ifStack: lag1 ueber 1/1/7, 1/1/8
    r.add("1.3.6.1.2.1.31.1.2.1.3.100.7", "2", 1)
    r.add("1.3.6.1.2.1.31.1.2.1.3.100.8", "2", 1)
    # Bridge-Ports 1..6 + 100 (LAG)
    bps = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 100: 100}
    for bp, idx in bps.items():
        r.add("1.3.6.1.2.1.17.1.4.1.2.%d" % bp, "2", idx)
    vlans = {1: "DEFAULT_VLAN", 10: "Server", 20: "Clients", 30: "Management"}
    for v, n in vlans.items():
        r.add("1.3.6.1.2.1.17.7.1.4.3.1.1.%d" % v, "4", n)
    # Trunks: 1,2,3 alle VLANs tagged, 100 tagged 10,20 ; Port 4 access 10, 5 access 20
    egress = {1: [5], 10: [1, 2, 3, 4, 100], 20: [1, 2, 3, 5, 100], 30: [1, 2, 3]}
    untag = {1: [5], 10: [4], 20: [5], 30: []}
    # Bitmap fuer Port 100 braucht 13 Bytes
    for v in vlans:
        r.add("1.3.6.1.2.1.17.7.1.4.3.1.2.%d" % v, "4x", portlist(egress[v], 16))
        r.add("1.3.6.1.2.1.17.7.1.4.3.1.4.%d" % v, "4x", portlist(untag[v], 16))
    for bp, pv in {1: 1, 2: 1, 3: 1, 4: 10, 5: 20, 6: 20, 100: 1}.items():
        r.add("1.3.6.1.2.1.17.7.1.4.5.1.1.%d" % bp, "66", pv)
    fdb = []
    fdb.append((30, ACC1_MAC, 1))
    for _n, m, _ip in CLIENTS1:
        fdb.append((20, m, 1))
    fdb.append((20, PHONE_MAC, 1))
    fdb.append((20, PRINTER[1], 1))
    fdb.append((30, ACC2_MAC, 2))
    for _n, m, _ip in SERVERS2:
        fdb.append((10, m, 2))
    for _n, m, _ip in CLIENTS2:
        fdb.append((20, m, 2))
    fdb.append((10, FW_MAC, 3))
    fdb.append((10, DB_MAC, 4))
    fdb.append((10, ESX_MAC, 100))
    for m in VM_MACS:
        fdb.append((10, m, 100))
    for v, m, bp in fdb:
        r.add("1.3.6.1.2.1.17.7.1.2.2.1.2.%d.%s" % (v, mac_idx(m)), "2", bp)
        r.add("1.3.6.1.2.1.17.7.1.2.2.1.3.%d.%s" % (v, mac_idx(m)), "2", 3)
    # L3
    for ip, idx in (("10.10.10.1", 1010), ("10.10.20.1", 1020), ("10.10.30.1", 1030)):
        r.add("1.3.6.1.2.1.4.20.1.1.%s" % ip, "64", ip)
        r.add("1.3.6.1.2.1.4.20.1.2.%s" % ip, "2", idx)
        r.add("1.3.6.1.2.1.4.20.1.3.%s" % ip, "64", "255.255.255.0")
    arp = [(1030, "127.0.0.12", ACC1_MAC), (1030, "127.0.0.13", ACC2_MAC), (1010, "10.10.10.254", FW_MAC),
           (1010, "10.10.10.20", DB_MAC), (1010, "10.10.10.50", ESX_MAC), (1020, PRINTER[2], PRINTER[1]),
           (1020, "10.10.20.60", PHONE_MAC)]
    arp += [(1010, "10.10.10.%d" % (60 + i), m) for i, m in enumerate(VM_MACS, 1)]
    arp += [(1020, ip, m) for _n, m, ip in CLIENTS1 + CLIENTS2]
    arp += [(1010, ip, m) for _n, m, ip in SERVERS2]
    for idx, ip, m in arp:
        r.add("1.3.6.1.2.1.4.22.1.2.%d.%s" % (idx, ip), "4x", mac_hex(m))
    # LLDP
    for i, n in enumerate(names, 1):
        r.add("1.0.8802.1.1.2.1.3.7.1.3.%d" % i, "4", n)
    lldp_rem(r, 1, 1, ACC1_MAC, "1/1/25", "ACC-SW01", BRIDGE, "127.0.0.12")
    lldp_rem(r, 3, 1, FW_MAC, "port2", "FW01", ROUTER, "10.10.10.254")
    lldp_rem(r, 4, 1, DB_MAC, "eno1", "SRV-DB01.firma.local", STATION, "10.10.10.20")
    return r


def acc1():
    r = Rec()
    system(r, "ACC-SW01", "Aruba JL661A 6300M 48G CL4 PoE 4SFP56 Swch, FL.10.13", "1.3.6.1.4.1.47196.4.1.1.1.2",
           "RZ Frankfurt, Rack A03, HE 42")
    entity(r, "JL661A 6300M", "SG0ABC5678", "FL.10.13.1000")
    for i in range(1, 27):
        alias = "Arbeitsplatz %d" % i if i <= 10 else ("Telefon Empfang" if i == 11 else
                                                         ("Drucker Etage 1" if i == 12 else
                                                          ("Uplink CORE-SW01" if i == 25 else "")))
        oper = 1 if i <= 12 or i in (14, 25) else 2
        iface(r, i, "1/1/%d" % i, 6, oper, alias, 10000 if i >= 25 else 1000, "00:0b:86:00:02:%02x" % i)
        r.add("1.3.6.1.2.1.17.1.4.1.2.%d" % i, "2", i)
        r.add("1.0.8802.1.1.2.1.3.7.1.3.%d" % i, "4", "1/1/%d" % i)
    iface(r, 1030, "vlan30", 136, 1, "", 1000, ACC1_MAC)
    for v, n in {1: "DEFAULT_VLAN", 20: "Clients", 30: "Management"}.items():
        r.add("1.3.6.1.2.1.17.7.1.4.3.1.1.%d" % v, "4", n)
    access = list(range(1, 25))
    r.add("1.3.6.1.2.1.17.7.1.4.3.1.2.20", "4x", portlist(access + [25], 4))
    r.add("1.3.6.1.2.1.17.7.1.4.3.1.4.20", "4x", portlist(access, 4))
    r.add("1.3.6.1.2.1.17.7.1.4.3.1.2.30", "4x", portlist([25], 4))
    r.add("1.3.6.1.2.1.17.7.1.4.3.1.4.30", "4x", portlist([], 4))
    r.add("1.3.6.1.2.1.17.7.1.4.3.1.2.1", "4x", portlist([25], 4))
    r.add("1.3.6.1.2.1.17.7.1.4.3.1.4.1", "4x", portlist([25], 4))
    for i in range(1, 27):
        r.add("1.3.6.1.2.1.17.7.1.4.5.1.1.%d" % i, "66", 20 if i <= 24 else 1)
    fdb = [(20, m, i) for i, (_n, m, _ip) in enumerate(CLIENTS1, 1)]
    fdb += [(20, PHONE_MAC, 11), (20, PRINTER[1], 12)]
    fdb += [(30, CORE_MAC, 25), (10, FW_MAC, 25), (10, DB_MAC, 25), (30, ACC2_MAC, 25)]
    fdb += [(20, m, 25) for _n, m, _ip in CLIENTS2]
    for v, m, bp in fdb:
        r.add("1.3.6.1.2.1.17.7.1.2.2.1.2.%d.%s" % (v, mac_idx(m)), "2", bp)
    r.add("1.3.6.1.2.1.4.20.1.2.127.0.0.12", "2", 1030)
    r.add("1.3.6.1.2.1.4.20.1.3.127.0.0.12", "64", "255.0.0.0")
    lldp_rem(r, 25, 1, CORE_MAC, "1/1/1", "CORE-SW01", BRIDGE | ROUTER, "127.0.0.11")
    lldp_rem(r, 11, 1, PHONE_MAC, "WAN", "SEP-Empfang", BRIDGE | PHONE, "10.10.20.60")
    return r


def acc2():
    """Cisco: Grunddaten ohne FDB + je VLAN eine Datei mit BRIDGE-MIB."""
    r = Rec()
    system(r, "ACC-SW02", "Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E8",
           "1.3.6.1.4.1.9.1.1208", "RZ Frankfurt, Rack B02, HE 41")
    entity(r, "WS-C2960X-48TS-L", "FOC1234X0YZ", "15.2(7)E8")
    for i in range(1, 49):
        idx = 10100 + i
        alias = {1: "SRV-APP01", 2: "SRV-APP02", 3: "SRV-APP03", 4: "SRV-APP04", 5: "SRV-APP05",
                 10: "PC Buchhaltung", 48: "Uplink CORE-SW01 1/1/2"}.get(i, "")
        oper = 1 if i <= 5 or i in (10, 11, 12, 48) else 2
        iface(r, idx, "Gi1/0/%d" % i, 6, oper, alias, 1000, "00:1e:bd:00:01:%02x" % i)
        vlan = 10 if i <= 9 else 20
        r.add("1.3.6.1.4.1.9.9.68.1.2.2.1.2.%d" % idx, "2", vlan)
    r.add("1.3.6.1.4.1.9.9.46.1.6.1.1.14.10148", "2", 1)
    r.add("1.3.6.1.4.1.9.9.46.1.6.1.1.5.10148", "2", 1)
    tv = bytearray(128)
    for v in (1, 10, 20, 30):
        tv[v // 8] |= 0x80 >> (v % 8)
    r.add("1.3.6.1.4.1.9.9.46.1.6.1.1.4.10148", "4x", tv.hex())
    iface(r, 2030, "Vlan30", 53, 1, "", 1000, ACC2_MAC)
    for v, n in {1: "default", 10: "Server", 20: "Clients", 30: "Management", 1002: "fddi-default"}.items():
        r.add("1.3.6.1.4.1.9.9.46.1.3.1.1.2.1.%d" % v, "2", 1)
        r.add("1.3.6.1.4.1.9.9.46.1.3.1.1.4.1.%d" % v, "4", n)
    r.add("1.3.6.1.2.1.4.20.1.2.127.0.0.13", "2", 2030)
    r.add("1.3.6.1.2.1.4.20.1.3.127.0.0.13", "64", "255.0.0.0")
    per_vlan = {}
    for v in (10, 20, 30):
        pv = Rec()
        for i in range(1, 49):
            pv.add("1.3.6.1.2.1.17.1.4.1.2.%d" % i, "2", 10100 + i)
        per_vlan[v] = pv
    for i, (_n, m, _ip) in enumerate(SERVERS2, 1):
        per_vlan[10].add("1.3.6.1.2.1.17.4.3.1.2.%s" % mac_idx(m), "2", i)
        per_vlan[10].add("1.3.6.1.2.1.17.4.3.1.3.%s" % mac_idx(m), "2", 3)
    for i, (_n, m, _ip) in enumerate(CLIENTS2, 10):
        per_vlan[20].add("1.3.6.1.2.1.17.4.3.1.2.%s" % mac_idx(m), "2", i)
    for m, v in ((CORE_MAC, 30), (FW_MAC, 10), (DB_MAC, 10), (ESX_MAC, 10), (PRINTER[1], 20)):
        per_vlan[v].add("1.3.6.1.2.1.17.4.3.1.2.%s" % mac_idx(m), "2", 48)
    for _n, m, _ip in CLIENTS1:
        per_vlan[20].add("1.3.6.1.2.1.17.4.3.1.2.%s" % mac_idx(m), "2", 48)
    per_vlan[30].add("1.3.6.1.2.1.17.4.3.1.2.%s" % mac_idx(ACC1_MAC), "2", 48)
    return r, per_vlan


def main(out):
    os.makedirs(out, exist_ok=True)
    for name, rec in (("core", core()), ("acc1", acc1())):
        d = os.path.join(out, name)
        os.makedirs(d, exist_ok=True)
        rec.write(os.path.join(d, "public.snmprec"))
    r, per_vlan = acc2()
    d = os.path.join(out, "acc2")
    os.makedirs(d, exist_ok=True)
    r.write(os.path.join(d, "public.snmprec"))
    for v, rec in per_vlan.items():
        rec.write(os.path.join(d, "public@%d.snmprec" % v))
    # Hostnamen fuer die Demo (es gibt kein echtes DNS)
    names = {ip: n.lower() + ".firma.local" for n, _m, ip in CLIENTS1 + SERVERS2 + CLIENTS2}
    names.update({"10.10.10.254": "fw01.firma.local", "10.10.10.20": "srv-db01.firma.local",
                  "10.10.10.50": "esx01.firma.local", "10.10.10.61": "vm-dc01.firma.local",
                  "10.10.10.62": "vm-file01.firma.local", "10.10.10.63": "vm-exchange.firma.local",
                  PRINTER[2]: "prn-etage1.firma.local", "10.10.20.60": "sep-empfang.firma.local"})
    import json
    with open(os.path.join(out, "names.json"), "w") as f:
        json.dump(names, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "simdata")
