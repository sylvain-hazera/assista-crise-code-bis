"""Suivi du relogement des familles sinistrées, et le bilan qu'on en tire.

Demande de Sylvain du 12/11/2026 : « il me faudra une page, suivi hébergement des familles
nécessitant un relogement [...] À terme, on devra pouvoir éditer des rapports à différents
moments de la crise et pouvoir dire, par exemple, tant de familles relogées, tant de manières
pérennes. »

Ce que ces tests tiennent, dans l'ordre d'importance :

1. **« Hébergée » n'est pas « relogée ».** Un foyer à l'hôtel depuis trois semaines n'est pas
   relogé : l'annoncer comme tel ferait écrire un bilan faux à une préfecture. Seule une
   solution `DEFINITIVE` compte comme pérenne.
2. **Le parcours n'est jamais écrasé.** Gymnase, puis hôtel, puis logement communal : chaque
   étape est une ligne. C'est l'historique que le rapport demande, et une mise à jour en
   place le détruirait.
3. **Deux hébergements ouverts en même temps pour un même foyer sont impossibles** — sinon la
   synthèse compte deux fois la même famille et personne ne sait où elle dort.
4. **Un foyer sans solution est le chiffre qui doit remonter en premier** : ce sont des gens
   qui dorment on ne sait où ce soir.
5. **Un terme dépassé sans sortie enregistrée est le cas le plus urgent** : personne ne sait
   où en est cette famille.
6. **Une famille n'est pas une personne** : « 12 familles » et « 31 personnes » sont deux
   réponses à deux questions, et le rapport veut les deux.
7. **Ces fiches ne sont pas lisibles par n'importe qui** : ce sont des sinistrés nommés, avec
   l'adresse où ils dorment.
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, Crisis, DossierRelogement, Institution, InstitutionType,
    SolutionRelogement, StatutDossierRelogement, Team, TitreOccupation,
    TypeSolutionRelogement, UserRole,
)


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie de Test", type=itype, actif=True)


@pytest.fixture
def autre_mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Voisine", type=itype, actif=True)


@pytest.fixture
def crise(db):
    return Crisis.objects.create(
        name="Crue de test", type="INONDATION", location="POINT (5.0 45.0)")


def _agent(create_user, institution, nom):
    user = create_user(username=f"{nom.lower()}-relog@test.fr",
                       email=f"{nom.lower()}-relog@test.fr",
                       type=UserRole.LOCAL_AUTHORITY, last_name=nom)
    ContactInstitution.objects.create(
        institution=institution, utilisateur=user, actif=True)
    return user


def _dossier(crise, institution, adultes=2, enfants=1, **kwargs):
    return DossierRelogement.objects.create(
        crise=crise, institution=institution, nom_referent="Famille Durand",
        nombre_adultes=adultes, nombre_enfants=enfants, environment="PROD", **kwargs)


def _solution(dossier, type_solution, titre, debut=None, fin_prevue=None, fin=None):
    return SolutionRelogement.objects.create(
        dossier_relogement=dossier, type_solution=type_solution, titre_occupation=titre,
        date_debut=debut or timezone.localdate(), date_fin_prevue=fin_prevue,
        date_fin_effective=fin, environment="PROD")


def _synthese(utilisateur, crise):
    return _client(utilisateur).get(
        reverse("dossierrelogement-synthese"), {"crise": str(crise.id)})


class TestLeBilanNeConfondPasHebergeEtReloge:
    def test_une_solution_definitive_compte_comme_perenne(
            self, create_user, mairie, crise):
        agent = _agent(create_user, mairie, "AGENT1")
        dossier = _dossier(crise, mairie)
        _solution(dossier, TypeSolutionRelogement.DEFINITIVE, TitreOccupation.BAIL)

        data = _synthese(agent, crise).data

        assert data["relogees_durablement"] == 1
        assert data["par_type_solution_courante"]["DEFINITIVE"] == 1

    def test_un_hotel_ne_compte_pas_comme_reloge(self, create_user, mairie, crise):
        """LE test. Trois semaines à l'hôtel, ce n'est pas un relogement."""
        agent = _agent(create_user, mairie, "AGENT2")
        dossier = _dossier(crise, mairie)
        _solution(dossier, TypeSolutionRelogement.TEMPORAIRE, TitreOccupation.HOTEL)

        data = _synthese(agent, crise).data

        assert data["relogees_durablement"] == 0
        assert data["par_type_solution_courante"]["TEMPORAIRE"] == 1

    def test_les_familles_et_les_personnes_sont_deux_chiffres(
            self, create_user, mairie, crise):
        agent = _agent(create_user, mairie, "AGENT3")
        _dossier(crise, mairie, adultes=2, enfants=3)
        _dossier(crise, mairie, adultes=1, enfants=0)

        data = _synthese(agent, crise).data

        assert data["foyers"] == 2
        assert data["personnes"] == 6
        assert data["adultes"] == 3
        assert data["enfants"] == 3

    def test_un_foyer_sans_solution_remonte(self, create_user, mairie, crise):
        """Des gens qui dorment on ne sait où ce soir : c'est le chiffre qui passe devant."""
        agent = _agent(create_user, mairie, "AGENT4")
        _dossier(crise, mairie)

        data = _synthese(agent, crise).data

        assert data["sans_solution"] == 1

    def test_un_dossier_clos_nest_pas_un_foyer_sans_solution(
            self, create_user, mairie, crise):
        """Il est sorti du dispositif, il n'est pas à la rue : les confondre ferait chercher
        une famille qui n'a besoin de rien."""
        agent = _agent(create_user, mairie, "AGENT5")
        _dossier(crise, mairie, statut=StatutDossierRelogement.CLOS_SANS_SUITE)

        assert _synthese(agent, crise).data["sans_solution"] == 0

    def test_un_terme_proche_est_signale(self, create_user, mairie, crise):
        agent = _agent(create_user, mairie, "AGENT6")
        dossier = _dossier(crise, mairie)
        _solution(dossier, TypeSolutionRelogement.INTERMEDIAIRE, TitreOccupation.PRET,
                  fin_prevue=timezone.localdate() + datetime.timedelta(days=10))

        data = _synthese(agent, crise).data

        assert data["arrivent_a_terme"] == 1
        assert data["termes_depasses"] == 0

    def test_un_terme_depasse_est_un_cas_a_part(self, create_user, mairie, crise):
        """Le plus urgent de tous : le prêt est fini et personne n'a enregistré de sortie."""
        agent = _agent(create_user, mairie, "AGENT7")
        dossier = _dossier(crise, mairie)
        _solution(dossier, TypeSolutionRelogement.INTERMEDIAIRE, TitreOccupation.PRET,
                  fin_prevue=timezone.localdate() - datetime.timedelta(days=3))

        data = _synthese(agent, crise).data

        assert data["termes_depasses"] == 1
        assert data["arrivent_a_terme"] == 0

    def test_une_solution_close_ne_loge_plus_personne(self, create_user, mairie, crise):
        """Elle est la plus récente, mais elle est finie : l'afficher comme courante ferait
        croire la famille à l'abri."""
        agent = _agent(create_user, mairie, "AGENT8")
        dossier = _dossier(crise, mairie)
        _solution(dossier, TypeSolutionRelogement.TEMPORAIRE, TitreOccupation.HOTEL,
                  fin=timezone.localdate() - datetime.timedelta(days=1))

        data = _synthese(agent, crise).data

        assert data["sans_solution"] == 1
        assert data["par_type_solution_courante"]["TEMPORAIRE"] == 0


