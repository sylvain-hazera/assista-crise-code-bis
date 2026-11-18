"""Le plan communal de sauvegarde copié sur le satellite (18/11/2026).

Question de Sylvain : « les fiches se copient sur les satellites ? » — elles ne l'étaient pas.
Pendant une coupure, c'est pourtant le plan qu'on veut sous la main."""
import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from core.models import (
    DossierPCS, FonctionPCS, Institution, InstitutionType, InterlocuteurAlertePCS, MoyenAlertePCS,
    PieceJointePCS, Satellite, StatutEnrolementSatellite,
)
from core.sync_referentiel import appliquer_referentiel, referentiel_pour_satellite


@pytest.fixture
def plan(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie du plan", type=itype, commune_code="42186")
    voisine = Institution.objects.create(nom="Mairie voisine", type=itype, commune_code="42207")
    dossier = DossierPCS.objects.create(institution=mairie, environment="PROD", lieu_pcc="Salle du conseil")
    fonction = FonctionPCS.objects.create(dossier=dossier, environment="PROD", fonction="SOUTIEN", consignes="Ouvrir le gymnase.")
    moyen = MoyenAlertePCS.objects.create(dossier=dossier, environment="PROD", type="SIRENE", personne="Paul Garde",
                                          consignes="Trois cycles.")
    interlocuteur = InterlocuteurAlertePCS.objects.create(nom="Préfecture", categorie="PREFECTURE", mode_alerte="TELEPHONE")
    interlocuteur.institutions.add(mairie)
    ailleurs = DossierPCS.objects.create(institution=voisine, environment="PROD")
    FonctionPCS.objects.create(dossier=ailleurs, environment="PROD", fonction="DOS", consignes="Secret de la voisine.")
    return {"mairie": mairie, "dossier": dossier, "fonction": fonction, "moyen": moyen, "interlocuteur": interlocuteur}


@pytest.mark.django_db
class TestCopieDuPlan:

    def test_le_plan_de_l_institution_part_et_celui_des_autres_non(self, plan):
        ref = referentiel_pour_satellite(plan["mairie"], "PROD")
        assert [f["consignes"] for f in ref["fonctions_pcs"]] == ["Ouvrir le gymnase."]
        assert [m["consignes"] for m in ref["moyens_alerte_pcs"]] == ["Trois cycles."]
        assert [i["id"] for i in ref["interlocuteurs_pcs"]] == [str(plan["interlocuteur"].id)]
        assert len(ref["dossier_pcs"]) == 1

    def test_le_satellite_retrouve_son_plan_apres_une_copie(self, plan):
        ref = referentiel_pour_satellite(plan["mairie"], "PROD")
        # Le satellite part de rien (sauf son institution, copiée avec les comptes).
        for modele in (FonctionPCS, MoyenAlertePCS, InterlocuteurAlertePCS, DossierPCS):
            modele.objects.all().delete()
        resultat = appliquer_referentiel(ref)
        assert resultat["erreur"] == 0
        assert FonctionPCS.objects.get().consignes == "Ouvrir le gymnase."
        assert MoyenAlertePCS.objects.get().personne == "Paul Garde"
        assert list(InterlocuteurAlertePCS.objects.get().institutions.all()) == [plan["mairie"]]

    def test_un_dossier_deja_cree_sur_le_satellite_recoit_le_plan_du_central(self, plan):
        """Le satellite avait ouvert son propre dossier, sous un autre identifiant : les fonctions
        du central s'y rattachent au lieu d'être perdues."""
        ref = referentiel_pour_satellite(plan["mairie"], "PROD")
        FonctionPCS.objects.all().delete(); MoyenAlertePCS.objects.all().delete(); DossierPCS.objects.all().delete()
        local = DossierPCS.objects.create(institution=plan["mairie"], environment="PROD")
        appliquer_referentiel(ref)
        assert DossierPCS.objects.count() == 1
        assert FonctionPCS.objects.get().dossier_id == local.id and MoyenAlertePCS.objects.get().dossier_id == local.id


@pytest.mark.django_db
class TestFichiersJoints:

    @pytest.fixture
    def satellite(self, plan, create_user):
        compte = create_user(username="sat-plan@service.assista-crise.local", email="sat-plan@service.assista-crise.local",
                             type="UTIL_SIMPLE", institution=plan["mairie"])
        return Satellite.objects.create(institution=plan["mairie"], nom="Sat plan", profil="FULL",
                                        statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte)

    def _piece(self, dossier):
        piece = PieceJointePCS(dossier=dossier, environment="PROD", titre="Plan du gymnase", nom_fichier="plan.pdf", taille=20)
        piece.fichier.save("plan.pdf", ContentFile(b"%PDF-1.4 plan du gymnase"), save=True)
        return piece

    def test_le_satellite_recupere_le_fichier_d_une_piece_de_son_institution(self, plan, satellite):
        piece = self._piece(plan["dossier"])
        client = APIClient()
        client.force_authenticate(user=satellite.compte_service)
        reponse = client.get(f"/api/satellites/{satellite.id}/piece-plan/{piece.id}/")
        assert reponse.status_code == 200 and b"".join(reponse.streaming_content) == b"%PDF-1.4 plan du gymnase"

    def test_ni_une_piece_d_une_autre_institution_ni_un_autre_compte(self, plan, satellite, create_user):
        voisine = DossierPCS.objects.exclude(institution=plan["mairie"]).get()
        piece_voisine = self._piece(voisine)
        client = APIClient()
        client.force_authenticate(user=satellite.compte_service)
        assert client.get(f"/api/satellites/{satellite.id}/piece-plan/{piece_voisine.id}/").status_code == 404
        intrus = APIClient()
        intrus.force_authenticate(user=create_user(username="intrus@plan.fr", email="intrus@plan.fr", type="AUT_LOCALE"))
        piece = self._piece(plan["dossier"])
        assert intrus.get(f"/api/satellites/{satellite.id}/piece-plan/{piece.id}/").status_code in (403, 404)
