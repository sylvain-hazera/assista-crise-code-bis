"""Grille de disponibilités à quinze jours, pour armer une mobilisation.

**Bascule du 11/11/2026 : la grille lit le moteur à créneaux** (`DisponibiliteOffre`, quatre
créneaux par jour), celui que lit aussi la constitution d'équipe. Elle lisait avant
`DisponibiliteOperationnelle`, une déclaration à la journée que personne d'autre ne consultait —
deux sources pour la même question, dont une seule décidait des mobilisations.

Ce que ces tests tiennent, dans l'ordre d'importance :

1. **Le silence reste distinct du refus, mais il n'est plus une valeur de case.** Ce moteur-ci
   tient « pas de ligne = indisponible » et ne sait pas stocker « non renseigné » : en base,
   une grille vierge et une grille entièrement décochée sont identiques. C'est `a_declare` qui
   les sépare, et c'est lui qui dit qui relancer. Confondre « a dit non » et « n'a pas
   répondu » reste l'erreur qui fait partir une mobilisation avec un effectif imaginaire.
2. **Les absents sont comptés, pas tus.** Les membres sortis et en congé ne figurent pas dans la
   grille, mais le nombre de congés est rendu : une liste qui omet des gens sans le dire laisse
   chercher où ils sont passés.
3. **Le contrôle d'accès est porté par l'action.** Le ViewSet qui l'héberge n'a pas de cadrage
   par institution, et une nouvelle action ne doit pas en hériter.
4. **Le créneau est l'unité**, pas la journée : quelqu'un de libre le matin et pris
   l'après-midi est une situation ordinaire, qu'une déclaration à la journée forcerait à
   déclarer « indisponible ».
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel, ContactInstitution, DisponibiliteOffre, FicheBenevole,
    Institution, InstitutionType, Qualification, QualificationMembre, RoleOperationnel,
    UserRole,
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


def _ressource(membre, aasc):
    """La ressource du membre — son offre « Bénévolat » interne.

    C'est elle qui porte les créneaux : le moteur est clé sur `Offer`, et c'est ce qui fait
    qu'un bénévole entre dans la constitution d'équipe."""
    from core.fiches_benevoles import ressource_du_benevole

    fiche, _ = FicheBenevole.objects.get_or_create(
        utilisateur=membre, defaults={"environment": "PROD"})
    offre, _cree = ressource_du_benevole(fiche, aasc)
    return offre


def _cocher(membre, aasc, decalage_jours, creneau="MATIN"):
    """Coche un créneau à J+n, comme le ferait l'écran du bénévole."""
    offre = _ressource(membre, aasc)
    return DisponibiliteOffre.objects.create(
        offer=offre, creneau=creneau,
        date=timezone.localdate() + datetime.timedelta(days=decalage_jours),
    )


def _grille(utilisateur, aasc, **params):
    return _client(utilisateur).get(
        reverse("disponibiliteoperationnelle-grille"),
        {"institution": str(aasc.id), **params})


class TestLesCasesViennentDuMoteurACreneaux:
    def test_sans_declaration_aucun_creneau_et_a_declare_faux(self, create_user, aasc, role):
        """LE test. Les cases vides ne sont pas des refus : `a_declare` le dit, et c'est lui
        qui permet de savoir qui relancer."""
        membre, _ = _membre(create_user, aasc, role, "SILENCIEUX")
        _ressource(membre, aasc)

        reponse = _grille(membre, aasc)

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        fiche = reponse.data["membres"][0]
        assert fiche["a_declare"] is False
        assert all(not any(j["creneaux"].values()) for j in fiche["jours"])

    def test_un_creneau_coche_ne_remplit_que_lui(self, create_user, aasc, role):
        """Le créneau est l'unité : cocher le matin ne dit rien du soir."""
        membre, _ = _membre(create_user, aasc, role, "MATINAL")
        _cocher(membre, aasc, 0, "MATIN")

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["a_declare"] is True
        assert fiche["jours"][0]["creneaux"]["MATIN"] is True
        assert fiche["jours"][0]["creneaux"]["SOIR"] is False
        # Le lendemain n'est pas déclaré : aucune case cochée.
        assert not any(fiche["jours"][1]["creneaux"].values())

    def test_la_grille_sert_les_quatre_creneaux_dans_l_ordre(self, create_user, aasc, role):
        """L'ordre est métier (matin → nuit) et vient du serveur : deux listes divergeraient."""
        membre, _ = _membre(create_user, aasc, role, "ORDRE")
        _ressource(membre, aasc)

        data = _grille(membre, aasc).data

        assert data["creneaux"] == ["MATIN", "MIDI", "SOIR", "NUIT"]
        assert set(data["membres"][0]["jours"][0]["creneaux"]) == {
            "MATIN", "MIDI", "SOIR", "NUIT"}

    def test_plusieurs_creneaux_le_meme_jour(self, create_user, aasc, role):
        membre, _ = _membre(create_user, aasc, role, "DOUBLE")
        _cocher(membre, aasc, 3, "MIDI")
        _cocher(membre, aasc, 3, "NUIT")

        jour = _grille(membre, aasc).data["membres"][0]["jours"][3]

        assert jour["creneaux"]["MIDI"] is True
        assert jour["creneaux"]["NUIT"] is True
        assert jour["creneaux"]["MATIN"] is False

    def test_un_creneau_hors_fenetre_n_apparait_pas(self, create_user, aasc, role):
        """Au-delà de quinze jours, la grille ne montre rien — et ne doit pas non plus
        remonter la déclaration sur un autre jour."""
        membre, _ = _membre(create_user, aasc, role, "LOINTAIN")
        _cocher(membre, aasc, 40, "MATIN")

        fiche = _grille(membre, aasc).data["membres"][0]

        assert len(fiche["jours"]) == 15
        assert all(not any(j["creneaux"].values()) for j in fiche["jours"])
        # Il a pourtant déclaré quelque chose : `a_declare` ne porte que sur la fenêtre lue.
        assert fiche["a_declare"] is False

    def test_les_creneaux_d_une_AUTRE_association_ne_comptent_pas(self, create_user, aasc,
                                                                  role):
        """Chaque association a sa propre ressource : partager une seule offre ferait voir à
        l'une les créneaux déclarés pour l'autre."""
        membre, _ = _membre(create_user, aasc, role, "DEUXASSOS")
        itype, _ = InstitutionType.objects.get_or_create(
            code="aasc", defaults={"libelle": "AASC"})
        autre = Institution.objects.create(nom="AASC Grille Autre", type=itype, actif=True)
        ContactInstitution.objects.create(institution=autre, utilisateur=membre, actif=True)
        _cocher(membre, autre, 1, "MATIN")

        fiche = _grille(membre, aasc).data["membres"][0]

        assert fiche["a_declare"] is False


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
