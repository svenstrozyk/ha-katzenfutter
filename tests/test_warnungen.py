"""Tests für Warn-Mitteilungen (ohne Netzwerk)."""
import importlib
import json
import os
import sys

import pytest
from werkzeug.datastructures import MultiDict

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Sam"}
OPTIONEN = {"notify_services": ["mobile_app_iphone_alex", "mobile_app_sams_iphone"]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    c.post("/katze", headers=HEADERS, data={"name": "Mimi", "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4"})
    yield c, app_module
    sys.path.pop(0)


@pytest.fixture()
def dienst(client, monkeypatch):
    _, mod = client
    gesendet = []
    d = mod.benachrichtigung.Dienst(mod.DB_PATH, "token", lambda: OPTIONEN, "/4f1ea0a0_katzenfutter")
    monkeypatch.setattr(d, "_senden", lambda ziel, payload: gesendet.append((ziel, payload)))
    d.gesendet = gesendet
    return d


def melden(c, typ, **extra):
    return c.post("/gesundheit", headers=HEADERS, data=dict({"typ": typ}, **extra), content_type="multipart/form-data")


def test_ohne_warnung_nichts(client, dienst):
    assert dienst.warnen_einmal() == 0 and dienst.gesendet == []


def test_tierarzt_hinweis_einmal_an_alle(client, dienst):
    c, _ = client
    melden(c, "erbrechen", blut="1")
    assert dienst.warnen_einmal() == 1
    assert [z for z, _ in dienst.gesendet] == ["mobile_app_iphone_alex", "mobile_app_sams_iphone"]
    payload = dienst.gesendet[0][1]
    assert payload["title"] == "Mimi: Tierarzt-Hinweis" and "Blut bemerkt" in payload["message"]
    assert "keine Diagnose" in payload["message"]
    assert payload["data"]["push"]["interruption-level"] == "time-sensitive"
    assert payload["data"]["url"] == "/4f1ea0a0_katzenfutter"
    # nicht wiederholen
    assert dienst.warnen_einmal() == 0 and len(dienst.gesendet) == 2


def test_zahlenaenderung_meldet_nicht_neu(client, dienst):
    c, _ = client
    melden(c, "erbrechen")
    melden(c, "erbrechen")
    assert dienst.warnen_einmal() == 2  # 2× Erbrechen (Tierarzt) + 2 Ereignisse in 7 Tagen (Hinweis)
    melden(c, "erbrechen")
    assert dienst.warnen_einmal() == 0


def test_erneut_nach_verschwinden(client, dienst):
    c, mod = client
    melden(c, "erbrechen", blut="1")
    dienst.warnen_einmal()
    con = mod.db()
    with con:
        con.execute("DELETE FROM ereignis")
    assert dienst.warnen_einmal() == 0
    assert mod.benachrichtigung.warnungen.gesendet_laden(mod.db()) == {}
    melden(c, "durchfall", blut="1")
    assert dienst.warnen_einmal() == 1


def test_hinweis_ohne_zeitkritisch(client, dienst):
    c, _ = client
    melden(c, "weicher_kot")
    melden(c, "durchfall")
    dienst.warnen_einmal()
    payload = dienst.gesendet[0][1]
    assert payload["title"] == "Mimi: Hinweis" and "push" not in payload["data"]


def test_snack_limit_nur_bei_ueberschreitung(client, dienst):
    c, _ = client
    c.post("/einstellungen", headers=HEADERS, data=MultiDict([
        ("name", "Sam"), ("rolle", "erwachsen"), ("ha_name", ""),
        ("name", "Kind 1"), ("rolle", "kind"), ("ha_name", ""), ("snack_limit_kinder", "1")]))
    c.post("/produkt", headers=HEADERS, data={"marke": "D", "sorte": "Leckerli", "futterart": "snack",
                                              "kcal_100g": "400", "stueck_g": "1"})
    c.post("/snack", headers=HEADERS, data={"produkt_id": "1", "stueck": "1", "person": "Kind 1"})
    assert dienst.warnen_einmal() == 0  # erreicht, nicht überschritten
    c.post("/snack", headers=HEADERS, data={"produkt_id": "1", "stueck": "1", "person": "Kind 1"})
    assert dienst.warnen_einmal() == 1
    assert "Snack-Limit der Kinder überschritten (2 von 1 Stück)" in dienst.gesendet[0][1]["message"]


def test_abschaltbar(client, monkeypatch):
    c, mod = client
    melden(c, "erbrechen", blut="1")
    d = mod.benachrichtigung.Dienst(mod.DB_PATH, "t", lambda: dict(OPTIONEN, warn_mitteilungen=False), "/")
    monkeypatch.setattr(d, "_senden", lambda *a: pytest.fail("darf nicht senden"))
    assert d.warnen_einmal() == 0


def test_fehlgeschlagener_versand_wird_wiederholt(client, monkeypatch):
    c, mod = client
    melden(c, "erbrechen", blut="1")
    d = mod.benachrichtigung.Dienst(mod.DB_PATH, "t", lambda: OPTIONEN, "/")

    def kaputt(ziel, payload):
        raise mod.benachrichtigung.requests.ConnectionError("HA startet neu")

    monkeypatch.setattr(d, "_senden", kaputt)
    assert d.warnen_einmal() == 0
    assert mod.benachrichtigung.warnungen.gesendet_laden(mod.db()) == {}
    monkeypatch.setattr(d, "_senden", lambda ziel, payload: None)
    assert d.warnen_einmal() == 1
