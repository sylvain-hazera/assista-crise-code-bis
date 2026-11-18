"""Fiches réflexes types : celles des fonctions du poste de commandement, et celles des moyens
d'alerte (18/11/2026)."""
from core.tests.outils_chiffre import filtrer_chiffre
import pytest
from rest_framework.test import APIClient

from core import pcs_fiches
from core.models import ContactInstitution, Institution, InstitutionType


@pytest.fixture
def mairie(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(nom="Mairie des fiches", type=itype, commune_code="42186")
    agent = create_user(username="agent@fiches.fr", email="agent@fiches.fr", type="AUT_LOCALE")
    agent.institution = institution
    agent.save()
    ContactInstitution.objects.create(institution=institution, utilisateur=agent, actif=True)
    client = APIClient()
    client.force_authenticate(user=agent)
    return client


def test_chaque_fonction_et_chaque_moyen_a_sa_fiche_type():
    for code in ("DOS", "COORDINATION", "ALERTE", "SOUTIEN", "LOGISTIQUE", "SECRETARIAT"):
        assert pcs_fiches.fiche_type(code).startswith("• ")
    for code in ("SIRENE", "VEHICULE", "AUTOMATE", "RELAIS", "PORTE_A_PORTE", "AFFICHAGE"):
        assert pcs_fiches.fiche_moyen(code).startswith("• ")


def test_les_fiches_parlent_le_vocabulaire_de_l_application():
    """« Mobilisation », pas « réquisition » comme geste de l'application ; et chaque fiche de
    fonction renvoie au moins une fois à un écran."""
    for code, lignes in pcs_fiches.FICHES_TYPES.items():
        if code == "AUTRE":
            continue
        assert any("[" in ligne for ligne in lignes), code
    assert "Demandes de mobilisation" in pcs_fiches.fiche_type("DOS")
    assert "Standard de crise" in pcs_fiches.fiche_type("SECRETARIAT")


@pytest.mark.django_db
class TestServiesParChoix:

    def test_les_fiches_types_se_lisent_avant_de_creer_la_ligne(self, mairie):
        fonctions = mairie.get("/api/pcs-fonctions/fiches-types/").data
        moyens = mairie.get("/api/pcs-moyens-alerte/fiches-types/").data
        assert fonctions["ALERTE"] == pcs_fiches.fiche_type("ALERTE")
        assert moyens["SIRENE"] == pcs_fiches.fiche_moyen("SIRENE")

    def test_la_fiche_du_moyen_sort_au_moment_de_l_alerte(self, mairie):
        mairie.post("/api/pcs-moyens-alerte/", {"type": "SIRENE", "description": "Toit de la mairie"}, format="json")
        mairie.post("/api/pcs-moyens-alerte/", {"type": "PORTE_A_PORTE", "consignes": "Binômes du conseil municipal, rue par rue."}, format="json")
        terrain = {m["type"]: m for m in mairie.get("/api/alertes-population/").data["apercu"]["terrain"]}
        assert terrain["SIRENE"]["consignes"] == pcs_fiches.fiche_moyen("SIRENE") and terrain["SIRENE"]["fiche_propre"] is False
        assert terrain["PORTE_A_PORTE"]["consignes"] == "Binômes du conseil municipal, rue par rue."
        assert terrain["PORTE_A_PORTE"]["fiche_propre"] is True

    def test_la_fiche_du_moyen_entre_au_document_du_plan(self, mairie):
        from core import document_pcs
        from core.models import Institution
        mairie.post("/api/pcs-moyens-alerte/", {"type": "SIRENE"}, format="json")
        contenu = document_pcs.rassembler(Institution.objects.get(nom="Mairie des fiches"), "PROD", lambda u: "")
        (moyen,) = contenu["moyens_alerte"]
        assert moyen["consignes"] == pcs_fiches.fiche_moyen("SIRENE") and moyen["fiche_propre"] is False


class TestBibliotheque:
    """Fiches de conseil reprises de documents publics de l'État, chacune avec sa source."""

    def test_chaque_fiche_cite_sa_source_publique(self):
        from core import fiches_conseil
        assert len(fiches_conseil.FICHES) >= 15
        for fiche in fiches_conseil.FICHES:
            source = fiche["source"]
            if fiche.get("officielle", True) is False:
                # Les astuces de terrain ne prétendent à aucune source officielle, et le disent.
                assert fiche["categorie"] == "ASTUCES" and "non officiel" in source["editeur"], fiche["code"]
                continue
            assert source["url"].startswith("https://www.") and ".gouv.fr/" in source["url"], fiche["code"]
            assert source["editeur"] and source["consulte_le"]
            assert fiche["categorie"] in fiches_conseil.CATEGORIES

    def test_on_y_trouve_les_roles_les_postes_et_le_centre_d_accueil(self):
        from core import fiches_conseil
        codes = set(fiches_conseil.par_code())
        assert {"decisions", "secretariat", "relais-quartier", "accueil-regroupement", "care-fonctions", "evacuation"} <= codes

    def test_la_fiche_en_texte_garde_sa_source(self):
        from core import fiches_conseil
        texte = fiches_conseil.en_texte(fiches_conseil.par_code()["care-preparer"])
        assert "4 m² par personne" in texte and "D'après" in texte and "sécurité civile" in texte


@pytest.mark.django_db
class TestReprendreDansLePlan:

    def test_la_bibliotheque_se_lit(self, mairie):
        donnees = mairie.get("/api/pcs-fiches-conseil/").data
        assert "CENTRE" in donnees["categories"] and len(donnees["fiches"]) >= 15

    def test_reprendre_une_fiche_cree_la_fonction_avec_ce_texte(self, mairie):
        from core.models import FonctionPCS
        reponse = mairie.post("/api/pcs-fiches-conseil/", {"fiche": "accueil-regroupement"}, format="json")
        assert reponse.status_code == 201 and reponse.data["fonction"] == "SOUTIEN"
        assert "Ouvre le centre d'accueil" in filtrer_chiffre(FonctionPCS.objects.filter(), fonction="SOUTIEN").get().consignes

    def test_on_ne_remplace_pas_en_silence_une_fiche_ecrite_par_la_commune(self, mairie):
        from core.models import FonctionPCS
        mairie.post("/api/pcs-fonctions/", {"fonction": "SOUTIEN", "consignes": "Notre fiche à nous."}, format="json")
        reponse = mairie.post("/api/pcs-fiches-conseil/", {"fiche": "accueil-regroupement"}, format="json")
        assert reponse.status_code == 409 and reponse.data["deja_ecrite"] is True
        assert filtrer_chiffre(FonctionPCS.objects.filter(), fonction="SOUTIEN").get().consignes == "Notre fiche à nous."
        assert mairie.post("/api/pcs-fiches-conseil/", {"fiche": "accueil-regroupement", "remplacer": True}, format="json").status_code == 201

    def test_une_fiche_sans_fonction_demande_laquelle(self, mairie):
        reponse = mairie.post("/api/pcs-fiches-conseil/", {"fiche": "evacuation"}, format="json")
        assert reponse.status_code == 400 and "fonction" in reponse.data
        assert mairie.post("/api/pcs-fiches-conseil/", {"fiche": "evacuation", "fonction": "COORDINATION"}, format="json").status_code == 201


def test_les_astuces_de_terrain_sont_a_part_et_dites_non_officielles():
    from core import fiches_conseil
    astuces = [f for f in fiches_conseil.catalogue() if f["categorie"] == "ASTUCES"]
    assert len(astuces) >= 5 and all(f["officielle"] is False for f in astuces)
    assert any("médiathèque" in ligne for f in astuces for s in f["sections"] for ligne in s["lignes"])
    assert all(f["officielle"] is True for f in fiches_conseil.catalogue() if f["categorie"] != "ASTUCES")
    assert len(fiches_conseil.une_astuce_au_hasard(3)) == 3
