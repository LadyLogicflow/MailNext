"""Betreiber-Anmeldung über das zentrale Portal-Cookie (bst_session, Domain .bst-next.de).

MailNext prüft das Cookie nicht selbst, sondern fragt SortNext (/api/v1/portal/me).
Ergebnis kurz zwischengespeichert (30 s), damit nicht jeder Aufruf SortNext belastet."""
import hashlib
import threading
import time
from functools import wraps

import requests
from flask import g, jsonify, request

import config

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


def betreiber_pflicht(f):
    @wraps(f)
    def innen(*a, **kw):
        token = request.cookies.get(COOKIE, "")
        if not token:
            return jsonify({"error": "not authenticated"}), 401
        b = betreiber_ermitteln(token)
        if b is None:
            return jsonify({"error": "forbidden"}), 403
        g.betreiber = b
        return f(*a, **kw)
    return innen
