"""Synchroner SNMP-Client (v1/v2c/v3) auf Basis von pysnmp 7 (asyncio)."""

import asyncio

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine,
    UdpTransportTarget, UsmUserData, bulk_walk_cmd, get_cmd, walk_cmd,
    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol, usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol, usmHMAC256SHA384AuthProtocol, usmHMAC384SHA512AuthProtocol,
    usmNoAuthProtocol, usmDESPrivProtocol, usm3DESEDEPrivProtocol, usmAesCfb128Protocol,
    usmAesCfb192Protocol, usmAesCfb256Protocol, usmNoPrivProtocol,
)
from pysnmp.proto import rfc1902

AUTH_PROTOCOLS = {
    "none": usmNoAuthProtocol, "md5": usmHMACMD5AuthProtocol, "sha": usmHMACSHAAuthProtocol,
    "sha224": usmHMAC128SHA224AuthProtocol, "sha256": usmHMAC192SHA256AuthProtocol,
    "sha384": usmHMAC256SHA384AuthProtocol, "sha512": usmHMAC384SHA512AuthProtocol,
}
PRIV_PROTOCOLS = {
    "none": usmNoPrivProtocol, "des": usmDESPrivProtocol, "3des": usm3DESEDEPrivProtocol,
    "aes": usmAesCfb128Protocol, "aes128": usmAesCfb128Protocol,
    "aes192": usmAesCfb192Protocol, "aes256": usmAesCfb256Protocol,
}

_EMPTY_TYPES = ("NoSuchObject", "NoSuchInstance", "EndOfMibView", "Null")


class SnmpError(Exception):
    pass


def split_host(host: str, default_port: int = 161):
    """'10.0.0.1' oder '10.0.0.1:1161' -> (host, port)."""
    host = host.strip()
    if host.count(":") == 1:
        h, p = host.split(":")
        return h, int(p)
    return host, default_port


def convert(val):
    """pysnmp-Wert -> Python (int | bytes | str)."""
    name = val.__class__.__name__
    if name in _EMPTY_TYPES:
        return None
    if isinstance(val, rfc1902.IpAddress):
        return ".".join(str(b) for b in val.asOctets())
    if isinstance(val, rfc1902.OctetString) or name in ("OctetString", "Bits", "Opaque"):
        return bytes(val.asOctets())
    if isinstance(val, rfc1902.ObjectName) or name == "ObjectIdentifier":
        return ".".join(str(x) for x in val)
    try:
        return int(val)
    except (TypeError, ValueError):
        return val.prettyPrint()


def to_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        try:
            s = v.decode("utf-8")
        except UnicodeDecodeError:
            s = v.decode("latin-1")
        return s.replace("\x00", "").strip()
    return str(v)


def to_mac(v) -> str:
    if isinstance(v, bytes) and len(v) == 6:
        return ":".join("%02x" % b for b in v)
    if isinstance(v, bytes):
        # manche Geraete liefern die MAC als Text
        s = to_text(v)
        return normalize_mac(s)
    return ""


def normalize_mac(s: str) -> str:
    if not s:
        return ""
    h = "".join(c for c in s.lower() if c in "0123456789abcdef")
    if len(h) != 12:
        return ""
    return ":".join(h[i:i + 2] for i in range(0, 12, 2))


