"""Planning d'équipe : qui tient quel créneau, quel jour.

Demande de Sylvain du 12/11/2026 : « vas-y, prévois le planning d'équipe et tout le
nécessaire ». Jusque-là, pointer un créneau à la main hors campagne ne laissait qu'une ligne
au journal d'audit — aucune table ne savait dire « cette équipe tient le soir du 14 ».

Ce que ces tests tiennent, dans l'ordre d'importance :

1. **Le double engagement est détecté et NOMMÉ.** La même personne attendue par deux équipes
   au même créneau n'est pas un oubli de saisie. On ne bloque pas (il existe des cas réels),
   mais on dit qui, quand, et avec quelle équipe — « 3 conflits » n'a jamais permis de
   décider.
2. **L'effectif d'un créneau ne compte ni les annulés ni les absents.** Compter une ligne
   annulée ferait croire une garde armée.
3. **Repointer une case ne crée pas de doublon** : la clé est
   `(équipe, personne, jour, créneau)`, deux clics feraient compter deux présents.
4. **Affecter quelqu'un hors de ses disponibilités déclarées est permis mais signalé** : un
   chef d'équipe a le droit d'appeler, et le taire ferait partir une garde sur une présence
   que personne n'a confirmée.
5. **Composer un planning est un ordre de service** : réservé à qui gère l'équipe.
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, CreneauEquipe, DisponibiliteOffre, FicheBenevole, Institution,
    InstitutionType, StatutCreneauEquipe, Team, UserRole,
)


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="AASC Planning", type=itype, actif=True)


@pytest.fixture
def autre_aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="AASC Planning Voisine", type=itype, actif=True)


def _membre(create_user, institution, nom):
    user = create_user(username=f"{nom.lower()}-plan@test.fr",
                       email=f"{nom.lower()}-plan@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name=nom)
    ContactInstitution.objects.create(
        institution=institution, utilisateur=user, actif=True, fonction="Équipier")
    return user


def _equipe(institution, nom, membres=()):
    equipe = Team.objects.create(name=nom, institution=institution, environment="PROD")
    if membres:
        equipe.members.add(*membres)
    return equipe


def _pointer(utilisateur, equipe, creneaux, **extra):
    return _client(utilisateur).post(
        reverse("creneauequipe-pointer"),
        {"equipe": str(equipe.id), "creneaux": creneaux, **extra}, format="json")


def _case(utilisateur, jour, creneau="SOIR"):
    return {"utilisateur": str(utilisateur.id), "date": jour.isoformat(), "creneau": creneau}


DEMAIN = timezone.localdate() + datetime.timedelta(days=1)


class TestPoserDesCreneaux:
    def test_un_creneau_pose_existe_en_base(self, create_user, aasc):
        chef = _membre(create_user, aasc, "CHEF")
        equipier = _membre(create_user, aasc, "EQUIPIER")
        equipe = _equipe(aasc, "Garde A", [chef, equipier])

        reponse = _pointer(chef, equipe, [_case(equipier, DEMAIN)])

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert reponse.data["poses"] == 1
        ligne = CreneauEquipe.objects.get(equipe=equipe, utilisateur=equipier)
        assert ligne.date == DEMAIN
        assert ligne.creneau == "SOIR"
        assert ligne.statut == StatutCreneauEquipe.PREVU

    def test_repointer_met_a_jour_sans_dupliquer(self, create_user, aasc):
        """Deux clics feraient compter deux présents là où il n'y en a qu'un."""
        chef = _membre(create_user, aasc, "CHEF2")
        equipier = _membre(create_user, aasc, "EQUIPIER2")
        equipe = _equipe(aasc, "Garde B", [chef, equipier])

        _pointer(chef, equipe, [_case(equipier, DEMAIN)])
        reponse = _pointer(chef, equipe, [_case(equipier, DEMAIN)],
                           statut=StatutCreneauEquipe.CONFIRME)

        assert reponse.data["poses"] == 0
        assert reponse.data["mis_a_jour"] == 1
        assert CreneauEquipe.objects.filter(equipe=equipe, utilisateur=equipier).count() == 1
        assert CreneauEquipe.objects.get(
            equipe=equipe, utilisateur=equipier).statut == StatutCreneauEquipe.CONFIRME

    def test_quelquun_hors_de_lequipe_est_refuse_nommement(self, create_user, aasc):
        """Un planning qui affecte des gens hors de l'équipe ne décrit plus rien."""
        chef = _membre(create_user, aasc, "CHEF3")
        dehors = _membre(create_user, aasc, "DEHORS")
        equipe = _equipe(aasc, "Garde C", [chef])

        reponse = _pointer(chef, equipe, [_case(dehors, DEMAIN)])

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "membre de cette équipe" in reponse.data["ignores"][0]["motif"]
        assert not CreneauEquipe.objects.filter(utilisateur=dehors).exists()

    def test_une_autre_institution_ne_compose_pas_ce_planning(
            self, create_user, aasc, autre_aasc):
        """Un planning est un ordre de service, pas une suggestion."""
        equipier = _membre(create_user, aasc, "EQUIPIER4")
        equipe = _equipe(aasc, "Garde D", [equipier])
        etranger = _membre(create_user, autre_aasc, "ETRANGER")

        reponse = _pointer(etranger, equipe, [_case(equipier, DEMAIN)])

        assert reponse.status_code == status.HTTP_403_FORBIDDEN


