"""Tests für die PetKit-Übernahme (simulierter HA-Verlauf, ohne Netzwerk)."""
import datetime
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}
PROFIL = {"name": "Mimi", "geburtsjahr": "2023", "kastriert": "1", "freigang": "1", "gewicht_aktuell": "4,2",
          "aktivitaetsfaktor": "1.4", "petkit_besuch_entity": "sensor.mimi_datum_der_letzten_benutzung",
          "petkit_gewicht_entity": "sensor.mimi_letztes_gewicht"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    yield c, app_module
    sys.path.pop(0)


def vor(stunden):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=stunden)).isoformat()


def gewicht(stunden, wert, einheit="kg"):
    return {"state": str(wert), "attributes": {"unit_of_measurement": einheit}, "last_changed": vor(stunden)}


def besuch(stunden):
    zeitpunkt = vor(stunden)
    return {"state": zeitpunkt, "attributes": {"device_class": "timestamp"}, "last_changed": zeitpunkt}


@pytest.mark.parametrize("zustand, kg", [
    ({"state": "4.25", "attributes": {"unit_of_measurement": "kg"}}, 4.25),
    ({"state": "4250", "attributes": {"unit_of_measurement": "g"}}, 4.25),
    ({"state": "9.37", "attributes": {"unit_of_measurement": "lb"}}, pytest.approx(4.25, abs=0.01)),
    ({"state": "unknown", "attributes": {"unit_of_measurement": "kg"}}, None),
    ({"state": "0.1", "attributes": {"unit_of_measurement": "kg"}}, None),
    ({"state": "4.2", "attributes": {"unit_of_measurement": "stone"}}, None),
])
def test_einheiten(client, zustand, kg):
    _, mod = client
    assert mod.petkit.kilogramm(zustand) == kg


def test_profil_speichert_sensoren_und_prueft_format(client):
    c, mod = client
    assert c.post("/katze", headers=HEADERS, data=PROFIL).status_code == 302
    k = mod.db().execute("SELECT petkit_besuch_entity, petkit_gewicht_entity FROM katze").fetchone()
    assert tuple(k) == ("sensor.mimi_datum_der_letzten_benutzung", "sensor.mimi_letztes_gewicht")
    r = c.post("/katze", headers=HEADERS, data=dict(PROFIL, petkit_gewicht_entity="number.mimi_gewicht"))
    assert r.status_code == 400 and "Entitäts-ID" in r.get_data(as_text=True)


def test_abgleich_uebernimmt_gewicht_und_besuche(client):
    c, mod = client
    c.post("/katze", headers=HEADERS, data=PROFIL)
    aufrufe = []

    def abfragen(token, entity, seit):
        aufrufe.append((entity, seit))
        if "gewicht" in entity:
            return [gewicht(30, 4.21), gewicht(20, "4230", "g"), gewicht(10, 4.6), gewicht(5, 4.22), gewicht(4, "unavailable")]
        return [{"state": "unknown", "last_changed": vor(40)}, besuch(30), besuch(20), besuch(5)]

    con = mod.db()
    with con:
        con.execute("DELETE FROM gewicht")  # Wiegung aus dem Profil wäre jünger als die PetKit-Werte
    ergebnis = mod.petkit.abgleichen(con, "token", abfragen)
    assert ergebnis[1] == {"besuche": 3, "gewichte": 3, "verworfen": 1}
    werte = [tuple(r) for r in con.execute("SELECT kg, verworfen FROM gewicht WHERE quelle = 'petkit' ORDER BY zeit")]
    # 4,6 kg weicht > 5 % vom Median (4,22) ab → verworfen, aber gespeichert
    assert werte == [(4.21, 0), (4.23, 0), (4.6, 1), (4.22, 0)]
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 4.22
    # erster Abgleich ab 7 Tagen, danach ab dem gespeicherten Stand
    assert aufrufe[0][1] < vor(24 * 6.9)
    mod.petkit.abgleichen(con, "token", abfragen)
    assert aufrufe[-1][1] > vor(1)
    # doppelte Werte werden nicht erneut übernommen
    assert con.execute("SELECT COUNT(*) FROM gewicht WHERE quelle = 'petkit'").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM ereignis WHERE typ = 'toilette'").fetchone()[0] == 3


def test_ohne_sensoren_kein_abgleich(client):
    _, mod = client
    assert mod.petkit.abgleichen(mod.db(), "t", lambda *a: pytest.fail("darf nicht abfragen")) == {}


