"""Grille de disponibilités à quinze jours, pour armer une mobilisation.

Ce que ces tests tiennent, dans l'ordre d'importance :

1. **Trois valeurs par case, pas deux.** Disponible, indisponible, ou **non renseigné**.
   Confondre « a dit non » et « n'a pas répondu » est l'erreur qui fait partir une mobilisation
   avec un effectif imaginaire.
2. **Les absents sont comptés, pas tus.** Les membres sortis et en congé ne figurent pas dans la
   grille, mais le nombre de congés est rendu : une liste qui omet des gens sans le dire laisse
   chercher où ils sont passés.
3. **Le contrôle d'accès est porté par l'action.** Le ViewSet qui l'héberge n'a pas de cadrage
   par institution, et une nouvelle action ne doit pas en hériter.
4. **Le dernier mot l'emporte** sur deux déclarations qui se recouvrent : quelqu'un qui se
   dédit a changé d'avis.
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel, ContactInstitution, DisponibiliteOperationnelle, Institution,
    InstitutionType, Qualification, QualificationMembre, RoleOperationnel, UserRole,
)


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    institution, _ = Institution.objects.get_or_create(
        nom="AASC Grille Test", defaults={"type": itype, "actif": True})
    return institution


@pytest.fixture
def role(db):
    return RoleOperationnel.objects.get_or_create(
        code="INTERVENANT", defaults={"libelle": "Intervenant"})[0]


def _membre(create_user, aasc, role, nom, statut=ContactInstitution.StatutMembre.ACTIF):
    user = create_user(username=f"{nom.lower()}-grille@test.fr",
                       email=f"{nom.lower()}-grille@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name=nom)
    ContactInstitution.objects.create(
        institution=aasc, utilisateur=user, fonction="Équipier", actif=True, statut=statut)
    affectation, _ = AffectationRoleOperationnel.objects.get_or_create(
        utilisateur=user, institution=aasc, role=role, competence=None)
    return user, affectation


def _declarer(affectation, disponible, debut_jours, fin_jours=None):
    maintenant = timezone.now()
    return DisponibiliteOperationnelle.objects.create(
        affectation=affectation, disponible=disponible,
        date_debut=maintenant + datetime.timedelta(days=debut_jours),
        date_fin=None if fin_jours is None
        else maintenant + datetime.timedelta(days=fin_jours),
        environment="PROD",
    )


def _grille(utilisateur, aasc, **params):
    return _client(utilisateur).get(
        reverse("disponibiliteoperationnelle-grille"),
        {"institution": str(aasc.id), **params})


class TestTroisValeursParCase:
    def test_sans_declaration_le_jour_est_non_renseigne(
            self, create_user, aasc, role):
        """LE test. `null` n'est pas « indisponible » : c'est un silence, et l'écran doit
        pouvoir le montrer pour qu'on sache qui relancer."""
        membre, _ = _membre(create_user, aasc, role, "SILENCIEUX")

        reponse = _grille(membre, aasc)

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        fiche = reponse.data["membres"][0]
        assert all(j["disponible"] is None for j in fiche["jours"])

    def test_une_disponibilite_declaree_remplit_sa_periode(
            self, create_user, aasc, role):
        membre, affectation = _membre(create_user, aasc, role, "DISPO")
        _declarer(affectation, True, 0, 2)

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["jours"][0]["disponible"] is True
        assert fiche["jours"][2]["disponible"] is True
        # Au-delà de la période déclarée : silence, pas refus.
        assert fiche["jours"][5]["disponible"] is None

    def test_une_indisponibilite_est_distincte_dun_silence(
            self, create_user, aasc, role):
        membre, affectation = _membre(create_user, aasc, role, "ABSENT")
        _declarer(affectation, False, 0, 1)

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["jours"][0]["disponible"] is False
        assert fiche["jours"][10]["disponible"] is None

    def test_une_permanence_sans_fin_couvre_toute_la_fenetre(
            self, create_user, aasc, role):
        """`date_fin` nulle = permanence ouverte (voir l'action prendre_permanence)."""
        membre, affectation = _membre(create_user, aasc, role, "PERMANENT")
        _declarer(affectation, True, 0, None)

        fiche = _grille(membre, aasc).data["membres"][0]

        assert all(j["disponible"] is True for j in fiche["jours"])

    def test_le_dernier_mot_lemporte(self, create_user, aasc, role):
        """Deux déclarations qui se recouvrent : quelqu'un qui se dédit a changé d'avis."""
        membre, affectation = _membre(create_user, aasc, role, "INDECIS")
        _declarer(affectation, True, 0, 10)
        _declarer(affectation, False, 2, 4)

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["jours"][0]["disponible"] is True
        assert fiche["jours"][3]["disponible"] is False
        assert fiche["jours"][6]["disponible"] is True