class TestLesDoublesEngagements:
    def test_la_meme_personne_dans_deux_equipes_est_signalee(self, create_user, aasc):
        """LE test. Quelqu'un attendu à deux endroits au même moment."""
        chef = _membre(create_user, aasc, "CHEF5")
        equipier = _membre(create_user, aasc, "PARTAGE")
        premiere = _equipe(aasc, "Garde matin", [chef, equipier])
        seconde = _equipe(aasc, "Garde renfort", [chef, equipier])

        _pointer(chef, premiere, [_case(equipier, DEMAIN)])
        reponse = _pointer(chef, seconde, [_case(equipier, DEMAIN)])

        conflits = reponse.data["conflits"]
        assert len(conflits) == 1
        # Nommé, pas compté : on doit savoir QUI, QUAND et avec QUELLE équipe.
        assert conflits[0]["equipe_nom"] == "Garde matin"
        assert conflits[0]["date"] == DEMAIN.isoformat()
        assert conflits[0]["creneau"] == "SOIR"
        # Et le créneau est posé quand même : il existe des cas légitimes.
        assert reponse.data["poses"] == 1

    def test_un_creneau_annule_ailleurs_nest_pas_un_conflit(self, create_user, aasc):
        """Une ligne annulée n'attend plus personne : la signaler ferait chercher un
        problème qui n'existe pas."""
        chef = _membre(create_user, aasc, "CHEF6")
        equipier = _membre(create_user, aasc, "LIBERE")
        premiere = _equipe(aasc, "Garde annulée", [chef, equipier])
        seconde = _equipe(aasc, "Garde reprise", [chef, equipier])
        _pointer(chef, premiere, [_case(equipier, DEMAIN)],
                 statut=StatutCreneauEquipe.ANNULE)

        reponse = _pointer(chef, seconde, [_case(equipier, DEMAIN)])

        assert reponse.data["conflits"] == []

    def test_le_meme_creneau_dans_la_MEME_equipe_nest_pas_un_conflit(
            self, create_user, aasc):
        chef = _membre(create_user, aasc, "CHEF7")
        equipier = _membre(create_user, aasc, "MEME")
        equipe = _equipe(aasc, "Garde E", [chef, equipier])
        _pointer(chef, equipe, [_case(equipier, DEMAIN)])

        reponse = _pointer(chef, equipe, [_case(equipier, DEMAIN)])

        assert reponse.data["conflits"] == []


class TestHorsDisponibiliteDeclaree:
    def _ressource(self, membre, institution):
        from core.fiches_benevoles import ressource_du_benevole

        fiche, _ = FicheBenevole.objects.get_or_create(
            utilisateur=membre, defaults={"environment": "PROD"})
        offre, _cree = ressource_du_benevole(fiche, institution)
        return offre

    def test_un_creneau_non_declare_est_signale_mais_pose(self, create_user, aasc):
        """Un chef d'équipe a le droit d'appeler ; l'interdire supposerait que la grille
        déclarée est exhaustive, ce qu'elle n'est pas."""
        chef = _membre(create_user, aasc, "CHEF8")
        equipier = _membre(create_user, aasc, "SILENCIEUX")
        self._ressource(equipier, aasc)
        equipe = _equipe(aasc, "Garde F", [chef, equipier])

        reponse = _pointer(chef, equipe, [_case(equipier, DEMAIN)])

        assert reponse.data["poses"] == 1
        assert len(reponse.data["hors_disponibilite"]) == 1
        assert reponse.data["hors_disponibilite"][0]["creneau"] == "SOIR"

    def test_un_creneau_declare_ne_remonte_pas(self, create_user, aasc):
        chef = _membre(create_user, aasc, "CHEF9")
        equipier = _membre(create_user, aasc, "DECLARANT")
        offre = self._ressource(equipier, aasc)
        DisponibiliteOffre.objects.create(offer=offre, date=DEMAIN, creneau="SOIR")
        equipe = _equipe(aasc, "Garde G", [chef, equipier])

        reponse = _pointer(chef, equipe, [_case(equipier, DEMAIN)])

        assert reponse.data["hors_disponibilite"] == []