class TestLeParcoursNestJamaisEcrase:
    def test_ajouter_une_solution_clot_la_precedente(self, create_user, mairie, crise):
        agent = _agent(create_user, mairie, "PARCOURS1")
        dossier = _dossier(crise, mairie)
        premiere = _solution(dossier, TypeSolutionRelogement.URGENCE, TitreOccupation.CENTRE,
                             debut=timezone.localdate() - datetime.timedelta(days=10))

        debut = timezone.localdate()
        reponse = _client(agent).post(
            reverse("dossierrelogement-ajouter-solution", args=[str(dossier.id)]),
            {"type_solution": TypeSolutionRelogement.INTERMEDIAIRE,
             "titre_occupation": TitreOccupation.PRET,
             "date_debut": debut.isoformat()},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        premiere.refresh_from_db()
        # La première est close, elle n'est PAS supprimée : le parcours est l'information.
        assert premiere.date_fin_effective == debut
        assert dossier.solutions.count() == 2

    def test_un_seul_hebergement_ouvert_a_la_fois(self, create_user, mairie, crise):
        """Deux lignes ouvertes feraient compter deux fois la même famille."""
        agent = _agent(create_user, mairie, "PARCOURS2")
        dossier = _dossier(crise, mairie)
        _solution(dossier, TypeSolutionRelogement.URGENCE, TitreOccupation.CENTRE)

        _client(agent).post(
            reverse("dossierrelogement-ajouter-solution", args=[str(dossier.id)]),
            {"type_solution": TypeSolutionRelogement.TEMPORAIRE,
             "titre_occupation": TitreOccupation.HOTEL,
             "date_debut": timezone.localdate().isoformat()},
            format="json")

        assert dossier.solutions.filter(date_fin_effective__isnull=True).count() == 1

    def test_le_statut_du_dossier_suit_la_solution(self, create_user, mairie, crise):
        """Le laisser à la main produirait des listes fausses au premier oubli."""
        agent = _agent(create_user, mairie, "PARCOURS3")
        dossier = _dossier(crise, mairie)

        _client(agent).post(
            reverse("dossierrelogement-ajouter-solution", args=[str(dossier.id)]),
            {"type_solution": TypeSolutionRelogement.DEFINITIVE,
             "titre_occupation": TitreOccupation.BAIL,
             "date_debut": timezone.localdate().isoformat()},
            format="json")

        dossier.refresh_from_db()
        assert dossier.statut == StatutDossierRelogement.RELOGEE

    def test_un_retour_au_domicile_se_distingue_dun_relogement(
            self, create_user, mairie, crise):
        """Rentrer chez soi et être relogé ailleurs sont deux issues différentes, et le bilan
        de crise les distingue."""
        agent = _agent(create_user, mairie, "PARCOURS4")
        dossier = _dossier(crise, mairie)

        _client(agent).post(
            reverse("dossierrelogement-ajouter-solution", args=[str(dossier.id)]),
            {"type_solution": TypeSolutionRelogement.DEFINITIVE,
             "titre_occupation": TitreOccupation.RETOUR,
             "date_debut": timezone.localdate().isoformat()},
            format="json")

        dossier.refresh_from_db()
        assert dossier.statut == StatutDossierRelogement.RETOUR_DOMICILE

    def test_clore_sans_remplacer_remet_le_foyer_en_recherche(
            self, create_user, mairie, crise):
        agent = _agent(create_user, mairie, "PARCOURS5")
        dossier = _dossier(crise, mairie, statut=StatutDossierRelogement.HEBERGE)
        _solution(dossier, TypeSolutionRelogement.TEMPORAIRE, TitreOccupation.HOTEL)

        reponse = _client(agent).post(
            reverse("dossierrelogement-cloturer-solution", args=[str(dossier.id)]),
            {"motif_fin": "Fin de prise en charge hôtelière"}, format="json")

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        dossier.refresh_from_db()
        assert dossier.statut == StatutDossierRelogement.EN_RECHERCHE

    def test_clore_sans_hebergement_en_cours_est_une_erreur(
            self, create_user, mairie, crise):
        agent = _agent(create_user, mairie, "PARCOURS6")
        dossier = _dossier(crise, mairie)

        reponse = _client(agent).post(
            reverse("dossierrelogement-cloturer-solution", args=[str(dossier.id)]),
            {}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST


class TestQuiPeutLire:
    def test_une_autre_collectivite_ne_voit_pas_ces_familles(
            self, create_user, mairie, autre_mairie, crise):
        """Des sinistrés nommés, avec l'adresse où ils dorment : le périmètre n'est pas une
        commodité d'affichage."""
        _dossier(crise, mairie)
        voisin = _agent(create_user, autre_mairie, "VOISIN")

        reponse = _client(voisin).get(reverse("dossierrelogement-list"))

        assert reponse.status_code == status.HTTP_200_OK
        assert list(reponse.data) == []

    def test_une_equipe_sur_la_crise_ouvre_la_lecture(
            self, create_user, mairie, autre_mairie, crise):
        """Une association mandatée sur la crise doit pouvoir suivre les familles qu'elle
        accompagne, sans être celle qui a ouvert le dossier."""
        _dossier(crise, mairie)
        equipier = _agent(create_user, autre_mairie, "MANDATEE")
        equipe = Team.objects.create(
            name="Équipe hébergement", institution=autre_mairie, environment="PROD")
        equipe.assigned_crises.add(crise)

        reponse = _client(equipier).get(reverse("dossierrelogement-list"))

        assert len(reponse.data) == 1

    def test_un_citoyen_na_rien_a_faire_ici(self, create_user, mairie, crise):
        _dossier(crise, mairie)
        citoyen = create_user(username="citoyen-relog@test.fr",
                              email="citoyen-relog@test.fr", type=UserRole.SIMPLE_USER)

        reponse = _client(citoyen).get(reverse("dossierrelogement-list"))

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_la_synthese_dune_crise_sans_dossier_accessible_est_refusee(
            self, create_user, mairie, autre_mairie, crise):
        _dossier(crise, mairie)
        voisin = _agent(create_user, autre_mairie, "VOISIN2")

        assert _synthese(voisin, crise).status_code == status.HTTP_404_NOT_FOUND


class TestRienNestStockeEnClair:
    def test_le_nom_du_referent_est_chiffre_en_base(self, create_user, mairie, crise):
        """Vérifié en SQL brut et non par l'ORM : c'est le seul contrôle qui prouve que la
        colonne elle-même ne contient pas la valeur lisible."""
        from django.db import connection

        dossier = _dossier(crise, mairie)
        dossier.nom_referent = "Famille Rossignol"
        dossier.telephone_referent = "0612345678"
        dossier.save()

        with connection.cursor() as curseur:
            curseur.execute(
                "SELECT nom_referent, telephone_referent FROM core_dossierrelogement "
                "WHERE id = %s", [str(dossier.id)])
            nom, telephone = curseur.fetchone()

        assert "Rossignol" not in nom
        assert "0612345678" not in telephone
        # …et restent lisibles par l'application.
        relu = DossierRelogement.objects.get(pk=dossier.pk)
        assert relu.nom_referent == "Famille Rossignol"