class TestQuiFigureDansLaGrille:
    def test_un_membre_sorti_nest_pas_liste(self, create_user, aasc, role):
        _membre(create_user, aasc, role, "PRESENT")
        _membre(create_user, aasc, role, "PARTI",
                statut=ContactInstitution.StatutMembre.SORTI)
        lecteur, _ = _membre(create_user, aasc, role, "LECTEUR")

        noms = {m["nom"] for m in _grille(lecteur, aasc).data["membres"]}

        assert "Test PARTI" not in noms

    def test_les_conges_sont_comptes_et_non_tus(self, create_user, aasc, role):
        """Ils ne figurent pas dans la grille — un membre en congé n'est pas mobilisable —
        mais leur nombre est rendu, sinon on cherche où ils sont passés."""
        lecteur, _ = _membre(create_user, aasc, role, "LECTEUR")
        _membre(create_user, aasc, role, "REPOS",
                statut=ContactInstitution.StatutMembre.CONGE)

        data = _grille(lecteur, aasc).data

        assert "Test REPOS" not in {m["nom"] for m in data["membres"]}
        assert data["membres_en_conge"] == 1

    def test_les_membres_sont_tries_par_nom(self, create_user, aasc, role):
        _membre(create_user, aasc, role, "ZULU")
        lecteur, _ = _membre(create_user, aasc, role, "ALPHA")

        noms = [m["nom"] for m in _grille(lecteur, aasc).data["membres"]]

        assert noms == sorted(noms, key=str.lower)


class TestSignauxDeMobilisation:
    def test_un_titre_perime_est_compte(self, create_user, aasc, role):
        """Un PSE1 expiré vaut un PSE1 absent : la grille doit le dire à côté du nom, pas le
        laisser découvrir le jour du départ."""
        membre, _ = _membre(create_user, aasc, role, "PERIME")
        titre = Qualification.objects.create(nom="PSE1 Grille Test")
        QualificationMembre.objects.create(
            utilisateur=membre, qualification=titre, environment="PROD",
            date_expiration=timezone.localdate() - datetime.timedelta(days=1))

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["qualifications_expirees"] == 1

    def test_un_titre_valide_nest_pas_compte(self, create_user, aasc, role):
        membre, _ = _membre(create_user, aasc, role, "AJOUR")
        titre = Qualification.objects.create(nom="PSE2 Grille Test")
        QualificationMembre.objects.create(
            utilisateur=membre, qualification=titre, environment="PROD",
            date_expiration=timezone.localdate() + datetime.timedelta(days=90))

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["qualifications_expirees"] == 0

    def test_laptitude_est_rendue_avec_la_ligne(self, create_user, aasc, role):
        """Date seule, comme partout : elle interdit le terrain quand elle est échue, sans rien
        dire de la personne."""
        membre, _ = _membre(create_user, aasc, role, "APTE")
        echeance = timezone.localdate() + datetime.timedelta(days=200)
        ContactInstitution.objects.filter(institution=aasc, utilisateur=membre).update(
            aptitude_valide_jusquau=echeance)

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["aptitude_valide_jusquau"] == echeance


class TestAccesALaGrille:
    def test_un_non_membre_est_refuse(self, create_user, aasc, role):
        """Le ViewSet hôte n'a pas de cadrage par institution : l'action porte le sien, sans
        quoi elle en hériterait l'ouverture."""
        _membre(create_user, aasc, role, "INTERNE")
        etranger = create_user(username="etranger-grille@test.fr",
                               email="etranger-grille@test.fr",
                               type=UserRole.LOCAL_AUTHORITY, last_name="ETRANGER")

        reponse = _grille(etranger, aasc)

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_un_administrateur_passe(self, create_user, aasc, role):
        _membre(create_user, aasc, role, "INTERNE2")
        admin = create_user(username="admin-grille@test.fr", email="admin-grille@test.fr",
                            type=UserRole.ADMINISTRATOR, last_name="ADMIN")

        assert _grille(admin, aasc).status_code == status.HTTP_200_OK

    def test_sans_institution_cest_une_erreur_explicite(self, create_user, aasc, role):
        lecteur, _ = _membre(create_user, aasc, role, "LECTEUR2")

        reponse = _client(lecteur).get(reverse("disponibiliteoperationnelle-grille"))

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "institution" in reponse.data["error"]

    def test_un_anonyme_na_pas_acces(self, aasc):
        reponse = APIClient().get(reverse("disponibiliteoperationnelle-grille"),
                                  {"institution": str(aasc.id)})

        assert reponse.status_code in (status.HTTP_401_UNAUTHORIZED,
                                       status.HTTP_403_FORBIDDEN)


class TestFenetre:
    def test_quinze_jours_par_defaut(self, create_user, aasc, role):
        lecteur, _ = _membre(create_user, aasc, role, "FENETRE")

        data = _grille(lecteur, aasc).data

        assert len(data["jours"]) == 15
        assert data["debut"] == timezone.localdate()
        assert data["fin"] == timezone.localdate() + datetime.timedelta(days=14)

    def test_la_fenetre_est_bornee(self, create_user, aasc, role):
        """Une grille de six mois n'est pas une grille, c'est un export — et elle ferait une
        case par jour et par membre à l'affichage."""
        lecteur, _ = _membre(create_user, aasc, role, "BORNE")

        data = _grille(lecteur, aasc, jours=400).data

        assert len(data["jours"]) == 31

    def test_une_valeur_absurde_retombe_sur_le_defaut(self, create_user, aasc, role):
        lecteur, _ = _membre(create_user, aasc, role, "ABSURDE")

        data = _grille(lecteur, aasc, jours="beaucoup").data

        assert len(data["jours"]) == 15
