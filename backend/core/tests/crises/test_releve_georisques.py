"""Un seul relevé Géorisques par commune, qui nourrit toutes les pages (18/11/2026).

Les réponses simulées reprennent la FORME réelle de chaque point d'accès, relevée à la main sur
une commune le 18/11/2026 : aucune requête ne part pendant les essais."""
import pytest
from rest_framework.test import APIClient

from core import plans_prevention, releve_georisques, zonages_officiels
from core.models import Commune, ContactInstitution, Institution, InstitutionType, ReleveGeorisques

REPONSES = {
    "gaspar/risques": [{"code_insee": "42186", "risques_detail": [
        {"num_risque": "11", "libelle_risque_long": "Inondation"}, {"num_risque": "12", "libelle_risque_long": "Mouvement de terrain"}]}],
    "gaspar/catnat": [
        {"code_national_catnat": "INTE0300740A", "date_debut_evt": "01/12/2003", "date_fin_evt": "02/12/2003",
         "date_publication_arrete": "12/12/2003", "libelle_risque_jo": "Inondations et/ou Coulées de Boue"},
        {"code_national_catnat": "INTE2121339A", "date_debut_evt": "10/05/2021", "date_fin_evt": "11/05/2021",
         "date_publication_arrete": "30/06/2021", "libelle_risque_jo": "Inondations et/ou Coulées de Boue"}],
    "gaspar/azi": [{"libelle_azi": "Atlas des zone inondables du Gier"}],
    "gaspar/tri": [{"libelle_tri": "Saint-Etienne", "liste_libelle_risque": [{"num_risque": "11", "libelle_risque_long": "Inondation"}]}],
    "mvt": [{"type": "Glissement", "date_debut": "2015-01-01", "commentaire_lieu": "ancien front de carrière"}],
    "cavites": [],
    "radon": [{"classe_potentiel": "3", "code_insee": "42186"}],
    "zonage_sismique": [{"code_zone": "2", "zone_sismicite": "2 - FAIBLE"}],
}


@pytest.fixture
def sans_reseau(monkeypatch):
    """Ni attente ni requête : on compte seulement ce qui aurait été demandé."""
    appels = []
    monkeypatch.setattr(releve_georisques, "_attendre_son_tour", lambda: None)
    monkeypatch.setattr(zonages_officiels, "relever", lambda *a, **k: appels.append("zonages") or {"relevees": [], "ignorees": [], "erreurs": {}})
    monkeypatch.setattr(plans_prevention, "relever", lambda *a, **k: appels.append("plans") or {"relevees": [], "ignorees": [], "erreurs": {}})
    from core import geoportail_urbanisme
    monkeypatch.setattr(geoportail_urbanisme, "relever", lambda *a, **k: appels.append("perimetres") or {"releves": 0, "erreurs": {}})
    monkeypatch.setattr(geoportail_urbanisme, "contour_de_la_commune", lambda code: None)

    def interroger(chemin, commune_code):
        appels.append(chemin)
        return REPONSES[chemin]
    return appels, interroger


