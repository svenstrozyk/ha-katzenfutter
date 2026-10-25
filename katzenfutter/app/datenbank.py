"""Datenbankzugriff und versionierte Migrationen (SQLite unter DATA_DIR).

Regeln:
- Schemaänderungen nur als neue Migration am Ende von MIGRATIONEN anhängen, bestehende nie ändern.
- Keine Migration verwirft Daten.
- Zeiten werden als ISO 8601 in UTC gespeichert.
"""
import datetime
import os
import sqlite3


def jetzt_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


MIGRATIONEN = [
    (
        1,
        "Testprotokoll aus Technik-Test 0.1.0 übernehmen",
        [
            # IF NOT EXISTS: bestehende Datenbank aus 0.1.0 wird samt Einträgen übernommen
            "CREATE TABLE IF NOT EXISTS testlog ("
            "id INTEGER PRIMARY KEY, ts TEXT, user TEXT, test TEXT, ok INTEGER, detail TEXT)",
        ],
    ),
    (
        2,
        "Grundschema MVP",
        [
            """CREATE TABLE katze (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                geburtsjahr INTEGER,
                kastriert INTEGER NOT NULL DEFAULT 1 CHECK (kastriert IN (0, 1)),
                freigang INTEGER NOT NULL DEFAULT 0 CHECK (freigang IN (0, 1)),
                gewicht_aktuell REAL CHECK (gewicht_aktuell > 0),
                zielgewicht REAL CHECK (zielgewicht > 0),
                bcs INTEGER CHECK (bcs BETWEEN 1 AND 9),
                aktivitaetsfaktor REAL NOT NULL DEFAULT 1.4 CHECK (aktivitaetsfaktor BETWEEN 0.5 AND 2.0),
                aktiv INTEGER NOT NULL DEFAULT 1 CHECK (aktiv IN (0, 1)),
                erstellt TEXT NOT NULL
            )""",
            """CREATE TABLE produkt (
                id INTEGER PRIMARY KEY,
                ean TEXT UNIQUE,
                marke TEXT NOT NULL,
                linie TEXT,
                sorte TEXT NOT NULL,
                futterart TEXT NOT NULL DEFAULT 'allein'
                    CHECK (futterart IN ('allein', 'ergaenzung', 'snack')),
                packung_g REAL CHECK (packung_g > 0),
                packungstyp TEXT,
                rohprotein REAL CHECK (rohprotein BETWEEN 0 AND 100),
                rohfett REAL CHECK (rohfett BETWEEN 0 AND 100),
                rohasche REAL CHECK (rohasche BETWEEN 0 AND 100),
                rohfaser REAL CHECK (rohfaser BETWEEN 0 AND 100),
                feuchte REAL CHECK (feuchte BETWEEN 0 AND 100),
                kcal_100g REAL CHECK (kcal_100g >= 0),
                kcal_herkunft TEXT CHECK (kcal_herkunft IN ('deklariert', 'berechnet')),
                textur TEXT,
                proteine TEXT,
                getreidefrei INTEGER CHECK (getreidefrei IN (0, 1)),
                zuckerfrei INTEGER CHECK (zuckerfrei IN (0, 1)),
                fleischanteil REAL CHECK (fleischanteil BETWEEN 0 AND 100),
                preis REAL CHECK (preis >= 0),
                status TEXT NOT NULL DEFAULT 'aktiv' CHECK (status IN ('aktiv', 'gesperrt', 'archiviert')),
                erstellt TEXT NOT NULL,
                geaendert TEXT
            )""",
            """CREATE TABLE mahlzeit (
                id INTEGER PRIMARY KEY,
                katze_id INTEGER NOT NULL REFERENCES katze(id),
                produkt_id INTEGER NOT NULL REFERENCES produkt(id),
                zeit TEXT NOT NULL,
                person TEXT,
                angeboten_g REAL NOT NULL CHECK (angeboten_g > 0),
                rest_g REAL CHECK (rest_g >= 0),
                rest_herkunft TEXT CHECK (rest_herkunft IN ('gewogen', 'geschaetzt')),
                gefressen_g REAL CHECK (gefressen_g >= 0),
                kcal REAL CHECK (kcal >= 0),
                verweigert INTEGER NOT NULL DEFAULT 0 CHECK (verweigert IN (0, 1)),
                notiz TEXT,
                CHECK (rest_g IS NULL OR rest_g <= angeboten_g)
            )""",
            "CREATE INDEX mahlzeit_katze_zeit ON mahlzeit (katze_id, zeit)",
            """CREATE TABLE snack (
                id INTEGER PRIMARY KEY,
                katze_id INTEGER NOT NULL REFERENCES katze(id),
                produkt_id INTEGER NOT NULL REFERENCES produkt(id),
                zeit TEXT NOT NULL,
                person TEXT,
                stueck REAL CHECK (stueck > 0),
                menge_g REAL CHECK (menge_g > 0),
                kcal REAL CHECK (kcal >= 0)
            )""",
            "CREATE INDEX snack_katze_zeit ON snack (katze_id, zeit)",
            """CREATE TABLE gewicht (
                id INTEGER PRIMARY KEY,
                katze_id INTEGER NOT NULL REFERENCES katze(id),
                zeit TEXT NOT NULL,
                kg REAL NOT NULL CHECK (kg > 0),
                quelle TEXT NOT NULL DEFAULT 'manuell' CHECK (quelle IN ('manuell', 'petkit')),
                verworfen INTEGER NOT NULL DEFAULT 0 CHECK (verworfen IN (0, 1))
            )""",
            "CREATE INDEX gewicht_katze_zeit ON gewicht (katze_id, zeit)",
            # typ ohne CHECK: PetKit-Ereignisse (Phase 3) kommen hinzu, Prüfung im Code
            """CREATE TABLE ereignis (
                id INTEGER PRIMARY KEY,
                katze_id INTEGER NOT NULL REFERENCES katze(id),
                zeit TEXT NOT NULL,
                typ TEXT NOT NULL,
                wert REAL,
                quelle TEXT NOT NULL DEFAULT 'manuell',
                person TEXT,
                notiz TEXT,
                foto TEXT,
                mahlzeit_id INTEGER REFERENCES mahlzeit(id) ON DELETE SET NULL
            )""",
            "CREATE INDEX ereignis_katze_zeit ON ereignis (katze_id, zeit)",
            """CREATE TABLE bestand (
                produkt_id INTEGER PRIMARY KEY REFERENCES produkt(id),
                packungen INTEGER NOT NULL DEFAULT 0 CHECK (packungen >= 0),
                angebrochen_g REAL CHECK (angebrochen_g >= 0)
            )""",
            "CREATE TABLE einstellung (schluessel TEXT PRIMARY KEY, wert TEXT)",
        ],
    ),
    (
        3,
        "Erste Katze anlegen (Gewicht offen)",
        [
            "INSERT INTO katze (name, geburtsjahr, kastriert, freigang, aktivitaetsfaktor, erstellt) "
            "SELECT 'Katze', NULL, 1, 1, 1.4, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') "
            "WHERE NOT EXISTS (SELECT 1 FROM katze)",
        ],
    ),
    (
        4,
        "Stückgewicht für Snacks",
        ["ALTER TABLE produkt ADD COLUMN stueck_g REAL CHECK (stueck_g > 0)"],
    ),
    (
        5,
        "Mahlzeit: Bestandsbewegung und Erfassungszeit (für Rückgängig)",
        [
            "ALTER TABLE mahlzeit ADD COLUMN aus_angebrochen_g REAL CHECK (aus_angebrochen_g >= 0)",
            "ALTER TABLE mahlzeit ADD COLUMN neue_packungen INTEGER CHECK (neue_packungen >= 0)",
            "ALTER TABLE mahlzeit ADD COLUMN erfasst TEXT",
        ],
    ),
    (
        6,
        "Erfasst von (HA-Benutzer) getrennt von der gebenden Person; Snack-Erfassungszeit",
        [
            "ALTER TABLE mahlzeit ADD COLUMN erfasst_von TEXT",
            "ALTER TABLE snack ADD COLUMN erfasst TEXT",
            "ALTER TABLE snack ADD COLUMN erfasst_von TEXT",
        ],
    ),
    (
        7,
        "Gesundheitsereignis: Warnzeichen und Erfassung",
        [
            "ALTER TABLE ereignis ADD COLUMN blut INTEGER NOT NULL DEFAULT 0 CHECK (blut IN (0, 1))",
            "ALTER TABLE ereignis ADD COLUMN apathie INTEGER NOT NULL DEFAULT 0 CHECK (apathie IN (0, 1))",
            "ALTER TABLE ereignis ADD COLUMN erfasst TEXT",
            "ALTER TABLE ereignis ADD COLUMN erfasst_von TEXT",
        ],
    ),
    (
        8,
        "Mahlzeit: Zeitpunkt der Rest-Erinnerung",
        ["ALTER TABLE mahlzeit ADD COLUMN erinnert TEXT"],
    ),
    (
        9,
        "Präferenzen je Sorte und Attribut (berechnet, wird bei jeder Auswertung erneuert)",
        [
            """CREATE TABLE praeferenz (
                katze_id INTEGER NOT NULL REFERENCES katze(id),
                bezug TEXT NOT NULL CHECK (bezug IN ('produkt', 'marke', 'textur', 'protein')),
                schluessel TEXT NOT NULL,
                score REAL,
                n INTEGER NOT NULL,
                verweigert INTEGER NOT NULL DEFAULT 0,
                akzeptanz REAL,
                status TEXT NOT NULL CHECK (status IN ('liebling', 'abgelehnt', 'neutral', 'zu_wenig')),
                stand TEXT NOT NULL,
                PRIMARY KEY (katze_id, bezug, schluessel)
            )""",
        ],
    ),
    (
        10,
        "Fehlende kcal bei Snacks und Mahlzeiten aus inzwischen ergänzten Futterdaten nachtragen",
        [
            # nur leere Felder füllen, vorhandene Werte bleiben
            "UPDATE snack SET menge_g = stueck * (SELECT stueck_g FROM produkt p WHERE p.id = snack.produkt_id) "
            "WHERE menge_g IS NULL AND stueck IS NOT NULL",
            "UPDATE snack SET kcal = menge_g * (SELECT kcal_100g FROM produkt p WHERE p.id = snack.produkt_id) / 100 "
            "WHERE kcal IS NULL AND menge_g IS NOT NULL",
            "UPDATE mahlzeit SET kcal = gefressen_g * (SELECT kcal_100g FROM produkt p WHERE p.id = mahlzeit.produkt_id) / 100 "
            "WHERE kcal IS NULL AND gefressen_g IS NOT NULL",
        ],
    ),
    (
        11,
        "PetKit: Sensoren je Katze und Stand des Abgleichs",
        [
            "ALTER TABLE katze ADD COLUMN petkit_besuch_entity TEXT",
            "ALTER TABLE katze ADD COLUMN petkit_gewicht_entity TEXT",
            "ALTER TABLE katze ADD COLUMN petkit_abgleich TEXT",
            "CREATE INDEX gewicht_quelle_zeit ON gewicht (katze_id, quelle, zeit)",
        ],
    ),
    (
        12,
        "Mindestbestand je Sorte (Packungen; leer = nach Reichweite)",
        [
            "ALTER TABLE produkt ADD COLUMN mindestbestand INTEGER CHECK (mindestbestand IS NULL OR mindestbestand >= 0)",
        ],
    ),
]


