"""Tests für Bestand: Reichweite, knapp, Lieferung, Einkaufsliste (HA-Aufrufe ohne Netzwerk)."""
import datetime
import importlib
import os
import sys

import pytest
from werkzeug.datastructures import MultiDict

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
ALEX, KIND = ({"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": n} for n in ("Alex", "Mia"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    c = app_module.app.test_client()
    for sorte, packungen in (("Pute", "2"), ("Rind", "20"), ("Lachs", "0")):
        c.post("/produkt", headers=ALEX, data={"marke": "Animonda", "sorte": sorte, "packung_g": "100",
                                               "bestand_packungen": packungen})
    yield c, app_module
    sys.path.pop(0)


def mahlzeiten_vor(mod, produkt_id, tage, gramm=100):
    """Je Tag eine Mahlzeit über die letzten `tage` Tage (Bestand bleibt unberührt)."""
    con = mod.db()
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    with con:
        for t in range(tage, 0, -1):
            con.execute("INSERT INTO mahlzeit (katze_id, produkt_id, zeit, angeboten_g) VALUES (1, ?, ?, ?)",
                        (produkt_id, (jetzt - datetime.timedelta(days=t)).isoformat(timespec="seconds"), gramm))


def zeile(mod, produkt_id):
    con = mod.db()
    return next(z for z in mod.bestand_modul.uebersicht(con, 7) if z["id"] == produkt_id)


def test_reichweite_und_knapp(client):
    c, mod = client
    mahlzeiten_vor(mod, 1, 10)          # 100 g/Tag, 2 Packungen à 100 g → 2 Tage
    mahlzeiten_vor(mod, 2, 10)          # 20 Packungen → 20 Tage
    p, r, l = zeile(mod, 1), zeile(mod, 2), zeile(mod, 3)
    assert round(p["reichweite_tage"]) == 2 and p["knapp"]
    assert round(r["reichweite_tage"]) == 20 and not r["knapp"]
    assert l["reichweite_tage"] is None and not l["knapp"]  # ohne Verbrauch kein Urteil


def test_neue_sorte_wird_nicht_ueberschaetzt(client):
    c, mod = client
    mahlzeiten_vor(mod, 2, 1)  # eine Mahlzeit gestern: Zeitraum 1 Tag, nicht 14
    assert round(zeile(mod, 2)["reichweite_tage"]) == 20


def test_mindestbestand_hat_vorrang(client):
    c, mod = client
    mahlzeiten_vor(mod, 2, 10)
    c.post("/produkt", headers=ALEX, data={"id": "2", "marke": "Animonda", "sorte": "Rind", "packung_g": "100",
                                           "bestand_packungen": "20", "mindestbestand": "24"})
    assert zeile(mod, 2)["knapp"]
    c.post("/produkt", headers=ALEX, data={"id": "3", "marke": "Animonda", "sorte": "Lachs", "packung_g": "100",
                                           "bestand_packungen": "0", "mindestbestand": "0"})
    assert zeile(mod, 3)["knapp"]
    r = c.post("/produkt", headers=ALEX, data={"id": "3", "marke": "Animonda", "sorte": "Lachs", "mindestbestand": "1,5"})
    assert r.status_code == 400


def test_lieferung_fuer_mehrere_sorten(client):
    c, mod = client
    r = c.post("/bestand", headers=ALEX, data={"aktion": "auffuellen", "plus_1": "+12", "plus_3": "6", "plus_2": ""})
    assert r.status_code == 302 and "aufgefuellt=2" in r.headers["Location"]
    assert (zeile(mod, 1)["packungen"], zeile(mod, 2)["packungen"], zeile(mod, 3)["packungen"]) == (14, 20, 6)
    c.post("/bestand", headers=ALEX, data={"aktion": "auffuellen", "plus_1": "-20"})
    assert zeile(mod, 1)["packungen"] == 0  # nie negativ
    assert "Lieferung gespeichert (2 Sorten)" in c.get("/bestand?aufgefuellt=2", headers=ALEX).get_data(as_text=True)


@pytest.mark.parametrize("daten, meldung", [
    ({"plus_1": "x"}, "ganze Zahl"), ({}, "Keine Packungen"), ({"plus_1": "900"}, "500"),
])
def test_lieferung_fehler(client, daten, meldung):
    c, _ = client
    r = c.post("/bestand", headers=ALEX, data=dict(daten, aktion="auffuellen"))
    assert r.status_code == 400 and meldung in r.get_data(as_text=True)


def test_kind_darf_nicht_auffuellen_aber_einkauf(client, monkeypatch):
    c, mod = client
    c.post("/einstellungen", headers=ALEX, data=MultiDict([
        ("name", "Alex"), ("rolle", "erwachsen"), ("ha_name", ""), ("name", "Mia"), ("rolle", "kind"), ("ha_name", ""),
        ("einkauf_liste", "todo.einkaufsliste")]))
    assert c.post("/bestand", headers=KIND, data={"aktion": "auffuellen", "plus_1": "1"}).status_code == 403
    html = c.get("/bestand", headers=KIND).get_data(as_text=True)
    assert "Lieferung speichern" not in html and "Lieferungen tragen Erwachsene ein" in html
    gesendet = []
    monkeypatch.setattr(mod.einkauf, "hinzufuegen", lambda token, liste, texte: (gesendet.append((liste, texte)) or (1, 0)))
    r = c.post("/bestand", headers=KIND, data={"aktion": "einkauf", "produkt_id": "1"})
    assert r.status_code == 302 and gesendet == [("todo.einkaufsliste", ["Katzenfutter: Animonda Pute (100 g)"])]


def test_ohne_ha_verstaendlicher_fehler(client):
    c, _ = client
    c.post("/einstellungen", headers=ALEX, data={"einkauf_liste": "todo.einkaufsliste"})
    r = c.post("/bestand", headers=ALEX, data={"aktion": "einkauf", "produkt_id": "1"})
    assert r.status_code == 400 and "nur in Home Assistant" in r.get_data(as_text=True)


def test_einstellung_einkaufsliste_pruefen(client):
    c, mod = client
    r = c.post("/einstellungen", headers=ALEX, data={"einkauf_liste": "Einkauf"})
    assert r.status_code == 400 and "todo.einkaufsliste" in r.get_data(as_text=True)
    c.post("/einstellungen", headers=ALEX, data={"einkauf_liste": "todo.einkaufsliste", "einkauf_automatisch": "1"})
    e = mod.einkauf.laden(mod.db())
    assert e["liste"] == "todo.einkaufsliste" and e["automatisch"]


class Antwort:
    def __init__(self, daten=None):
        self.daten = daten or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self.daten


def test_hinzufuegen_ohne_doppelte(client, monkeypatch):
    _, mod = client
    e = mod.einkauf
    aufrufe = []

    def post(url, json=None, **_):
        aufrufe.append((url.rsplit("/", 1)[-1], json))
        if "get_items" in url:
            return Antwort({"service_response": {"todo.l": {"items": [{"summary": "Katzenfutter: A"}]}}})
        return Antwort()

    monkeypatch.setattr(e.requests, "post", post)
    assert e.hinzufuegen("t", "todo.l", ["Katzenfutter: A", "Katzenfutter: B", "Katzenfutter: B"]) == (1, 2)
    assert [a for a in aufrufe if a[0] == "add_item"] == [("add_item", {"entity_id": "todo.l", "item": "Katzenfutter: B"})]


def test_automatisch_einmal_je_knapp_phase(client, monkeypatch):
    c, mod = client
    con = mod.db()
    mod.einkauf.speichern(con, liste="todo.l", automatisch=True)
    gesendet = []
    monkeypatch.setattr(mod.einkauf, "hinzufuegen", lambda t, l, texte: (gesendet.extend(texte) or (len(texte), 0)))
    mahlzeiten_vor(mod, 1, 10)
    zeilen = lambda: mod.bestand_modul.uebersicht(con, 7)
    assert mod.einkauf.automatisch(con, "t", zeilen()) == 1
    assert mod.einkauf.automatisch(con, "t", zeilen()) == 0  # schon gemeldet
    mod.bestand_modul.auffuellen(con, {1: 30})                # wieder genug
    assert mod.einkauf.automatisch(con, "t", zeilen()) == 0
    mod.bestand_modul.auffuellen(con, {1: -30})               # erneut knapp → erneut melden
    assert mod.einkauf.automatisch(con, "t", zeilen()) == 1
    assert gesendet == ["Katzenfutter: Animonda Pute (100 g)"] * 2


def test_hinweis_heute_und_futter(client):
    c, mod = client
    mahlzeiten_vor(mod, 1, 10)
    assert "Bald nachkaufen:</strong> Animonda Pute" in c.get("/", headers=ALEX).get_data(as_text=True)
    assert "Bestand &amp; Einkauf · 1 knapp" in c.get("/futter", headers=ALEX).get_data(as_text=True)