@pytest.mark.django_db
class TestUnSeulReleve:

    def test_un_geste_releve_tout_et_nourrit_la_page_des_risques(self, sans_reseau):
        appels, interroger = sans_reseau
        bilan = releve_georisques.relever_tout("42186", "PROD", interroger=interroger)
        assert sorted(bilan["relevees"]) == sorted(releve_georisques.RUBRIQUES) and not bilan["erreurs"]
        # Les zones inondables et les plans de prévention partent dans le même geste.
        assert appels.count("zonages") == 1 and appels.count("plans") == 1
        # ... et le périmètre et l'acte des plans, qui sont au Géoportail de l'urbanisme.
        assert appels.count("perimetres") == 1
        # La page « Risques de la commune » lit ce que CE relevé a rapporté : plus de second appel.
        assert [r["libelle_risque_long"] for r in Commune.objects.get(code="42186").risques_territoire] == ["Inondation", "Mouvement de terrain"]

    def test_un_releve_recent_n_est_pas_refait(self, sans_reseau):
        appels, interroger = sans_reseau
        releve_georisques.relever_tout("42186", "PROD", interroger=interroger)
        avant = len([a for a in appels if "/" in a or a in ("mvt", "cavites", "radon", "zonage_sismique")])
        bilan = releve_georisques.relever_tout("42186", "PROD", interroger=interroger)
        assert sorted(bilan["ignorees"]) == sorted(releve_georisques.RUBRIQUES)
        assert len([a for a in appels if "/" in a or a in ("mvt", "cavites", "radon", "zonage_sismique")]) == avant
        # ... sauf si on le demande.
        assert sorted(releve_georisques.relever_tout("42186", "PROD", forcer=True, interroger=interroger)["relevees"]) == sorted(releve_georisques.RUBRIQUES)

    def test_une_rubrique_en_panne_garde_ce_qu_on_avait(self, sans_reseau):
        _, interroger = sans_reseau
        releve_georisques.relever_tout("42186", "PROD", interroger=interroger)

        def en_panne(chemin, commune_code):
            if chemin == "gaspar/catnat":
                raise OSError("Géorisques ne répond pas")
            return interroger(chemin, commune_code)
        bilan = releve_georisques.relever_tout("42186", "PROD", forcer=True, interroger=en_panne)
        assert list(bilan["erreurs"]) == ["catnat"]
        assert len(ReleveGeorisques.objects.get(commune_code="42186", rubrique="catnat").donnees) == 2

    def test_l_ecran_lit_la_copie_mise_en_forme(self, sans_reseau):
        _, interroger = sans_reseau
        releve_georisques.relever_tout("42186", "PROD", interroger=interroger)
        etat = releve_georisques.etat("42186", "PROD")
        assert (etat["releve"], etat["complet"], etat["sismicite"], etat["radon"], etat["cavites"]) == (True, True, "2 - FAIBLE", "significatif", 0)
        assert etat["catnat"]["nombre"] == 2 and etat["catnat"]["derniers"][0]["debut"] == "10/05/2021"      # le plus récent d'abord
        assert etat["azi"] == ["Atlas des zone inondables du Gier"] and etat["tri"][0]["nom"] == "Saint-Etienne"
        assert etat["mouvements"][0]["type"] == "Glissement"

    def test_sans_releve_l_ecran_le_dit(self, db):
        etat = releve_georisques.etat("42186", "PROD")
        assert etat["releve"] is False and etat["catnat"]["nombre"] == 0 and etat["sismicite"] == ""


@pytest.mark.django_db
class TestParLApi:

    @pytest.fixture
    def mairie(self, create_user):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(nom="Mairie du relevé", type=itype, commune_code="42186")
        agent = create_user(username="agent@geo.fr", email="agent@geo.fr", type="AUT_LOCALE")
        agent.institution = institution
        agent.save()
        ContactInstitution.objects.create(institution=institution, utilisateur=agent, actif=True)
        client = APIClient()
        client.force_authenticate(user=agent)
        return client

    def test_la_lecture_ne_fait_aucun_appel_exterieur(self, mairie, monkeypatch):
        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("aucun appel attendu")))
        reponse = mairie.get("/api/dossier-pcs/georisques/")
        assert reponse.status_code == 200 and reponse.data["releve"] is False and len(reponse.data["rubriques"]) == len(releve_georisques.RUBRIQUES)

    def test_demander_le_releve_lance_la_tache_unique(self, mairie, monkeypatch):
        from core import tasks
        demandes = []
        monkeypatch.setattr(tasks.relever_zonages_officiels_task, "delay", lambda *a: demandes.append(a))
        assert mairie.post("/api/dossier-pcs/georisques/", {}, format="json").status_code == 202
        assert demandes == [("42186", "PROD", False)]

    def test_le_rapport_est_demande_par_le_serveur_et_rendu_en_pdf(self, mairie, monkeypatch):
        monkeypatch.setattr(releve_georisques, "rapport_pdf", lambda code: b"%PDF-1.7 rapport " + code.encode())
        reponse = mairie.get("/api/dossier-pcs/georisques/rapport/")
        assert reponse.status_code == 200 and reponse["Content-Type"] == "application/pdf" and reponse.content.startswith(b"%PDF-")

    def test_un_particulier_n_y_a_pas_acces(self, create_user):
        client = APIClient()
        client.force_authenticate(user=create_user(username="p@geo.fr", email="p@geo.fr", type="UTIL_SIMPLE"))
        assert client.get("/api/dossier-pcs/georisques/").status_code == 403
