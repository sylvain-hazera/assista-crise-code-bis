"""Les services d'adresses de l'État, en un seul endroit (core/adresses.py, 18/11/2026)."""
import pathlib
import re

from core import adresses

CORE = pathlib.Path(adresses.__file__).parent


def test_tout_le_geocodage_passe_par_la_geoplateforme():
    assert adresses.url_recherche("3 rue Haute, Saint-Exemple") == \
        "https://data.geopf.fr/geocodage/search?q=3+rue+Haute%2C+Saint-Exemple&limit=1"
    assert adresses.url_inverse(4.617, 45.529) == "https://data.geopf.fr/geocodage/reverse?lon=4.617&lat=45.529&limit=1"
    assert adresses.url_ban("42186") == "https://plateforme.adresse.data.gouv.fr/lookup/42186"


def test_aucun_autre_module_n_ecrit_l_adresse_d_un_service_d_adresses():
    """C'est ce qui avait dérivé : trois services, cinq modules, chacun son adresse en dur."""
    fautifs = []
    for fichier in CORE.glob("*.py"):
        if fichier.name == "adresses.py":
            continue
        code = "\\n".join(ligne.split("#", 1)[0] for ligne in fichier.read_text(encoding="utf-8").splitlines())
        code = re.sub(r'"""(?s:.*?)"""', "", code)         # les explications ont le droit de les nommer
        if re.search(r"api-adresse\\.data\\.gouv\\.fr|plateforme\\.adresse\\.data\\.gouv\\.fr|data\\.geopf\\.fr/geocodage", code):
            fautifs.append(fichier.name)
    assert fautifs == []


def test_la_reponse_se_lit_de_la_meme_facon_partout():
    # Forme réelle de la réponse, relevée le 18/11/2026.
    reponse = {"type": "FeatureCollection", "features": [{"type": "Feature",
               "geometry": {"type": "Point", "coordinates": [4.616673, 45.529107]},
               "properties": {"label": "32 Rue du Canal 42800 Rive-de-Gier", "citycode": "42186", "city": "Rive-de-Gier"}}]}
    assert adresses.premiere_adresse(reponse) == {
        "latitude": 45.529107, "longitude": 4.616673, "citycode": "42186", "commune": "Rive-de-Gier",
        "libelle": "32 Rue du Canal 42800 Rive-de-Gier"}
    assert adresses.premiere_adresse({"features": []}) is None and adresses.premiere_adresse(None) is None
    assert adresses.premiere_adresse({"features": [{"geometry": None}]}) is None