def test_neue_sensoren_setzen_abgleich_zurueck(client):
    c, mod = client
    c.post("/katze", headers=HEADERS, data=PROFIL)
    con = mod.db()
    mod.petkit.abgleichen(con, "t", lambda *a: [])
    assert con.execute("SELECT petkit_abgleich FROM katze").fetchone()[0] is not None
    c.post("/katze", headers=HEADERS, data=dict(PROFIL, petkit_gewicht_entity="sensor.mimi_anderes_gewicht"))
    assert con.execute("SELECT petkit_abgleich FROM katze").fetchone()[0] is None


def test_heute_zeigt_toilettengaenge_und_verlauf_nutzt_petkit(client):
    c, mod = client
    c.post("/katze", headers=HEADERS, data=PROFIL)
    con = mod.db()
    mod.petkit.abgleichen(con, "t", lambda token, entity, seit: [besuch(3), besuch(2)] if "benutzung" in entity
                          else [gewicht(3, 4.2)])
    html = c.get("/", headers=HEADERS).get_data(as_text=True)
    assert "Toilettengänge (24 Stunden)" in html and '<span class="wert">2</span>' in html
    # Gewicht von der Toilette zählt im Verlauf; Toilettengänge nicht in der Gesundheitsliste
    assert "kein Gewicht von der Toilette" not in " ".join(mod.verlauf_modul.gewicht_daten(con, 1, 30)["hinweise"])
    assert mod.gesundheit.liste(con, 1) == []


def test_drei_tage_ohne_petkit_gewicht(client):
    c, mod = client
    c.post("/katze", headers=HEADERS, data=PROFIL)
    con = mod.db()
    mod.petkit.abgleichen(con, "t", lambda token, entity, seit: [gewicht(24 * 4, 4.2)] if "gewicht" in entity else [])
    hinweise = mod.verlauf_modul.gewicht_daten(con, 1, 30)["hinweise"]
    assert any("kein Gewicht von der Toilette" in h for h in hinweise)


def test_viele_toilettengaenge(client):
    c, mod = client
    c.post("/katze", headers=HEADERS, data=PROFIL)
    con = mod.db()
    normal = [besuch(26 + i * 24) for i in range(14)] + [besuch(38 + i * 24) for i in range(14)]  # ~2 je Tag
    mod.petkit.abgleichen(con, "t", lambda token, entity, seit: normal if "benutzung" in entity else [])
    assert mod.petkit.viele_gaenge(con, 1) is None
    con.execute("UPDATE katze SET petkit_abgleich = NULL")
    con.commit()
    viele = [besuch(1 + i * 3) for i in range(7)]  # 7 in 24 h
    mod.petkit.abgleichen(con, "t", lambda token, entity, seit: viele if "benutzung" in entity else [])
    text = mod.petkit.viele_gaenge(con, 1)
    assert text and text.startswith("7 Toilettengänge in 24 Stunden")
    assert "Toilettengänge in 24 Stunden" in c.get("/", headers=HEADERS).get_data(as_text=True)


def test_vorschlaege_aus_ha(client, monkeypatch):
    _, mod = client

    class Antwort:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"entity_id": "sensor.mimi_datum_der_letzten_benutzung", "attributes": {"device_class": "timestamp", "friendly_name": "Mimi Datum der letzten Benutzung"}},
                {"entity_id": "sensor.mimi_letztes_gewicht", "attributes": {"device_class": "weight", "unit_of_measurement": "kg", "friendly_name": "Mimi Letztes Gewicht"}},
                {"entity_id": "sensor.mimi_gewicht", "attributes": {"device_class": "weight", "unit_of_measurement": "kg", "friendly_name": "Katzenfutter Mimi Gewicht"}},
                {"entity_id": "sensor.wohnzimmer_temperatur", "attributes": {"unit_of_measurement": "°C"}},
                {"entity_id": "number.mimi_gewicht", "attributes": {"device_class": "weight", "unit_of_measurement": "kg"}},
            ]

    monkeypatch.setattr(mod.petkit.requests, "get", lambda *a, **k: Antwort())
    besuch_v, gewicht_v = mod.petkit.vorschlaege("t", "Mimi")
    assert [e for e, _ in besuch_v] == ["sensor.mimi_datum_der_letzten_benutzung"]
    # eigener Sensor des Add-ons und number.* werden ausgeblendet
    assert [e for e, _ in gewicht_v] == ["sensor.mimi_letztes_gewicht"]
