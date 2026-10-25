"""Zeitumrechnung: Speicherung in UTC, Anzeige und Tagesgrenzen in Europe/Berlin."""
import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def jetzt():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(zeitpunkt):
    return zeitpunkt.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def lokal(text):
    return datetime.datetime.fromisoformat(text).astimezone(BERLIN)


def tagesbeginn_utc(tag=None):
    """Beginn des Kalendertags in Berlin (Standard: heute) als UTC-ISO-Text."""
    tag = tag or jetzt().astimezone(BERLIN).date()
    return iso(datetime.datetime.combine(tag, datetime.time(0), tzinfo=BERLIN))


def heute_um(uhrzeit):
    """Uhrzeit „HH:MM“ von heute (Berlin) als UTC-Zeitpunkt."""
    stunde, minute = (int(t) for t in uhrzeit.split(":"))
    tag = jetzt().astimezone(BERLIN).date()
    return datetime.datetime.combine(tag, datetime.time(stunde, minute), tzinfo=BERLIN)
