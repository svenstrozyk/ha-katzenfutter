"""Tests für die Heute-Ansicht."""
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
    # 4,2 kg, Faktor 1,4 → MER ≈ 287,5 kcal; Futter 100 kcal/100 g, Feuchte 80 %, Schale 100 g
    c.post("/katze", headers=HEADERS, data={"name": "Mimi", "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4",
                                            "freigang": "1", "kastriert": "1"})
    c.post("/produkt", headers=HEADERS, data={"marke": "Animonda", "sorte": "Pute", "packung_g": "100",
                                              "kcal_100g": "100", "feuchte": "80", "bestand_packungen": "10"})
    yield c, app_module
    sys.path.pop(0)


def seite(c):
    return c.get("/", headers=HEADERS).get_data(as_text=True)


def vor(stunden):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=stunden)).isoformat(timespec="seconds")


def test_leerer_tag(client):
    c, _ = client
    html = seite(c)
    assert "Mimi heute" in html
    assert "288 kcal" in html  # Noch offen = voller Bedarf
    assert "Seit mehr als 24 Stunden" not in html  # frische Installation: kein Alarm
    # Vorschlag: 287,5 kcal / 100 kcal × 100 g
    assert "entspricht Pute" in html and "2,9 Packungen" in html


def test_bilanz_mit_geschaetztem_rest_und_snack(client):
    c, _ = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "wenig"})  # gefressen 90 g = 90 kcal
    c.post("/produkt", headers=HEADERS, data={"marke": "Leckerli", "sorte": "Huhn", "futterart": "snack",
                                              "kcal_100g": "400", "stueck_g": "2"})
    c.post("/snack", headers=HEADERS, data={"produkt_id": "2", "stueck": "1"})  # 8 kcal
    html = seite(c)
    assert "≈ 90 kcal" in html and "teils geschätzt" in html
    assert "8 kcal" in html
    # 287,5 − 90 − 8 = 189,5 → 190
    assert "190 kcal" in html
    # Wasser aus Futter: 90 g × 80 % = 72 ml; Richtwert 168–252 ml
    assert "≈ 72 ml" in html and "168–252 ml" in html


def test_offene_mahlzeit_als_offen_angezeigt(client):
    c, _ = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    html = seite(c)
    assert "Rest eintragen (1 offen)" in html
    assert "bis 100 kcal" in html
    # 287,5 − 100 (offen) = 187,5 → 188
    assert "188 kcal" in html


def test_keine_aufnahme_ueber_24_stunden(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "nichts"})
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET zeit = ?", (vor(25),))
    assert "Seit mehr als 24 Stunden keine Futteraufnahme" in seite(c)


def test_offener_rest_loest_keinen_alarm_aus(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "nichts"})
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET zeit = ? WHERE id = 1", (vor(30),))
        con.execute("UPDATE mahlzeit SET zeit = ? WHERE id = 2", (vor(5),))
    assert "Seit mehr als 24 Stunden" not in seite(c)


def test_alles_verweigert_in_24_stunden(client):
    c, _ = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "unberuehrt", "verweigert": "1"})
    html = seite(c)
    assert "nichts gefressen" in html


def test_gesundheit_erscheint_auf_heute(client):
    c, _ = client
    c.post("/gesundheit", headers=HEADERS, data={"typ": "erbrechen", "blut": "1"}, content_type="multipart/form-data")
    html = seite(c)
    assert "Blut bemerkt" in html and "Gesundheit heute" in html


def test_ohne_gewicht(client):
    c, mod = client
    con = mod.db()
    with con:
        con.execute("UPDATE katze SET gewicht_aktuell = NULL")
    html = seite(c)
    assert "Tagesbedarf unbekannt" in html


def test_gestern_zaehlt_nicht(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "nichts"})
    gestern = datetime.datetime.combine(
        datetime.datetime.now(mod.zeit.BERLIN).date() - datetime.timedelta(days=1),
        datetime.time(20, 0), tzinfo=mod.zeit.BERLIN)
    con = mod.db()
    with con:
        con.execute("UPDATE mahlzeit SET zeit = ?", (mod.zeit.iso(gestern),))
    html = seite(c)
    assert "288 kcal" in html and "≈ 100 kcal" not in html
