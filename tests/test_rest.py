"""Tests für die Rest-Erfassung."""
import datetime
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    # Futter mit berechneten 94,75 kcal/100 g, eine Mahlzeit à 85 g
    c.post("/produkt", headers=HEADERS, data={
        "marke": "Animonda", "sorte": "Pute", "packung_g": "85", "bestand_packungen": "5",
        "rohprotein": "11", "rohfett": "6", "rohasche": "2", "rohfaser": "0,5", "feuchte": "79"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "85"})
    yield c, app_module
    sys.path.pop(0)


def mahlzeit(mod):
    return mod.db().execute("SELECT * FROM mahlzeit WHERE id = 1").fetchone()


def test_offene_mahlzeit_wird_angezeigt(client):
    c, _ = client
    html = c.get("/fuettern", headers=HEADERS).get_data(as_text=True)
    assert "<h2>Rest eintragen</h2>" in html and 'value="haelfte"' in html
    assert "Rest offen" in html


@pytest.mark.parametrize("stufe, rest, gefressen", [
    ("nichts", 0, 85), ("wenig", 8.5, 76.5), ("haelfte", 42.5, 42.5), ("viel", 63.75, 21.25), ("unberuehrt", 85, 0),
])
def test_schaetzstufen(client, stufe, rest, gefressen):
    c, mod = client
    r = c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": stufe})
    assert r.status_code == 302 and "rest=1" in r.headers["Location"]
    m = mahlzeit(mod)
    assert m["rest_g"] == pytest.approx(rest) and m["gefressen_g"] == pytest.approx(gefressen)
    assert m["rest_herkunft"] == "geschaetzt" and m["verweigert"] == 0
    assert m["kcal"] == pytest.approx(gefressen * 0.9475)


def test_gewogener_rest(client):
    c, mod = client
    c.post("/rest", headers=HEADERS, data={"id": "1", "rest_g": "12,5"})
    m = mahlzeit(mod)
    assert (m["rest_g"], m["rest_herkunft"], m["gefressen_g"]) == (12.5, "gewogen", 72.5)


def test_verweigert(client):
    c, mod = client
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "unberuehrt", "verweigert": "1"})
    m = mahlzeit(mod)
    assert (m["gefressen_g"], m["verweigert"], m["kcal"]) == (0, 1, 0)


def test_korrektur_ueberschreibt(client):
    c, mod = client
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "haelfte"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "rest_g": "30"})
    m = mahlzeit(mod)
    assert (m["rest_g"], m["rest_herkunft"]) == (30, "gewogen")


def test_erfasste_mahlzeit_nicht_mehr_offen_und_heute_markiert(client):
    c, _ = client
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "wenig"})
    html = c.get("/fuettern?rest=1", headers=HEADERS).get_data(as_text=True)
    assert "<h2>Rest eintragen</h2>" not in html
    assert "≈ 76,5 g" in html and "geschätzt" in html
    assert "Rest gespeichert" in html


def test_rueckgaengig_nach_rest_nicht_moeglich(client):
    c, mod = client
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "nichts"})
    r = c.post("/rueckgaengig", headers=HEADERS, data={"mahlzeit_id": "1"})
    assert "zurueckgenommen=0" in r.headers["Location"]


@pytest.mark.parametrize("daten, meldung", [
    ({"id": "1", "rest_g": "90"}, "zwischen 0 und 85"),
    ({"id": "1", "rest_g": "-1"}, "zwischen 0 und 85"),
    ({"id": "1", "rest_g": "viel"}, "in g angeben"),
    ({"id": "1", "stufe": "ein_bisschen"}, "Schätzstufe"),
    ({"id": "1"}, "Schätzstufe"),
])
def test_ungueltiger_rest(client, daten, meldung):
    c, mod = client
    r = c.post("/rest", headers=HEADERS, data=daten)
    assert r.status_code == 400 and meldung in r.get_data(as_text=True)
    assert mahlzeit(mod)["rest_g"] is None


def test_unbekannte_mahlzeit_404(client):
    c, _ = client
    assert c.get("/rest?id=99", headers=HEADERS).status_code == 404


def test_ohne_kcal_bleiben_kcal_leer(client):
    c, mod = client
    c.post("/produkt", headers=HEADERS, data={"marke": "X", "sorte": "Ohne Deklaration", "packung_g": "100",
                                              "bestand_packungen": "1"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "2", "menge_g": "50"})
    c.post("/rest", headers=HEADERS, data={"id": "2", "stufe": "nichts"})
    m = mod.db().execute("SELECT gefressen_g, kcal FROM mahlzeit WHERE id = 2").fetchone()
    assert tuple(m) == (50, None)


def test_alte_mahlzeit_nicht_mehr_offen(client):
    c, mod = client
    alt = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=49)).isoformat(timespec="seconds")
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET zeit = ?", (alt,))
    html = c.get("/fuettern", headers=HEADERS).get_data(as_text=True)
    assert "<h2>Rest eintragen</h2>" not in html
    # Detailseite bleibt erreichbar
    assert c.get("/rest?id=1", headers=HEADERS).status_code == 200
