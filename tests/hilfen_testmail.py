"""Hilfe für Tests, die nur einen getesteten Entwurf brauchen (seit v0.6.3 geht jede Testmail an die Testliste des Mandanten)."""
import newsletter

STANDARD_TESTADRESSE = "testliste@beispiel.de"


def testmail_liste(mandant, entwurf_id):
    """Testmail an die Testliste; ist sie leer, wird eine Standardadresse eingetragen."""
    if not newsletter.testliste(mandant):
        newsletter.testliste_setzen(mandant, [STANDARD_TESTADRESSE])
    return newsletter.testmail(mandant, entwurf_id)
