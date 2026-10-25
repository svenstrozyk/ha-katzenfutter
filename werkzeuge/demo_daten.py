"""Demo-Datenbank für Screenshots (erfundene Werte, keine echten Produkte).

Aufruf: python3 werkzeuge/demo_daten.py <ordner>
Danach: DEV_MODE=1 DEV_BENUTZER=Alex DATA_DIR=<ordner> python3 katzenfutter/app/app.py
"""
import datetime
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "katzenfutter", "app"))
import datenbank  # noqa: E402
import fachlogik  # noqa: E402
import zeit  # noqa: E402

ordner = sys.argv[1]
os.makedirs(ordner, exist_ok=True)
pfad = os.path.join(ordner, "katzenfutter.db")
if os.path.exists(pfad):
    sys.exit(f"{pfad} existiert schon – bitte einen leeren Ordner angeben.")
datenbank.migrieren(pfad)
con = datenbank.verbinden(pfad)
random.seed(7)
jetzt = zeit.jetzt()
heute = jetzt.astimezone(zeit.BERLIN).date()
erstellt = zeit.iso(jetzt - datetime.timedelta(days=40))

# (Sorte, Linie, Protein, Fett, Asche, Faser, Feuchte, Preis, Proteine, Textur, Vorliebe, EAN)
SORTEN = [
    ("Pute & Herz", "Feinkost", 11.0, 5.5, 2.0, 0.5, 80.0, 1.19, "Pute", "Pastete", 1.0, "4006381333931"),
    ("Rind pur", "Feinkost", 10.5, 6.0, 2.2, 0.4, 79.5, 1.29, "Rind", "Pastete", 0.86, "9002200000003"),
    ("Lachs in Gelee", "Meer", 9.5, 4.5, 2.0, 0.3, 81.0, 1.49, "Lachs", "Stückchen in Gelee", 0.45, None),
]
with con:
    con.execute("UPDATE katze SET name = 'Luna', geburtsjahr = 2023, gewicht_aktuell = 4.2 WHERE id = 1")
    for i, (sorte, linie, rp, rf, ra, rfa, fe, preis, proteine, textur, _, ean) in enumerate(SORTEN, start=1):
        con.execute(
            "INSERT INTO produkt (id, ean, marke, linie, sorte, futterart, packung_g, packungstyp, rohprotein, rohfett, "
            "rohasche, rohfaser, feuchte, kcal_100g, kcal_herkunft, textur, proteine, getreidefrei, zuckerfrei, preis, "
            "erstellt) VALUES (?, ?, 'Musterküche', ?, ?, 'allein', 85, 'Schale', ?, ?, ?, ?, ?, ?, 'berechnet', ?, ?, 1, 1, ?, ?)",
            (i, ean, linie, sorte, rp, rf, ra, rfa, fe, fachlogik.kcal_100g_berechnet(rp, rf, ra, rfa, fe), textur,
             proteine, preis, erstellt))
        con.execute("INSERT INTO bestand (produkt_id, packungen, angebrochen_g) VALUES (?, ?, ?)",
                    (i, [14, 9, 3][i - 1], 42.5 if i == 1 else None))
    con.execute("INSERT INTO produkt (id, marke, sorte, futterart, packung_g, stueck_g, kcal_100g, kcal_herkunft, preis, "
                "erstellt) VALUES (4, 'Musterküche', 'Knusperkissen Huhn', 'snack', 60, 1.5, 420, 'deklariert', 2.49, ?)",
                (erstellt,))
    personen = [{"name": "Alex", "rolle": "erwachsen", "ha_name": ""}, {"name": "Sam", "rolle": "erwachsen", "ha_name": ""},
                {"name": "Kind 1", "rolle": "kind", "ha_name": ""}, {"name": "Kind 2", "rolle": "kind", "ha_name": ""}]
    con.execute("INSERT INTO einstellung (schluessel, wert) VALUES ('personen', ?)", (json.dumps(personen, ensure_ascii=False),))
    con.execute("INSERT INTO einstellung (schluessel, wert) VALUES ('snack_limit_kinder', '2')")

    stufen = [("nichts", 0.0), ("wenig", 0.10), ("haelfte", 0.5), ("viel", 0.75)]
    for tag_nr in range(30):
        tag = heute - datetime.timedelta(days=29 - tag_nr)
        for stunde in (7, 13, 19):
            zeitpunkt = datetime.datetime.combine(tag, datetime.time(stunde, random.randint(0, 40)), tzinfo=zeit.BERLIN)
            if zeitpunkt > jetzt - datetime.timedelta(minutes=50):
                continue
            produkt_id = random.choices([1, 2, 3], weights=[5, 4, 2])[0]
            vorliebe = SORTEN[produkt_id - 1][10]
            angeboten = 85.0
            offen = tag == heute and stunde == max(h for h in (7, 13, 19) if datetime.datetime.combine(
                tag, datetime.time(h), tzinfo=zeit.BERLIN) < jetzt - datetime.timedelta(minutes=50))
            person = random.choice(["Alex", "Sam", "Sam", "Kind 1"])
            if offen:
                con.execute("INSERT INTO mahlzeit (katze_id, produkt_id, zeit, person, angeboten_g, erfasst, erfasst_von) "
                            "VALUES (1, ?, ?, ?, ?, ?, ?)", (produkt_id, zeit.iso(zeitpunkt), person, angeboten,
                                                            zeit.iso(zeitpunkt), person))
                continue
            gefressen_anteil = min(1.0, max(0.0, random.gauss(vorliebe, 0.12)))
            gewogen = random.random() < 0.2
            if gewogen:
                rest = round(angeboten * (1 - gefressen_anteil), 1)
                herkunft = "gewogen"
            else:
                stufe = min(stufen, key=lambda s: abs(s[1] - (1 - gefressen_anteil)))
                rest, herkunft = angeboten * stufe[1], "geschaetzt"
            gefressen = angeboten - rest
            kcal = gefressen * con.execute("SELECT kcal_100g FROM produkt WHERE id = ?", (produkt_id,)).fetchone()[0] / 100
            con.execute(
                "INSERT INTO mahlzeit (katze_id, produkt_id, zeit, person, angeboten_g, rest_g, rest_herkunft, gefressen_g, "
                "kcal, verweigert, erfasst, erfasst_von, erinnert) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (produkt_id, zeit.iso(zeitpunkt), person, angeboten, rest, herkunft, gefressen, kcal,
                 zeit.iso(zeitpunkt), person, zeit.iso(zeitpunkt)))
        if random.random() < 0.7:
            zeitpunkt = datetime.datetime.combine(tag, datetime.time(17, 30), tzinfo=zeit.BERLIN)
            if zeitpunkt < jetzt:
                con.execute("INSERT INTO snack (katze_id, produkt_id, zeit, person, stueck, menge_g, kcal, erfasst, erfasst_von) "
                            "VALUES (1, 4, ?, ?, 2, 3, 12.6, ?, ?)",
                            (zeit.iso(zeitpunkt), random.choice(["Kind 1", "Kind 2", "Sam"]), zeit.iso(zeitpunkt), "Sam"))
        if tag_nr % 4 == 1:
            zeitpunkt = datetime.datetime.combine(tag, datetime.time(8, 15), tzinfo=zeit.BERLIN)
            con.execute("INSERT INTO gewicht (katze_id, zeit, kg, quelle) VALUES (1, ?, ?, 'manuell')",
                        (zeit.iso(zeitpunkt), round(4.32 - tag_nr * 0.004 + random.uniform(-0.03, 0.03), 2)))
    haarballen = datetime.datetime.combine(heute - datetime.timedelta(days=9), datetime.time(21, 5), tzinfo=zeit.BERLIN)
    con.execute("INSERT INTO ereignis (katze_id, zeit, typ, person, notiz, erfasst, erfasst_von) "
                "VALUES (1, ?, 'haarballen', 'Sam', 'nach dem Freigang', ?, 'Sam')",
                (zeit.iso(haarballen), zeit.iso(haarballen)))
print(f"Demo-Daten in {pfad}")
