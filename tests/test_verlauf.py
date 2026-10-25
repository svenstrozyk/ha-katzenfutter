"""Tests für Verlauf: Tagesmedian, Trend, Gewichtshinweise, kcal je Tag, Seite."""
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
    c.post("/katze", headers=HEADERS, data={"name": "Mimi", "gewicht_aktuell": "4,2", "aktivitaetsfaktor": "1.4"})
    yield c, app_module
    sys.path.pop(0)


def tag(mod, vor_tagen):
    return mod.verlauf_modul.heute_lokal() - datetime.timedelta(days=vor_tagen)


def wiegung(mod, vor_tagen, kg, quelle="manuell", stunde=8):
    zeitpunkt = datetime.datetime.combine(tag(mod, vor_tagen), datetime.time(stunde), tzinfo=mod.zeit.BERLIN)
    con = mod.db()
    with con:
        con.execute("INSERT INTO gewicht (katze_id, zeit, kg, quelle) VALUES (1, ?, ?, ?)",
                    (mod.zeit.iso(zeitpunkt), kg, quelle))


def leeren(mod):
    con = mod.db()
    with con:
        con.execute("DELETE FROM gewicht")


def test_tagesmedian_und_trend(client):
    _, mod = client
    v = mod.verlauf_modul
    t = datetime.date(2026, 10, 1)
    zeile = lambda d, kg, verworfen=0: {"zeit": mod.zeit.iso(datetime.datetime.combine(d, datetime.time(9), tzinfo=mod.zeit.BERLIN)),
                                         "kg": kg, "verworfen": verworfen}
    mediane = v.tagesmediane([zeile(t, 4.0), zeile(t, 4.4), zeile(t, 4.2), zeile(t, 9.0, verworfen=1),
                              zeile(t + datetime.timedelta(days=3), 4.6)])
    assert mediane == {t: 4.2, t + datetime.timedelta(days=3): 4.6}
    tr = v.trend(mediane)
    assert tr[t] == pytest.approx(4.2) and tr[t + datetime.timedelta(days=3)] == pytest.approx(4.4)


def test_ausreisser_regel(client):
    _, mod = client
    v = mod.verlauf_modul
    assert v.ist_ausreisser(4.5, 4.2) is True   # +7 %
    assert v.ist_ausreisser(4.3, 4.2) is False  # +2,4 %
    assert v.ist_ausreisser(4.3, None) is False


@pytest.mark.parametrize("werte, erwartet", [
    ([(14, 4.20), (7, 4.20), (0, 4.10)], "Gewichtsverlust 2,4 % in einer Woche"),
    ([(28, 4.40), (0, 4.15)], "Gewichtsverlust 5,7 % in 4 Wochen"),
    ([(28, 4.00), (0, 4.25)], "Gewichtszunahme 6,2 % in 4 Wochen"),
    ([(7, 4.20), (0, 4.15)], None),
])
def test_gewichtshinweise(client, werte, erwartet):
    _, mod = client
    leeren(mod)
    for vor, kg in werte:
        wiegung(mod, vor, kg)
    hinweise = mod.verlauf_modul.gewicht_daten(mod.db(), 1, 30)["hinweise"]
    if erwartet:
        assert any(erwartet in h for h in hinweise), hinweise
    else:
        assert hinweise == []


def test_referenz_weiter_als_3_tage_entfernt_zaehlt_nicht(client):
    _, mod = client
    leeren(mod)
    wiegung(mod, 12, 4.4)
    wiegung(mod, 0, 4.1)
    hinweise = mod.verlauf_modul.gewicht_daten(mod.db(), 1, 30)["hinweise"]
    assert not any("einer Woche" in h for h in hinweise)


def test_petkit_luecke(client):
    _, mod = client
    wiegung(mod, 4, 4.2, quelle="petkit")
    hinweise = mod.verlauf_modul.gewicht_daten(mod.db(), 1, 30)["hinweise"]
    assert any("kein Gewicht von der Toilette" in h for h in hinweise)


def test_gewicht_eintragen_aktualisiert_profil_nur_wenn_juengste(client):
    c, mod = client
    r = c.post("/verlauf", headers=HEADERS, data={"kg": "4,3", "datum": tag(mod, 0).isoformat(), "tage": "30"})
    assert r.status_code == 302 and "gespeichert=1" in r.headers["Location"]
    c.post("/verlauf", headers=HEADERS, data={"kg": "4,0", "datum": tag(mod, 5).isoformat()})
    con = mod.db()
    assert con.execute("SELECT gewicht_aktuell FROM katze").fetchone()[0] == 4.3
    assert con.execute("SELECT COUNT(*) FROM gewicht").fetchone()[0] == 3  # inkl. Profil-Eintrag


@pytest.mark.parametrize("daten, meldung", [
    ({"kg": "42"}, "zwischen 1 und 15"),
    ({"kg": "vier"}, "Bitte Gewicht"),
    ({"kg": "4,2", "datum": "2999-01-01"}, "Zukunft"),
    ({"kg": "4,2", "datum": "kein-datum"}, "Bitte Gewicht"),
])
def test_ungueltiges_gewicht(client, daten, meldung):
    c, _ = client
    r = c.post("/verlauf", headers=HEADERS, data=daten)
    assert r.status_code == 400 and meldung in r.get_data(as_text=True)


def test_kcal_tage(client):
    c, mod = client
    c.post("/produkt", headers=HEADERS, data={"marke": "A", "sorte": "Pute", "packung_g": "100", "kcal_100g": "100",
                                              "bestand_packungen": "5"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "wenig"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "50"})
    reihe = mod.verlauf_modul.kcal_tage(mod.db(), 1, 7)
    assert len(reihe) == 7 and reihe[-1]["tag"] == tag(mod, 0)
    assert reihe[-1]["futter"] == pytest.approx(90) and reihe[-1]["geschaetzt"] and reihe[-1]["offen"] == 1
    assert reihe[0]["futter"] == 0


@pytest.mark.parametrize("tage", [7, 30, 90])
def test_seite_mit_diagrammen(client, tage):
    c, mod = client
    c.post("/produkt", headers=HEADERS, data={"marke": "A", "sorte": "Pute", "packung_g": "100", "kcal_100g": "100",
                                              "bestand_packungen": "5"})
    c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    c.post("/rest", headers=HEADERS, data={"id": "1", "stufe": "nichts"})
    wiegung(mod, 3, 4.25)
    html = c.get(f"/verlauf?tage={tage}", headers=HEADERS).get_data(as_text=True)
    assert 'aria-label="Gewicht: Tageswerte' in html and 'aria-label="Gefressene kcal je Tag' in html
    assert "Trend 7 Tage" in html and "Bedarf 288" in html
    assert 'data-tip="' in html
    assert 'href="/' not in html


def test_leerer_verlauf(client):
    c, mod = client
    con = mod.db()
    with con:
        con.execute("DELETE FROM gewicht")
    html = c.get("/verlauf", headers=HEADERS).get_data(as_text=True)
    assert "Noch keine Wiegung" in html and "Noch keine erfassten Mahlzeiten" in html


def test_ungueltiger_zeitraum_faellt_auf_30(client):
    c, _ = client
    html = c.get("/verlauf?tage=1000", headers=HEADERS).get_data(as_text=True)
    assert 'href="verlauf?tage=30" aria-pressed="true"' in html


def test_gewichtshinweis_auf_heute(client):
    c, mod = client
    leeren(mod)
    wiegung(mod, 7, 4.3)
    wiegung(mod, 0, 4.1)
    html = c.get("/", headers=HEADERS).get_data(as_text=True)
    assert "Gewichtsverlust" in html
