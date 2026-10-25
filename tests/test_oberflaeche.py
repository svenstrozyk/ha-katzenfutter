"""Tests für Tabs und Katzenprofil (Flask-Testclient, DEV_MODE)."""
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}

PROFIL = {
    "name": "Mimi", "geburtsjahr": "2023", "kastriert": "1", "freigang": "1",
    "gewicht_aktuell": "4,2", "zielgewicht": "", "bcs": "", "aktivitaetsfaktor": "1.4",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    yield app_module.app.test_client(), app_module
    sys.path.pop(0)


@pytest.mark.parametrize("pfad", ["/", "/fuettern", "/futter", "/verlauf", "/katze", "/einstellungen", "/snack", "/gesundheit", "/kosten", "/scan", "/produkt"])
def test_alle_tabs_erreichbar(client, pfad):
    c, _ = client
    assert c.get(pfad, headers=HEADERS).status_code == 200


def test_links_sind_relativ(client):
    c, _ = client
    html = c.get("/katze", headers=HEADERS).get_data(as_text=True)
    assert 'href="/' not in html
    assert 'action="/' not in html


def test_ohne_gewicht_fordert_rechner_gewicht_an(client):
    c, _ = client
    html = c.get("/katze", headers=HEADERS).get_data(as_text=True)
    assert "Aktuelles Gewicht eintragen" in html


def test_gewicht_speichern_mit_komma_und_historie(client):
    c, mod = client
    r = c.post("/katze", headers=HEADERS, data=PROFIL)
    assert r.status_code == 302
    # Weiterleitung mit Ingress-Präfix
    assert r.headers["Location"].startswith("/api/hassio_ingress/test/katze")
    con = mod.db()
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 4.2
    assert [tuple(z) for z in con.execute("SELECT kg, quelle FROM gewicht")] == [(4.2, "manuell")]
    # gleiches Gewicht erneut speichern erzeugt keinen zweiten Historieneintrag
    c.post("/katze", headers=HEADERS, data=PROFIL)
    assert con.execute("SELECT COUNT(*) FROM gewicht").fetchone()[0] == 1


def test_rechner_zeigt_bedarf(client):
    c, _ = client
    c.post("/katze", headers=HEADERS, data=PROFIL)
    html = c.get("/katze?kcal_100g=95&packung_g=85", headers=HEADERS).get_data(as_text=True)
    # RER = 70 × 4,2^0,75 ≈ 205; MER = × 1,4 ≈ 288; Menge = 287,5 / 95 × 100 ≈ 303 g
    assert "205 kcal" in html
    assert "288 kcal" in html
    assert "303 g" in html
    assert "3,6 × 85 g" in html


def test_reduktion_ohne_zielgewicht_gibt_hinweis(client):
    c, _ = client
    c.post("/katze", headers=HEADERS, data=dict(PROFIL, aktivitaetsfaktor="0.8"))
    html = c.get("/katze", headers=HEADERS).get_data(as_text=True)
    assert "Zielgewicht ist noch offen" in html


@pytest.mark.parametrize("feld, wert", [
    ("gewicht_aktuell", "42"), ("gewicht_aktuell", "vier"), ("bcs", "12"), ("bcs", "4,5"), ("name", ""),
])
def test_ungueltige_eingaben_werden_abgelehnt(client, feld, wert):
    c, mod = client
    r = c.post("/katze", headers=HEADERS, data=dict(PROFIL, **{feld: wert}))
    assert r.status_code == 400
    assert "Nicht gespeichert" in r.get_data(as_text=True)
    assert mod.db().execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] is None


def test_zielgewicht_und_bcs_offen_bleiben_null(client):
    c, mod = client
    c.post("/katze", headers=HEADERS, data=PROFIL)
    row = mod.db().execute("SELECT zielgewicht, bcs FROM katze").fetchone()
    assert tuple(row) == (None, None)


def test_zahlenformat_rundet_kaufmaennisch(client):
    _, mod = client
    assert mod.format_de(42.5) == "43"
    assert mod.format_de(1234.25, 1) == "1.234,3"
    assert mod.format_de(None) == "–"
    assert mod.format_gramm(85.0) == "85" and mod.format_gramm(42.5) == "42,5"
