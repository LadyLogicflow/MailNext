"""Betreiber-Anmeldung über das zentrale Portal-Cookie (bst_session, Domain .bst-next.de).

MailNext prüft das Cookie nicht selbst, sondern fragt SortNext (/api/v1/portal/me).
Ergebnis kurz zwischengespeichert (30 s), damit nicht jeder Aufruf SortNext belastet."""
import hashlib
import ipaddress
import logging
import threading
import time
from functools import wraps
from urllib.parse import urlsplit

import requests
from flask import g, jsonify, request

import config

LOG = logging.getLogger("mailnext.betreiber_auth")
COOKIE = "bst_session"
CACHE_SEKUNDEN = 30
_cache: dict[str, tuple[float, dict | None]] = {}
_cache_sperre = threading.Lock()


def _schluessel(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bei_sortnext_fragen(token: str) -> dict | None:
    try:
        r = requests.get(config.sortnext_basis_url() + "/api/v1/portal/me",
                         cookies={COOKIE: token}, timeout=5)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        daten = r.json()
    except ValueError:
        return None
    if not isinstance(daten, dict) or not daten.get("email"):
        return None
    return daten


def betreiber_ermitteln(token: str) -> dict | None:
    """Gibt {'email': …} für einen gültigen, vollständig eingerichteten Betreiber zurück."""
    if not token:
        return None
    k = _schluessel(token)
    jetzt = time.monotonic()
    with _cache_sperre:
        treffer = _cache.get(k)
        if treffer and jetzt - treffer[0] < CACHE_SEKUNDEN:
            return treffer[1]
    daten = _bei_sortnext_fragen(token)
    ergebnis = None
    if daten and daten.get("betreiber") is True and not daten.get("onboarding_incomplete"):
        ergebnis = {"email": str(daten["email"]).lower()}
    with _cache_sperre:
        if len(_cache) > 500:
            _cache.clear()
        _cache[k] = (jetzt, ergebnis)
    return ergebnis


def cache_leeren() -> None:
    with _cache_sperre:
        _cache.clear()


# ----- Offen-Modus (nur Pi-Testinstanz im Heimnetz, MAILNEXT_BETREIBER_AUTH=offen) -----
# Betreiber-Aufrufe brauchen dort keine Anmeldung, werden aber nur beantwortet, wenn ALLE Bedingungen erfüllt sind (sonst 403, fail closed):
# (a) die Verbindung kommt direkt von einer Loopback- oder privaten Adresse (REMOTE_ADDR, nie X-Forwarded-For),
# (b) die Anfrage trägt keinen Proxy-Kopf (ein Tunnel/Proxy auf dem Pi selbst erscheint sonst als Loopback),
# (c) der Host-Kopf ist die Pi-Adresse oder localhost (stoppt DNS-Rebinding); ändernde Aufrufe mit Origin-Kopf nur vom selben Host (stoppt fremde Webseiten im
#     Browser des Heimnetzes),
# (d) die Anfrage kam nicht auf dem öffentlichen Port (das erledigt app.py: dort gibt es keine Betreiber-Pfade).
PROXY_KOEPFE = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Forwarded-Port", "Forwarded", "X-Real-IP", "X-Client-IP",
                "CF-Connecting-IP", "True-Client-IP", "Fastly-Client-IP", "Via")
LOKALE_NAMEN = ("localhost", "127.0.0.1", "[::1]", "::1")
_PRIVAT = tuple(ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7"))


def adresse_privat(adresse: str) -> bool:
    try:
        ip = ipaddress.ip_address((adresse or "").strip())
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in netz for netz in _PRIVAT)


def _host_name(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):                                                         # [::1]:8000
        return host.split("]", 1)[0] + "]"
    return host.split(":", 1)[0]


def offen_pruefen() -> str | None:
    """None = erlaubt, sonst ein kurzer Grund (nur für das Log, nie für den Aufrufer)."""
    if not adresse_privat(request.remote_addr or ""):
        return "adresse_nicht_privat"
    if any(request.headers.get(k) for k in PROXY_KOEPFE):
        return "proxy_kopf"
    erlaubt = set(LOKALE_NAMEN)
    if config.pi_adresse():
        erlaubt.add(config.pi_adresse())
    if _host_name(request.headers.get("Host", "")) not in erlaubt:
        return "host_unbekannt"
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        herkunft = request.headers.get("Origin")
        if herkunft is not None and (herkunft == "null" or urlsplit(herkunft).netloc.lower() != request.headers.get("Host", "").strip().lower()):
            return "origin_fremd"
    return None


def betreiber_pflicht(f):
    @wraps(f)
    def innen(*a, **kw):
        if config.betreiber_auth() == "offen":
            grund = offen_pruefen()
            if grund:
                LOG.warning("Offen-Modus: Betreiber-Aufruf abgelehnt (%s)", grund)
                return jsonify({"error": "forbidden"}), 403
            g.betreiber = {"email": config.betreiber_offen_email() or "offen", "offen": True}
            return f(*a, **kw)
        token = request.cookies.get(COOKIE, "")
        if not token:
            return jsonify({"error": "not authenticated"}), 401
        b = betreiber_ermitteln(token)
        if b is None:
            return jsonify({"error": "forbidden"}), 403
        g.betreiber = b
        return f(*a, **kw)
    return innen
