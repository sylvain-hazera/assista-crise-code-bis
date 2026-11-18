"""Qui prévenir, et à quel moment (18/11/2026).

Demande de Sylvain : sur l'annuaire, « prévenir à l'ouverture de la crise », « prévenir à
l'ouverture d'un centre d'accueil ». Et sa décision : « préparation de la liste et clic pour
confirmer » — rien ne part tout seul."""
from core.tests.outils_chiffre import filtrer_chiffre
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.alertes_pcs import preparer_checklist_centre, preparer_checklist_pcs
from core.models import (
    ContactInstitution, Crisis, Institution, InstitutionType, InterlocuteurAlertePCS, NotificationAlertePCS,
    PointOperationnel, PointType, StatutNotificationPCS,
)


@pytest.fixture
def mairie(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(nom="Mairie de la prévenance", type=itype, commune_code="42186")
    agent = create_user(username="agent@prev.fr", email="agent@prev.fr", type="AUT_LOCALE")
    agent.institution = institution
    agent.save()
    ContactInstitution.objects.create(institution=institution, utilisateur=agent, actif=True)
    client = APIClient()
    client.force_authenticate(user=agent)
    return institution, client


def _interlocuteur(mairie, nom, crise=True, centre=False):
    fiche = InterlocuteurAlertePCS.objects.create(nom=nom, categorie="PREFECTURE", mode_alerte="TELEPHONE",
                                                  prevenir_ouverture_crise=crise, prevenir_ouverture_centre=centre)
    fiche.institutions.add(mairie)
    return fiche


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name="Crue du Gier", type="INONDATION", location=Point(4.6, 45.5, srid=4326))


@pytest.mark.django_db
class TestOuvertureDeLaCrise:

    def test_tous_sont_dans_la_liste_seuls_ceux_a_prevenir_sont_coches(self, mairie, crise):
        _interlocuteur(mairie[0], "Préfecture")
        _interlocuteur(mairie[0], "Association du quartier", crise=False)
        preparer_checklist_pcs(crise, mairie[0])
        lignes = {n.nom_snapshot: n for n in NotificationAlertePCS.objects.filter(crise=crise)}
        assert (lignes["Préfecture"].preselectionne, lignes["Association du quartier"].preselectionne) == (True, False)
        # Rien n'est parti : la liste attend le clic de quelqu'un.
        assert {n.statut for n in lignes.values()} == {StatutNotificationPCS.EN_ATTENTE}
        assert {n.motif for n in lignes.values()} == {"CRISE"}


@pytest.mark.django_db
class TestOuvertureDUnCentreDAccueil:

    def _ouvrir(self, client, crise, code="HEBERGEMENT", nom="Gymnase municipal"):
        ptype, _ = PointType.objects.get_or_create(code=code, defaults={"libelle": code.title(), "actif": True})
        return client.post("/api/points-operationnels/", {"nom": nom, "type": str(ptype.id), "crise": str(crise.id)}, format="json")

    def test_ouvrir_un_centre_prepare_la_liste_de_ceux_a_prevenir_a_ce_moment(self, mairie, crise):
        _interlocuteur(mairie[0], "Croix-Rouge locale", centre=True)
        _interlocuteur(mairie[0], "Préfecture")                       # à l'ouverture de la crise seulement
        reponse = self._ouvrir(mairie[1], crise)
        assert reponse.status_code == 201, reponse.data
        (ligne,) = filtrer_chiffre(NotificationAlertePCS.objects.filter(), motif="CENTRE")
        assert (ligne.nom_snapshot, ligne.point_nom_snapshot, ligne.preselectionne) == ("Croix-Rouge locale", "Gymnase municipal", True)
        assert ligne.statut == StatutNotificationPCS.EN_ATTENTE       # préparée, pas envoyée

    def test_un_point_qui_n_est_pas_un_centre_d_accueil_ne_prepare_rien(self, mairie, crise):
        _interlocuteur(mairie[0], "Croix-Rouge locale", centre=True)
        assert self._ouvrir(mairie[1], crise, code="CARBURANT", nom="Station").status_code == 201
        assert not filtrer_chiffre(NotificationAlertePCS.objects.filter(), motif="CENTRE").exists()

    def test_la_meme_ouverture_ne_prepare_pas_deux_fois_la_meme_ligne(self, mairie, crise):
        _interlocuteur(mairie[0], "Croix-Rouge locale", centre=True)
        self._ouvrir(mairie[1], crise)
        point = PointOperationnel.objects.get()
        assert preparer_checklist_centre(point, mairie[0]) == 0
        assert filtrer_chiffre(NotificationAlertePCS.objects.filter(), motif="CENTRE").count() == 1

    def test_la_liste_dit_pourquoi_chaque_ligne_est_la(self, mairie, crise):
        _interlocuteur(mairie[0], "Croix-Rouge locale", centre=True)
        preparer_checklist_pcs(crise, mairie[0])
        self._ouvrir(mairie[1], crise)
        lignes = mairie[1].get(f"/api/notifications-alerte-pcs/?crise={crise.id}").data
        lignes = lignes["results"] if isinstance(lignes, dict) else lignes
        assert sorted((l["motif"], l["point_nom_snapshot"]) for l in lignes) == [("CENTRE", "Gymnase municipal"), ("CRISE", "")]
