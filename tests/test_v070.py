"""v0.7.0 (catrin #19211): Empfängerauswahl nach Tags um zwei Varianten erweitert.

* tags_modus "ohne_tags": nur bestätigte Abonnentinnen, deren Tags leer sind (tags darf nicht angegeben sein)
* tags_modus "ausser": alle bestätigten, die KEINEN der gewählten Tags haben (tags Pflicht, 1-20)
* bestehend: "oder" (Standard) und "und"; Prüfung/Normalisierung wie bisher; UND mit rollen/interessen; Vorschau, Entwurf, Freigabe und Versand benutzen dieselbe Auswahl.
Nur erfundene Adressen."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import newsletter
from test_meilenstein_b import Basis


class Basis070(Basis):
    def tags_setzen(self, m, adresse, tags):
        z = self.zeile(m["id"], adresse)
        with db.verbindung() as c:
            c.execute("UPDATE abonnent SET tags=? WHERE id=?", (json.dumps(tags, ensure_ascii=False), z["id"]))

    def vorbereiten(self):
        m = self.mandant("hilo")
        for adresse, rolle, tags in (("a@beispiel.de", "verein", ["Spender"]), ("b@beispiel.de", "verein", ["Spender", "Verein A"]), ("c@beispiel.de", "beratungsstelle", ["Verein A"]),
                                     ("d@beispiel.de", "verein", []), ("e@beispiel.de", "beratungsstelle", ["SPENDER"]), ("f@beispiel.de", "verein", ["Verein A", "Spender", "Neu"]),
                                     ("g@beispiel.de", "beratungsstelle", [])):
            self.abo(m, adresse, rolle=rolle)
            self.tags_setzen(m, adresse, tags)
        return m

    def adressen(self, m, **segment):
        z = {"ziel": "abonnenten", "segment": json.dumps(newsletter._segment_pruefen(m, segment))}
        return sorted(a for _, _, a in newsletter._empfaenger_ermitteln(m, z))

    def fehler(self, m, **segment):
        with self.assertRaises(newsletter.Fehler) as ctx:
            newsletter._segment_pruefen(m, segment)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("segment_ungueltig", 400))


def norm(**segment):
    """So sieht ein geprüftes Segment aus: nicht gesetzte Felder stehen als None darin."""
    return {"rollen": None, "interessen": None, **segment}


def kurz(adressen):
    return [a.split("@")[0] for a in adressen]


class TestOhneTags(Basis070):
    def test_nur_wer_keinen_tag_hat(self):
        m = self.vorbereiten()
        self.assertEqual(kurz(self.adressen(m, tags_modus="ohne_tags")), ["d", "g"])

    def test_normalisiertes_segment_hat_nur_den_modus(self):
        m = self.vorbereiten()
        self.assertEqual(newsletter._segment_pruefen(m, {"tags_modus": "ohne_tags"}), norm(tags_modus="ohne_tags"))

    def test_tags_zusammen_mit_ohne_tags_ist_ein_fehler(self):
        m = self.vorbereiten()
        self.fehler(m, tags_modus="ohne_tags", tags=["Spender"])
        self.fehler(m, tags_modus="ohne_tags", tags=[])

    def test_kombinierbar_mit_rolle_und_interessen(self):
        m = self.vorbereiten()
        self.assertEqual(kurz(self.adressen(m, tags_modus="ohne_tags", rollen=["verein"])), ["d"])
        self.assertEqual(kurz(self.adressen(m, tags_modus="ohne_tags", rollen=["beratungsstelle"])), ["g"])

    def test_nur_bestaetigte_nicht_abgemeldete_nicht_unzustellbare(self):
        m = self.vorbereiten()
        self.abo(m, "h@beispiel.de", status="unbestaetigt")
        self.abo(m, "i@beispiel.de", status="unzustellbar")
        self.abo(m, "j@beispiel.de", status="abgemeldet")
        self.assertEqual(kurz(self.adressen(m, tags_modus="ohne_tags")), ["d", "g"])


class TestAusser(Basis070):
    def test_alle_ausser_mit_dem_tag(self):
        m = self.vorbereiten()
        self.assertEqual(kurz(self.adressen(m, tags=["Spender"], tags_modus="ausser")), ["c", "d", "g"])
        self.assertEqual(kurz(self.adressen(m, tags=["Neu"], tags_modus="ausser")), ["a", "b", "c", "d", "e", "g"])

    def test_mehrere_tags_ausschluss_bei_jedem_davon(self):
        m = self.vorbereiten()
        self.assertEqual(kurz(self.adressen(m, tags=["Spender", "Verein A"], tags_modus="ausser")), ["d", "g"])

    def test_gross_klein_egal_und_normalisiert(self):
        m = self.vorbereiten()
        self.assertEqual(kurz(self.adressen(m, tags=["spender"], tags_modus="ausser")), ["c", "d", "g"])
        self.assertEqual(newsletter._segment_pruefen(m, {"tags": ["  spender "], "tags_modus": "ausser"}), norm(tags=["Spender"], tags_modus="ausser"))

    def test_kombinierbar_mit_rolle(self):
        m = self.vorbereiten()
        self.assertEqual(kurz(self.adressen(m, tags=["Spender"], tags_modus="ausser", rollen=["beratungsstelle"])), ["c", "g"])
        self.assertEqual(kurz(self.adressen(m, tags=["Spender"], tags_modus="ausser", rollen=["verein"])), ["d"])

    def test_nur_bestaetigte(self):
        m = self.vorbereiten()
        self.abo(m, "h@beispiel.de", status="unbestaetigt")
        self.abo(m, "j@beispiel.de", status="abgemeldet")
        self.assertEqual(kurz(self.adressen(m, tags=["Neu"], tags_modus="ausser")), ["a", "b", "c", "d", "e", "g"])

    def test_pflicht_tags_und_gueltigkeit(self):
        m = self.vorbereiten()
        self.fehler(m, tags_modus="ausser")                                           # ohne tags
        self.fehler(m, tags=[], tags_modus="ausser")                                  # leer
        self.fehler(m, tags=["Gibt es nicht"], tags_modus="ausser")                   # unbekannter Tag
        self.fehler(m, tags=["Spender"] * 21, tags_modus="ausser")                    # mehr als 20
        self.fehler(m, tags=[5], tags_modus="ausser")                                 # kein Text

    def test_unbekannter_modus_ist_ein_fehler(self):
        m = self.vorbereiten()
        self.fehler(m, tags=["Spender"], tags_modus="nicht")
        self.fehler(m, tags_modus="nicht")

    def test_tags_anderer_mandanten_zaehlen_nicht(self):
        m = self.vorbereiten()
        andere = self.mandant("andere", "Andere")
        self.abo(andere, "x@beispiel.de")
        self.tags_setzen(andere, "x@beispiel.de", ["Fremd"])
        self.fehler(m, tags=["Fremd"], tags_modus="ausser")
        self.assertEqual(kurz(self.adressen(andere, tags=["Fremd"], tags_modus="ausser")), [])


class TestBestehendesBleibt(Basis070):
    def test_oder_und_standard_unveraendert(self):
        m = self.vorbereiten()
        self.assertEqual(kurz(self.adressen(m, tags=["Spender"])), ["a", "b", "e", "f"])
        self.assertEqual(kurz(self.adressen(m, tags=["Spender", "Verein A"], tags_modus="oder")), ["a", "b", "c", "e", "f"])
        self.assertEqual(kurz(self.adressen(m, tags=["Spender", "Verein A"], tags_modus="und")), ["b", "f"])

    def test_tags_modus_oder_und_ohne_tags_bleiben_fehler(self):
        m = self.vorbereiten()
        self.fehler(m, tags_modus="oder")
        self.fehler(m, tags_modus="und")

    def test_ohne_segment_alle_bestaetigten(self):
        m = self.vorbereiten()
        self.assertEqual(len(self.adressen(m)), 7)


class TestEntwurfFreigabeVersand(Basis070):
    def test_segment_bindet_den_hash_der_freigabe(self):
        m = self.vorbereiten()
        hashes = {}
        for name, seg in (("ausser", {"tags": ["Spender"], "tags_modus": "ausser"}), ("oder", {"tags": ["Spender"], "tags_modus": "oder"}), ("ohne", {"tags_modus": "ohne_tags"})):
            e = newsletter.anlegen(m, "Betreff " + name, "Text", "abonnenten", seg)
            hashes[name] = newsletter.lesen(m, e["id"])
        zwei = newsletter.anlegen(m, "Gleich", "Text", "abonnenten", {"tags": ["Spender"], "tags_modus": "ausser"})["content_hash"]
        drei = newsletter.anlegen(m, "Gleich", "Text", "abonnenten", {"tags": ["Spender"], "tags_modus": "oder"})["content_hash"]
        self.assertNotEqual(zwei, drei)                                                # gleicher Inhalt, anderes Segment = anderer Stand
        self.assertEqual(hashes["ausser"]["segment"], norm(tags=["Spender"], tags_modus="ausser"))
        self.assertEqual(hashes["ohne"]["segment"], norm(tags_modus="ohne_tags"))

    def test_aenderung_des_segments_macht_die_testmail_ungueltig(self):
        m = self.vorbereiten()
        newsletter.testliste_setzen(m, ["t@beispiel.de"])
        e = newsletter.anlegen(m, "Betreff", "Text", "abonnenten", {"tags": ["Spender"], "tags_modus": "oder"})
        newsletter.testmail(m, e["id"])
        self.assertTrue(newsletter.lesen(m, e["id"])["testmail"]["passender_stand"])
        newsletter.aendern(m, e["id"], None, None, None, {"tags": ["Spender"], "tags_modus": "ausser"})
        self.assertFalse(newsletter.lesen(m, e["id"])["testmail"]["passender_stand"])

    def test_vorschau_freigabe_und_versand_nutzen_dieselbe_auswahl(self):
        m = self.vorbereiten()
        eid = self.freigegeben(m, "abonnenten", segment={"tags": ["Spender"], "tags_modus": "ausser"})
        self.assertEqual(newsletter.vorschau(m, eid)["anzahl"], 3)
        self.assertEqual(newsletter.segment_anzahl(m, {"tags": ["Spender"], "tags_modus": "ausser"})["anzahl"], 3)
        newsletter.lauf()
        self.assertEqual(kurz(self.an_adressen("hilo")), ["c", "d", "g"])

    def test_ohne_tags_wird_versendet_an_die_ohne_tag(self):
        m = self.vorbereiten()
        self.freigegeben(m, "abonnenten", segment={"tags_modus": "ohne_tags"})
        newsletter.lauf()
        self.assertEqual(kurz(self.an_adressen("hilo")), ["d", "g"])

    def test_empfaengerliste_wird_bei_der_freigabe_festgeschrieben(self):
        m = self.vorbereiten()
        eid = self.freigegeben(m, "abonnenten", segment={"tags_modus": "ohne_tags"})
        self.abo(m, "neu@beispiel.de")                                                  # nach der Freigabe dazugekommen, ohne Tag
        newsletter.lauf()
        self.assertEqual(kurz(self.an_adressen("hilo")), ["d", "g"])
        self.assertEqual(len(self.zeilen(eid)), 2)


class TestSchnittstelle(Basis070):
    def test_vorschau_per_api(self):
        from unittest import mock
        import betreiber_auth
        m = self.vorbereiten()
        with mock.patch.object(betreiber_auth, "_bei_sortnext_fragen", return_value={"email": "catrin@bst-next.de", "betreiber": True}):
            betreiber_auth.cache_leeren()
            self.c.set_cookie("bst_session", "tok")
            pfad = "/api/v1/betreiber/mandanten/%d/abonnenten/vorschau" % m["id"]
            r = self.c.post(pfad, json={"segment": {"tags_modus": "ohne_tags"}})
            self.assertEqual((r.status_code, r.get_json()["anzahl"], r.get_json()["segment"]), (200, 2, norm(tags_modus="ohne_tags")))
            r = self.c.post(pfad, json={"segment": {"tags": ["spender"], "tags_modus": "ausser"}})
            self.assertEqual((r.status_code, r.get_json()["anzahl"]), (200, 3))
            r = self.c.post(pfad, json={"segment": {"tags": ["Spender"], "tags_modus": "ohne_tags"}})
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, "segment_ungueltig"))
            r = self.c.post(pfad, json={"segment": {"tags_modus": "ausser"}})
            self.assertEqual((r.status_code, r.get_json()["error"]), (400, "segment_ungueltig"))
            self.assertNotIn("@", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
