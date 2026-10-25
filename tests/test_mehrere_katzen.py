"""Tests für mehrere Katzen: Auswahl je Gerät (Cookie), getrennte Erfassung, gemeinsames Futter."""
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
    c.post("/produkt", headers=HEADERS, data={"marke": "A", "sorte": "Pute", "packung_g": "100", "bestand_packungen": "10"})
    yield c, app_module
    sys.path.pop(0)


def test_ein_katze_ohne_umschalter(client):
    c, _ = client
    html = c.get("/", headers=HEADERS).get_data(as_text=True)
    assert 'class="katzenwahl"' not in html and "Katze heute" in html


def test_neue_katze_wird_gewaehlt_und_getrennt_gefuehrt(client):
    c, mod = client
    r = c.post("/katze_neu", headers=HEADERS, data={"name": "Mimi"})
    assert r.status_code == 302
    cookie = r.headers["Set-Cookie"]
    assert "katzenfutter_katze=2" in cookie and "Path=/api/hassio_ingress/test/" in cookie and "HttpOnly" in cookie
    # Im Browser gilt das Cookie unter dem Ingress-Pfad; der Testclient ruft ohne Präfix auf
    c.set_cookie("katzenfutter_katze", "2")
    html = c.get("/", headers=HEADERS).get_data(as_text=True)
    assert "Mimi heute" in html and 'class="katzenwahl"' in html
    # Mahlzeit für Mimi; Bestand ist gemeinsam
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    con = mod.db()
    assert con.execute("SELECT katze_id FROM mahlzeit").fetchone()[0] == 2
    assert con.execute("SELECT packungen FROM bestand").fetchone()[0] == 9
    # zurück zu Katze: keine Mahlzeit heute
    r = c.post("/katze_waehlen", headers=HEADERS, data={"id": "1", "zurueck": "fuettern"})
    assert r.headers["Location"].endswith("/api/hassio_ingress/test/fuettern")
    c.set_cookie("katzenfutter_katze", "1")
    seite = c.get("/fuettern", headers=HEADERS).get_data(as_text=True)
    assert "<h2>Heute</h2>" not in seite
    assert "Katze heute" in c.get("/", headers=HEADERS).get_data(as_text=True)


def test_unbekannte_oder_inaktive_katze(client):
    c, mod = client
    assert c.post("/katze_waehlen", headers=HEADERS, data={"id": "99"}).status_code == 404
    c.post("/katze_neu", headers=HEADERS, data={"name": "Mimi"})
    c.set_cookie("katzenfutter_katze", "2")
    con = mod.db()
    with con:
        con.execute("UPDATE katze SET aktiv = 0 WHERE id = 2")
    # Cookie zeigt noch auf Mimi → Rückfall auf die erste aktive Katze
    assert "Katze heute" in c.get("/", headers=HEADERS).get_data(as_text=True)


def test_ungueltiger_name(client):
    c, mod = client
    c.post("/katze_neu", headers=HEADERS, data={"name": "  "})
    assert mod.db().execute("SELECT COUNT(*) FROM katze").fetchone()[0] == 1


def test_fremdes_ziel_wird_ignoriert(client):
    c, _ = client
    r = c.post("/katze_waehlen", headers=HEADERS, data={"id": "1", "zurueck": "https://beispiel.de"})
    assert r.headers["Location"].endswith("/api/hassio_ingress/test/")


def test_sensoren_fuer_jede_katze(client):
    c, mod = client
    c.post("/katze_neu", headers=HEADERS, data={"name": "Mimi"})
    con = mod.db()
    katzen = con.execute("SELECT * FROM katze WHERE aktiv = 1").fetchall()
    topics = [t for k in katzen for t, _ in mod.mqtt_sensoren.discovery(k)]
    assert any("katzenfutter_2/" in t for t in topics)
    eintrag = dict(mod.mqtt_sensoren.discovery(katzen[1]))["homeassistant/sensor/katzenfutter_2/kcal_heute/config"]
    assert eintrag["default_entity_id"] == "sensor.mimi_kcal_heute"