def verbinden(pfad):
    con = sqlite3.connect(pfad, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def schema_stand(con):
    try:
        return con.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def migrieren(pfad):
    """Wendet ausstehende Migrationen an und gibt den neuen Schemastand zurück.

    BEGIN IMMEDIATE sperrt die Datenbank, damit parallel startende Gunicorn-Worker
    nicht gleichzeitig migrieren. Schlägt ein Schritt fehl, wird alles zurückgerollt.
    """
    con = sqlite3.connect(pfad, timeout=30, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER PRIMARY KEY, beschreibung TEXT NOT NULL, angewendet TEXT NOT NULL)"
        )
        stand = schema_stand(con)
        for version, beschreibung, befehle in MIGRATIONEN:
            if version <= stand:
                continue
            for befehl in befehle:
                con.execute(befehl)
            con.execute(
                "INSERT INTO schema_version (version, beschreibung, angewendet) VALUES (?, ?, ?)",
                (version, beschreibung, jetzt_utc()),
            )
            stand = version
        con.execute("COMMIT")
        return stand
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


SICHERUNG_PRAEFIX = "katzenfutter-"


def sicherung(pfad, ordner, datum, behalten=7):
    """Vollständige Kopie der Datenbank als ordner/katzenfutter-JJJJ-MM-TT.db.

    Nutzt die Online-Sicherung von SQLite (konsistent auch bei laufenden Schreibzugriffen).
    Existiert die Kopie des Tages schon, passiert nichts. Danach bleiben die neuesten
    `behalten` Kopien erhalten. Gibt den Pfad einer neu angelegten Kopie zurück, sonst None.
    """
    os.makedirs(ordner, exist_ok=True)
    ziel = os.path.join(ordner, f"{SICHERUNG_PRAEFIX}{datum.isoformat()}.db")
    neu = None
    if not os.path.exists(ziel):
        temp = ziel + ".tmp"
        quelle = sqlite3.connect(pfad, timeout=30)
        kopie = sqlite3.connect(temp)
        try:
            quelle.backup(kopie)
        finally:
            kopie.close()
            quelle.close()
        os.replace(temp, ziel)
        neu = ziel
    vorhandene = sorted(n for n in os.listdir(ordner) if n.startswith(SICHERUNG_PRAEFIX) and n.endswith(".db"))
    for name in vorhandene[:-behalten] if behalten > 0 else []:
        os.remove(os.path.join(ordner, name))
    return neu


