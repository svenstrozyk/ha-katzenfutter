"""Tests für die Präferenzerkennung (Rechenbeispiele von Hand nachvollziehbar)."""
import datetime
import importlib
import os
import sys

import pytest

ADDON_APP = os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app")
HEADERS = {"X-Ingress-Path": "/api/hassio_ingress/test", "X-Remote-User-Display-Name": "Alex"}
BASIS = datetime.datetime(2026, 10, 1, 7, 0, tzinfo=datetime.timezone.utc)


def m(i, produkt, gefressen, angeboten=100, herkunft="gewogen", verweigert=0, stunden=None, marke="A",
      textur="pastete", proteine="Pute"):
    """Synthetische Mahlzeit; standardmäßig zwei Mahlzeiten je Tag (7 und 17 Uhr UTC)."""
    zeitpunkt = BASIS + (datetime.timedelta(hours=stunden) if stunden is not None
                         else datetime.timedelta(days=i // 2, hours=10 * (i % 2)))
    return {"id": i, "zeit": zeitpunkt.isoformat(), "produkt_id": produkt, "angeboten_g": angeboten,
            "gefressen_g": gefressen, "rest_herkunft": herkunft, "verweigert": verweigert,
            "marke": marke, "textur": textur, "proteine": proteine}


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "1")
    sys.path.insert(0, os.path.abspath(ADDON_APP))
    import app as app_module
    importlib.reload(app_module)
    yield app_module
    sys.path.pop(0)


def test_gewichte(mod):
    p = mod.praeferenz
    liste = [m(0, 1, 90, stunden=0), m(1, 1, 90, herkunft="geschaetzt", stunden=4), m(2, 1, 90, stunden=8),
             m(3, 2, 90, stunden=40)]
    b = p.bewerten(liste)
    # erste zwei Mahlzeiten von Sorte 1: halbes Gewicht (Neophobie)
    assert b[0]["w"] == pytest.approx(0.5) and b[1]["w"] == pytest.approx(0.3)
    assert b[2]["w"] == pytest.approx(1.0)
    # Sorte 2: neu (×0,5) und nach > 12 h Pause (×0,5)
    assert b[3]["w"] == pytest.approx(0.25)


def test_baseline_ohne_eigene_mahlzeit(mod):
    b = mod.praeferenz.bewerten([m(0, 1, 100), m(1, 1, 50), m(2, 1, 80), m(3, 1, 60)])
    # Mahlzeit 3: Vergleich mit 1,0 / 0,5 / 0,8
    assert b[3]["baseline"] == pytest.approx((1.0 + 0.5 + 0.8) / 3)
    # Mahlzeit 0: weniger als 3 vorher → ±14 Tage
    assert b[0]["baseline"] == pytest.approx((0.5 + 0.8 + 0.6) / 3)


def test_score_formel(mod):
    p = mod.praeferenz
    bewertungen = [{"mahlzeit": m(0, 1, 0), "a": 0.9, "baseline": 0.7, "w": 1.0},
                   {"mahlzeit": m(1, 1, 0), "a": 0.8, "baseline": 0.7, "w": 0.6}]
    e = p.auswerten(bewertungen)[("produkt", "1")]
    # (1,0·0,2 + 0,6·0,1) / (1,6 + 3) = 0,26 / 4,6
    assert e["score"] == pytest.approx(0.26 / 4.6)
    assert e["n"] == 2 and e["status"] == "zu_wenig"


def test_lieblingsfutter_und_abgelehnt(mod):
    p = mod.praeferenz
    liste = []
    # Sorte 1 (Huhn): fast immer leer; Sorte 2 (Fisch): meist halb; Sorte 3: neutral
    for tag in range(14):
        liste.append(m(len(liste), 1, 100, proteine="Huhn", marke="A", stunden=tag * 24))
        liste.append(m(len(liste), 2, 40, proteine="Fisch", marke="B", textur="stueckchen", stunden=tag * 24 + 5))
        liste.append(m(len(liste), 3, 75, proteine="Pute", marke="A", stunden=tag * 24 + 10))
    e = p.auswerten(p.bewerten(liste))
    assert e[("produkt", "1")]["status"] == "liebling"
    assert e[("produkt", "2")]["status"] == "abgelehnt"
    assert e[("produkt", "3")]["status"] == "neutral"
    assert e[("protein", "huhn")]["status"] == "liebling"
    assert e[("textur", "Stueckchen")]["status"] == "abgelehnt"
    assert e[("marke", "B")]["score"] < 0 < e[("marke", "A")]["score"]


def test_zwei_mal_verweigert(mod):
    p = mod.praeferenz
    liste = [m(0, 1, 90), m(1, 1, 90), m(2, 1, 90), m(3, 2, 0, verweigert=1), m(4, 2, 0, verweigert=1)]
    assert p.auswerten(p.bewerten(liste))[("produkt", "2")]["status"] == "abgelehnt"


def test_zu_wenig_daten(mod):
    p = mod.praeferenz
    liste = [m(0, 1, 100), m(1, 1, 100), m(2, 2, 50)]
    e = p.auswerten(p.bewerten(liste))
    assert e[("produkt", "1")]["status"] == "zu_wenig"


def test_akzeptanzeinbruch(mod):
    p = mod.praeferenz
    jetzt = BASIS + datetime.timedelta(days=20)
    normal = [m(i, 1 + i % 2, 90, stunden=i * 12) for i in range(30)]  # Tage 0–14
    neu = [m(100 + i, 1 + i % 2, 40, stunden=(18 * 24) + i * 12) for i in range(4)]  # Tage 18–19
    assert p.akzeptanzeinbruch(p.bewerten(normal + neu), jetzt=jetzt) is True
    gleich = [m(100 + i, 1 + i % 2, 85, stunden=(18 * 24) + i * 12) for i in range(4)]
    assert p.akzeptanzeinbruch(p.bewerten(normal + gleich), jetzt=jetzt) is False


def test_offene_reste_zaehlen_nicht_aber_fuer_pause(mod):
    p = mod.praeferenz
    # Mahlzeit mit offenem Rest um 6 h verhindert die Pausenregel für die Mahlzeit um 15 h
    liste = [m(0, 1, 90, stunden=0), m(1, 1, 90, stunden=1), m(2, 1, 90, stunden=15)]
    ohne = p.bewerten(liste, [x["zeit"] for x in liste])
    mit = p.bewerten(liste, [x["zeit"] for x in liste] + [(BASIS + datetime.timedelta(hours=6)).isoformat()])
    assert ohne[2]["w"] == pytest.approx(0.5) and mit[2]["w"] == pytest.approx(1.0)


def test_seiten_und_sperren(mod):
    c = mod.app.test_client()
    for sorte in ("Huhn", "Fisch"):
        c.post("/produkt", headers=HEADERS, data={"marke": "A", "sorte": sorte, "packung_g": "100",
                                                  "bestand_packungen": "50", "proteine": sorte})
    for _ in range(2):
        c.post("/fuettern", headers=HEADERS, data={"produkt_id": "2", "menge_g": "100"})
    for i in (1, 2):
        c.post("/rest", headers=HEADERS, data={"id": str(i), "stufe": "unberuehrt", "verweigert": "1"})
    for _ in range(3):
        c.post("/fuettern", headers=HEADERS, data={"produkt_id": "1", "menge_g": "100"})
    for i in (3, 4, 5):
        c.post("/rest", headers=HEADERS, data={"id": str(i), "stufe": "nichts"})
    html = c.get("/futter", headers=HEADERS).get_data(as_text=True)
    assert "✕ wird nicht gemocht" in html and "Vorlieben" in html
    seite = c.get("/produkt?id=2", headers=HEADERS).get_data(as_text=True)
    assert "Sorte sperren" in seite and "2×" in seite
    # gespeichert in der Tabelle praeferenz
    assert mod.db().execute("SELECT status FROM praeferenz WHERE bezug = 'produkt' AND schluessel = '2'").fetchone()[0] == "abgelehnt"
    # nie automatisch gesperrt
    assert mod.db().execute("SELECT status FROM produkt WHERE id = 2").fetchone()[0] == "aktiv"
    r = c.post("/sperren", headers=HEADERS, data={"id": "2"})
    assert r.status_code == 302
    assert mod.db().execute("SELECT status FROM produkt WHERE id = 2").fetchone()[0] == "gesperrt"
    assert "Fisch" not in c.get("/fuettern", headers=HEADERS).get_data(as_text=True).split("<h2>Heute</h2>")[0]