class TestLeffectifTenu:
    def test_les_annules_et_les_absents_ne_comptent_pas(self, create_user, aasc):
        """Compter une ligne annulée ferait croire une garde armée."""
        chef = _membre(create_user, aasc, "CHEF10")
        present = _membre(create_user, aasc, "PRESENT")
        absent = _membre(create_user, aasc, "ABSENT")
        annule = _membre(create_user, aasc, "ANNULE")
        equipe = _equipe(aasc, "Garde H", [chef, present, absent, annule])

        _pointer(chef, equipe, [_case(present, DEMAIN)],
                 statut=StatutCreneauEquipe.CONFIRME)
        _pointer(chef, equipe, [_case(absent, DEMAIN)], statut=StatutCreneauEquipe.ABSENT)
        _pointer(chef, equipe, [_case(annule, DEMAIN)], statut=StatutCreneauEquipe.ANNULE)

        planning = _client(chef).get(
            reverse("creneauequipe-planning"),
            {"equipe": str(equipe.id), "jours": 3}).data

        assert planning["effectifs"][DEMAIN.isoformat()]["SOIR"] == 1

    def test_le_planning_montre_tous_les_membres_meme_sans_creneau(
            self, create_user, aasc):
        """Un planning qui ne montre que les gens déjà placés ne permet pas de voir qui
        reste à placer."""
        chef = _membre(create_user, aasc, "CHEF11")
        libre = _membre(create_user, aasc, "DISPONIBLE")
        equipe = _equipe(aasc, "Garde I", [chef, libre])

        planning = _client(chef).get(
            reverse("creneauequipe-planning"), {"equipe": str(equipe.id)}).data

        # `create_user` donne « Test » comme prénom : on compare sur le patronyme.
        noms = {p["nom"].split()[-1] for p in planning["personnes"]}
        assert noms == {"CHEF11", "DISPONIBLE"}

    def test_les_creneaux_sous_armes_sont_listes(self, create_user, aasc):
        """Les chercher à l'œil dans quatorze colonnes est ce qu'un écran doit éviter de
        faire faire."""
        chef = _membre(create_user, aasc, "CHEF12")
        equipe = _equipe(aasc, "Garde J", [chef])

        planning = _client(chef).get(
            reverse("creneauequipe-planning"),
            {"equipe": str(equipe.id), "jours": 1, "effectif_cible": 2}).data

        # Un jour, quatre créneaux, aucun armé : quatre manques de deux.
        assert len(planning["non_couverts"]) == 4
        assert planning["non_couverts"][0]["manque"] == 2


class TestLaGrilleDeLassociationAlimenteLePlanning:
    def test_affecter_avec_des_creneaux_remplit_le_planning(self, create_user, aasc):
        """Le lien entre les deux écrans : pointer dans la grille de l'association pose
        vraiment le créneau, au lieu de n'être qu'une ligne d'audit."""
        bureau = create_user(username="bureau-plan@test.fr", email="bureau-plan@test.fr",
                             type=UserRole.ORGANIZED_RESCUE, last_name="BUREAU")
        ContactInstitution.objects.create(
            institution=aasc, utilisateur=bureau, actif=True, membre_bureau=True)
        equipier = _membre(create_user, aasc, "AFFECTE")
        equipe = _equipe(aasc, "Garde K", [])

        reponse = _client(bureau).post(
            reverse("team-ajouter-membres", args=[str(equipe.id)]),
            {"utilisateurs": [str(equipier.id)],
             "creneaux": [_case(equipier, DEMAIN, "MATIN")]},
            format="json")

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert reponse.data["creneaux_planning"] == 1
        ligne = CreneauEquipe.objects.get(equipe=equipe, utilisateur=equipier)
        # CONFIRMÉ : un humain vient de cocher la case, ce n'est pas un planning prévisionnel.
        assert ligne.statut == StatutCreneauEquipe.CONFIRME
        assert ligne.creneau == "MATIN"
