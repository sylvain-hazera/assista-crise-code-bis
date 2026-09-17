"""Test minimal d'annoncer_backend_local.py — la boucle d'annonce elle-même (annoncer()) est une
boucle infinie qui parle réellement à zeroconf, vérifiée par smoke test manuel (voir la session
du 2026-09-17 sur meshcore-bridge/proxy.py, même technique) plutôt que par un test automatisé
qui ne testerait qu'un mock."""
import annoncer_backend_local as abl


def test_ip_locale_annoncable_renvoie_une_chaine_ou_none():
    resultat = abl._ip_locale_annoncable()
    assert resultat is None or isinstance(resultat, str)
