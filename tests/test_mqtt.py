"""Tests für die MQTT-Sensoren (ohne Broker: Discovery, Zustand, Zugangsdaten, Auslöser)."""
import importlib
import json
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
    c.post("/katze", headers=HEADERS, data={"name": "Mimi", "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4"})
    c.post("/produkt", headers=HEADERS, data={"marke": "Animonda", "sorte": "Pute", "packung_g": "100",
                                              "kcal_100g": "100", "feuchte": "80", "bestand_packungen": "5"})
    yield c, app_module
    sys.path.pop(0)


class FakeClient:
    def __init__(self):
        self.nachrichten = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.nachrichten.append((topic, payload, retain))


def test_discovery_konfiguration(client):
    _, mod = client
    katze = mod.aktive_katze(mod.db())
    eintraege = dict(mod.mqtt_sensoren.discovery(katze))
    topic = "homeassistant/sensor/katzenfutter_1/kcal_heute/config"
    assert topic in eintraege
    k = eintraege[topic]
    assert k["default_entity_id"] == "sensor.mimi_kcal_heute"
    assert k["unique_id"] == "katzenfutter_1_kcal_heute"
    assert k["state_topic"] == "katzenfutter/1/zustand"
    assert k["availability_topic"] == "katzenfutter/status"
    assert k["device"]["name"] == "Katzenfutter Mimi"
    binaer = eintraege["homeassistant/binary_sensor/katzenfutter_1/tierarzt_hinweis/config"]
    assert binaer["device_class"] == "problem" and "json_attributes_topic" in binaer
    assert len(eintraege) == len(mod.mqtt_sensoren.SENSOREN)


def test_slug_mit_umlauten(client):
    _, mod = client
    assert mod.mqtt_sensoren.slug("Mäxchen Öl") == "maexchen_oel"


def test_zustand(client):
    c, mod = client
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "wenig"})
    con = mod.db()
    z = mod.mqtt_sensoren.zustand(con, mod.aktive_katze(con))
    assert z["kcal_heute"] == 90
    assert z["tagesbedarf"] == 288
    assert z["kcal_verbleibend"] == 198  # 287,5 − 90 = 197,5
    assert z["futter_gefressen_heute"] == 90
    assert z["wasser_aus_futter_heute"] == 72
    assert z["gewicht"] == 4.2
    assert z["bestand_packungen"] == 4
    assert z["bestand"]["Animonda Pute"] == {"packungen": 4, "angebrochen_g": 0}
    assert z["letzte_mahlzeit"].endswith("+00:00")
    assert z["keine_futteraufnahme"] is False and z["tierarzt_hinweis"] is False
    json.dumps(z)  # muss serialisierbar sein


def test_zustand_mit_tierarzt_hinweis(client):
    c, mod = client
    c.post("/gesundheit", headers=HEADERS, data={"typ": "erbrechen", "blut": "1"}, content_type="multipart/form-data")
    con = mod.db()
    z = mod.mqtt_sensoren.zustand(con, mod.aktive_katze(con))
    assert z["tierarzt_hinweis"] is True
    assert any("Blut" in t for t in z["hinweise"]["tierarzt"])


def test_senden_meldet_discovery_einmal(client):
    _, mod = client
    dienst = mod.mqtt_sensoren.Dienst(mod.DB_PATH, "", lambda: {})
    fake = FakeClient()
    dienst.senden(fake)
    topics = [t for t, _, _ in fake.nachrichten]
    assert "katzenfutter/status" in topics and "katzenfutter/1/zustand" in topics
    assert all(retain for _, _, retain in fake.nachrichten)
    anzahl = len(fake.nachrichten)
    dienst.senden(fake)
    # zweites Mal nur noch der Zustand
    assert len(fake.nachrichten) == anzahl + 1


def test_zugangsdaten_vom_supervisor(client, monkeypatch):
    _, mod = client

    class Antwort:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"host": "core-mosquitto", "port": 1883, "username": "addons", "password": "x"}}

    monkeypatch.setattr(mod.mqtt_sensoren.requests, "get", lambda *a, **k: Antwort())
    z = mod.mqtt_sensoren.zugangsdaten("token", {})
    assert z == {"host": "core-mosquitto", "port": 1883, "user": "addons", "password": "x"}


def test_zugangsdaten_aus_optionen_als_ersatz(client, monkeypatch):
    _, mod = client

    def fehler(*a, **k):
        raise mod.mqtt_sensoren.requests.ConnectionError("nicht erreichbar")

    monkeypatch.setattr(mod.mqtt_sensoren.requests, "get", fehler)
    z = mod.mqtt_sensoren.zugangsdaten("token", {"mqtt_host": "192.168.1.6", "mqtt_user": "u", "mqtt_password": "p"})
    assert z == {"host": "192.168.1.6", "port": 1883, "user": "u", "password": "p"}
    assert mod.mqtt_sensoren.zugangsdaten("", {}) is None


def test_post_loest_aktualisierung_aus(client):
    c, mod = client

    class Zaehler:
        anzahl = 0

        def aenderung(self):
            self.anzahl += 1

    z = Zaehler()
    mod.mqtt_dienst = z
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "50"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "0"})  # Fehler → kein Auslöser
    c.get("/", headers=HEADERS)
    assert z.anzahl == 1
    mod.mqtt_dienst = None


def test_kein_dienst_im_entwicklungsmodus(client):
    _, mod = client
    assert mod.mqtt_dienst is None