class SnmpClient:
    """Ein Client je Zielgeraet. Nicht thread-sicher - pro Thread eine Instanz verwenden."""

    def __init__(self, host: str, cred: dict, timeout: float = 2.0, retries: int = 1):
        self.host, self.port = split_host(host)
        self.cred = cred or {}
        self.timeout = timeout
        self.retries = retries
        self.version = str(self.cred.get("version", "2c")).lower().lstrip("v")
        self._loop = asyncio.new_event_loop()
        self._engine = None
        self._target = None

    # ------------------------------------------------------------ intern
    def close(self):
        try:
            if self._engine is not None:
                self._engine.close_dispatcher()
        except Exception:
            pass
        try:
            # haengende Timeout-Tasks des pysnmp-Dispatchers sauber beenden
            pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        try:
            self._loop.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    async def _prepare(self):
        if self._engine is None:
            self._engine = SnmpEngine()
        if self._target is None:
            self._target = await UdpTransportTarget.create(
                (self.host, self.port), timeout=self.timeout, retries=self.retries)

    def _auth(self, vlan=None):
        c = self.cred
        if self.version in ("1", "2c", "2"):
            community = c.get("community", "public")
            if vlan is not None:
                community = "%s@%s" % (community, vlan)  # Cisco: Bridge-MIB je VLAN
            return CommunityData(community, mpModel=0 if self.version == "1" else 1)
        auth = AUTH_PROTOCOLS.get(str(c.get("auth_protocol", "sha")).lower(), usmHMACSHAAuthProtocol)
        priv = PRIV_PROTOCOLS.get(str(c.get("priv_protocol", "aes")).lower(), usmAesCfb128Protocol)
        auth_key = c.get("auth_key") or None
        priv_key = c.get("priv_key") or None
        if not auth_key:
            auth, priv = usmNoAuthProtocol, usmNoPrivProtocol
        elif not priv_key:
            priv = usmNoPrivProtocol
        return UsmUserData(c.get("user", ""), authKey=auth_key, privKey=priv_key,
                           authProtocol=auth, privProtocol=priv)

    def _context(self, vlan=None):
        if vlan is not None and self.version == "3":
            name = (self.cred.get("vlan_context_format") or "vlan-{vlan}").format(vlan=vlan)
            return ContextData(contextName=name)
        return ContextData()

    # ------------------------------------------------------------ API
    def get(self, oids):
        """Liefert {oid: wert} fuer skalare OIDs."""
        return self._run(self._get(list(oids)))

    async def _get(self, oids):
        await self._prepare()
        err_ind, err_stat, _idx, var_binds = await get_cmd(
            self._engine, self._auth(), self._target, self._context(),
            *[ObjectType(ObjectIdentity(o)) for o in oids], lookupMib=False)
        if err_ind:
            raise SnmpError(str(err_ind))
        if err_stat:
            raise SnmpError(err_stat.prettyPrint())
        out = {}
        for name, val in var_binds:
            out[".".join(str(x) for x in name)] = convert(val)
        return out

    def walk(self, base_oid: str, vlan=None, max_rows: int = 200000):
        """Walk eines Teilbaums -> Liste [(index_tuple, wert)]. Index relativ zu base_oid."""
        return self._run(self._walk(base_oid, vlan, max_rows))

    async def _walk(self, base_oid, vlan, max_rows):
        await self._prepare()
        base = tuple(int(x) for x in base_oid.strip(".").split("."))
        rows = []
        if self.version == "1":
            gen = walk_cmd(self._engine, self._auth(vlan), self._target, self._context(vlan),
                           ObjectType(ObjectIdentity(base_oid)),
                           lexicographicMode=False, lookupMib=False)
        else:
            gen = bulk_walk_cmd(self._engine, self._auth(vlan), self._target, self._context(vlan),
                                0, 25, ObjectType(ObjectIdentity(base_oid)),
                                lexicographicMode=False, lookupMib=False)
        async for err_ind, err_stat, _idx, var_binds in gen:
            if err_ind:
                if rows:
                    break  # Teilergebnis behalten
                raise SnmpError(str(err_ind))
            if err_stat:
                break
            for name, val in var_binds:
                oid = tuple(name)
                if oid[:len(base)] != base:
                    return rows
                v = convert(val)
                if v is None:
                    continue
                rows.append((oid[len(base):], v))
            if len(rows) >= max_rows:
                break
        return rows

    def walk_dict(self, base_oid: str, vlan=None):
        """Walk -> {index_tuple: wert}."""
        return dict(self.walk(base_oid, vlan))

    def walk_first(self, base_oid: str, vlan=None):
        """Walk mit einstelligem Index -> {int: wert}."""
        return {idx[0]: v for idx, v in self.walk(base_oid, vlan) if idx}


def probe(host: str, credentials: list, timeout: float = 2.0, retries: int = 1):
    """Ermittelt die erste funktionierende Zugangsdaten-Variante. -> (cred, sysinfo) oder (None, None)."""
    for cred in credentials:
        try:
            with SnmpClient(host, cred, timeout, retries) as c:
                res = c.get(["1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.1.1.0", "1.3.6.1.2.1.1.2.0",
                             "1.3.6.1.2.1.1.7.0"])
                if any(v is not None for v in res.values()):
                    return cred, res
        except Exception:
            continue
    return None, None
