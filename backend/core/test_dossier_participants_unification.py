import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationCompetence,
    AffectationRoleOperationnel,
    Besoin,
    BesoinCompetence,
    Competence,
    Crisis,
    Dossier,
    DossierParticipant,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    RequestTypeBesoin,
    RoleOperationnel,
    Team,
)


def _declare_responsable(crisis, create_user):
    """Rend une crise 'surveillée' (Volet 8) : sans ImplicationInstitution.responsable
    actif, le dépôt de demande sur cette crise est désormais rejeté par le serializer."""
    itype = InstitutionType.objects.create(code=f"ITYPE-MONITOR-{crisis.id}", libelle="Mairie")
    institution = Institution.objects.create(nom=f"Institution monitor {crisis.id}", type=itype)
    responsable = create_user(username=f"resp-{crisis.id}@test.fr", email=f"resp-{crisis.id}@test.fr", type="AUT_LOCALE")
    ImplicationInstitution.objects.create(
        crise=crisis, institution=institution, type_implication="IMPLIQUE",
        responsable=responsable, actif=True,
    )
    return responsable


@pytest.fixture
def local_authority_client(create_user):
    user = create_user(username="autorite-unif@test.fr", email="autorite-unif@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _setup_competence_chain(request_type):
    besoin = Besoin.objects.create(nom="Besoin unif test")
    RequestTypeBesoin.objects.create(request_type=request_type, besoin=besoin)
    competence = Competence.objects.create(nom="Competence unif test")
    BesoinCompetence.objects.create(besoin=besoin, competence=competence)
    return competence


def _regulateur(create_user, competence, email="regul-unif@test.fr"):
    regulateur = create_user(username=email, email=email, type="UTIL_SIMPLE")
    role = RoleOperationnel.objects.create(code="REGULATEUR", libelle="Régulateur")
    itype = InstitutionType.objects.create(code=f"ITYPE-{email}", libelle="Mairie")
    institution = Institution.objects.create(nom=f"Institution {email}", type=itype)
    AffectationRoleOperationnel.objects.create(
        utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True,
    )
    return regulateur


@pytest.mark.django_db
class TestAutomaticPathParticipants:

    def test_dossier_linked_to_originating_request(self, request_type, create_user):
        """Le dossier auto-créé doit référencer la demande d'origine (Dossier.demande) —
        jusqu'ici seul le chemin manuel (assign_team) le faisait."""
        competence = _setup_competence_chain(request_type)
        crisis = Crisis.objects.create(name="Crise unif 1", type="INCEDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)
        team = Team.objects.create(name="Equipe unif 1", description="", color="#3b82f6")
        AffectationCompetence.objects.create(crise=crisis, competence=competence, equipe=team, active=True)

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande lien dossier", "location": "POINT (5.72 45.18)",
                "first_name_request": "A", "last_name_request": "B", "email_request": "lien-dossier@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(crise=crisis, competence=competence)
        assert str(dossier.demande_id) == response.data["id"]

    def test_anonymous_demandeur_becomes_participant(self, request_type, create_user):
        """Une demande anonyme (sans auteur authentifié) doit tout de même obtenir un
        participant DEMANDEUR via resolve_or_invite_demandeur, pour pouvoir suivre son
        dossier — avant l'unification, seul demande.author (donc jamais l'anonyme) comptait."""
        competence = _setup_competence_chain(request_type)
        crisis = Crisis.objects.create(name="Crise unif 2", type="INCEDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande anonyme unif", "location": "POINT (5.72 45.18)",
                "first_name_request": "Anna", "last_name_request": "Onyme",
                "email_request": "anonyme-unif@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(crise=crisis, competence=competence)
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur__email="anonyme-unif@test.fr",
            role=DossierParticipant.Role.DEMANDEUR,
        ).exists()

    def test_regulateur_becomes_regulation_participant(self, request_type, create_user):
        """Le rôle REGULATION de DossierParticipant, jusqu'ici jamais peuplé, doit
        maintenant l'être pour tout régulateur notifié sur le chemin automatique."""
        competence = _setup_competence_chain(request_type)
        crisis = Crisis.objects.create(name="Crise unif 3", type="INCEDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)
        team = Team.objects.create(name="Equipe unif 3", description="", color="#3b82f6")
        AffectationCompetence.objects.create(crise=crisis, competence=competence, equipe=team, active=True)
        regulateur = _regulateur(create_user, competence, email="regul-unif3@test.fr")

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande regulation participant", "location": "POINT (5.72 45.18)",
                "first_name_request": "A", "last_name_request": "B", "email_request": "regparticip@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(crise=crisis, competence=competence)
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=regulateur, role=DossierParticipant.Role.REGULATION,
        ).exists()

    def test_no_competence_branch_still_links_demandeur(self, request_type, create_user):
        """Même quand aucune compétence n'est trouvée, le dossier de secours doit au moins
        rattacher le demandeur comme participant (avant : zéro participant du tout)."""
        crisis = Crisis.objects.create(name="Crise unif 4", type="INCEDIE", location="POINT (5.72 45.18)")
        _declare_responsable(crisis, create_user)

        client = APIClient()
        response = client.post(
            reverse('request-list'),
            {
                "title": "Demande sans competence unif", "location": "POINT (5.72 45.18)",
                "first_name_request": "A", "last_name_request": "B", "email_request": "sanscompunif@test.fr",
                "phone_request": "0600000000", "status": "NON_TRAITEE",
                "request_type": str(request_type.id), "crisis": str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        dossier = Dossier.objects.get(crise=crisis, competence=None)
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur__email="sanscompunif@test.fr",
            role=DossierParticipant.Role.DEMANDEUR,
        ).exists()


@pytest.mark.django_db
class TestManualPathParticipants:

    def test_assign_team_populates_equipe_participants(self, local_authority_client, create_user):
        """assign_team ajoutait un régulateur notifié mais jamais l'équipe elle-même comme
        DossierParticipant — désormais unifié avec le chemin automatique."""
        client, _ = local_authority_client
        from core.test_requests import REQUEST_PAYLOAD
        from core.models import Request

        request_type_local = None
        from core.models import RequestType
        request_type_local = RequestType.objects.create(type="Type unif manuel")

        author = create_user(username="demandeur-unif-manuel@test.fr", email="demandeur-unif-manuel@test.fr", type="UTIL_SIMPLE")
        demande = Request.objects.create(
            request_type=request_type_local, crisis=None, author=author,
            **{**REQUEST_PAYLOAD, "email_request": "demandeur-unif-manuel@test.fr"},
        )
        demande.crisis = Crisis.objects.create(name="Crise unif manuel", type="INCEDIE", location="POINT (5.72 45.18)")
        demande.save()

        team = Team.objects.create(name="Equipe unif manuel", description="", color="#3b82f6")
        membre = create_user(username="membre-unif-manuel@test.fr", email="membre-unif-manuel@test.fr", type="UTIL_SIMPLE")
        team.members.add(membre)

        response = client.post(
            reverse('request-assign-team', args=[demande.id]), {"team": str(team.id)}, format='json'
        )

        assert response.status_code == status.HTTP_200_OK
        dossier = Dossier.objects.get(id=response.data["dossier"])
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=membre, role=DossierParticipant.Role.EQUIPE,
        ).exists()

    def test_assign_team_populates_regulation_role(self, local_authority_client, request_type, create_user):
        """Le régulateur notifié par assign_team doit aussi apparaître comme
        DossierParticipant(role=REGULATION), pas seulement recevoir une Notification."""
        client, _ = local_authority_client
        from core.test_requests import REQUEST_PAYLOAD
        from core.models import Request

        crisis = Crisis.objects.create(name="Crise unif manuel regul", type="INCEDIE", location="POINT (5.72 45.18)")
        author = create_user(username="demandeur-unif-regul@test.fr", email="demandeur-unif-regul@test.fr", type="UTIL_SIMPLE")
        demande = Request.objects.create(
            request_type=request_type, crisis=crisis, author=author,
            **{**REQUEST_PAYLOAD, "email_request": "demandeur-unif-regul@test.fr"},
        )

        team = Team.objects.create(name="Equipe unif manuel regul", description="", color="#3b82f6")
        regulateur = create_user(username="regul-unif-manuel@test.fr", email="regul-unif-manuel@test.fr", type="UTIL_SIMPLE")
        team.members.add(regulateur)
        role = RoleOperationnel.objects.create(code="REGULATEUR", libelle="Régulateur")
        competence = Competence.objects.create(nom="Competence unif manuel regul")
        team.competences.add(competence)
        itype = InstitutionType.objects.create(code="ITYPE_UNIF_MANUEL", libelle="Mairie")
        institution = Institution.objects.create(nom="Institution unif manuel", type=itype)
        AffectationRoleOperationnel.objects.create(
            utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True,
        )

        response = client.post(
            reverse('request-assign-team', args=[demande.id]), {"team": str(team.id)}, format='json'
        )

        assert response.status_code == status.HTTP_200_OK
        dossier = Dossier.objects.get(id=response.data["dossier"])
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=regulateur, role=DossierParticipant.Role.REGULATION,
        ).exists()