WIEDERHERSTELLEN = "wiederherstellen.db"


def wiederherstellen(pfad, ordner, zeitstempel):
    """Spielt ordner/wiederherstellen.db als Datenbank ein (vor dem Start aufrufen).

    Die bisherige Datenbank wird als vor-wiederherstellung-<zeitstempel>.db im selben Ordner
    beiseitegelegt. Eine Datei ohne gültige Katzenfutter-Datenbank wird nicht eingespielt,
    sondern in wiederherstellen-ungueltig.db umbenannt. Rückgabe: "eingespielt", "ungueltig" oder None.
    """
    quelle_pfad = os.path.join(ordner, WIEDERHERSTELLEN)
    if not os.path.isfile(quelle_pfad):
        return None
    try:
        quelle = sqlite3.connect(f"file:{quelle_pfad}?mode=ro", uri=True)
        try:
            gueltig = (quelle.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                       and schema_stand(quelle) > 0
                       and quelle.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'katze'").fetchone()[0] == 1)
        finally:
            quelle.close()
    except sqlite3.DatabaseError:
        gueltig = False
    if not gueltig:
        os.replace(quelle_pfad, os.path.join(ordner, "wiederherstellen-ungueltig.db"))
        return "ungueltig"
    if os.path.exists(pfad):
        alt = sqlite3.connect(pfad, timeout=30)
        kopie = sqlite3.connect(os.path.join(ordner, f"vor-wiederherstellung-{zeitstempel}.db"))
        try:
            alt.backup(kopie)
        finally:
            kopie.close()
            alt.close()
    quelle = sqlite3.connect(quelle_pfad)
    ziel = sqlite3.connect(pfad, timeout=30)
    try:
        quelle.backup(ziel)
    finally:
        ziel.close()
        quelle.close()
    os.remove(quelle_pfad)
    return "eingespielt"
