"""Création/réutilisation d'une institution confirmée par l'annuaire officiel.

Ce bloc recoupait sur le SEUL nom de l'institution. Comme une même mairie porte des noms
différents selon qui l'a enregistrée, celle déjà connue sous « Châteauneuf-du-Faou » a été
recréée sous « Mairie - Châteauneuf-du-Faou » dès qu'un adjoint s'est inscrit par l'annuaire
(27/10/2026). Conséquences constatées en production : deux institutions pour une commune, les
deux déclarées acteur sur la même crise, deux équipes jumelles, un adjoint dont le compte
pointait sur l'une pendant que son plan vivait sur l'autre — et une fusion manuelle qui a
détruit au passage sa fonction, son statut de contact principal et son rôle opérationnel.

Le même bloc créait aussi son `InstitutionType` avec un code mis en minuscules, d'où un
catalogue où « MAIRIE » et « mairie » cohabitaient (4 institutions d'un côté, 5 de l'autre).
Les lectures qui gouvernent l'accès aux fonctions PCS normalisent la casse, mais pas toutes :
`backfill_zones_mon_territoire` sautait silencieusement cinq mairies sur neuf.

Une commune n'a qu'une mairie : c'est le couple (commune, type) qui l'identifie, pas son nom.
"""
import pytest

from core.institution_attachment import find_or_create_institution_from_annuaire
from core.models import AuditAction, AuditLog, Institution, InstitutionType


@pytest.fixture
def candidat(create_user, db):
    user = create_user(username="adjoint-annuaire@test.fr", email="adjoint-annuaire@test.fr",
                       type="AUT_LOCALE")
    user.pending_institution_name = "Mairie de Quimper"
    user.pending_commune_code = "29232"
    user.pending_commune_name = "Quimper"
    user.save(update_fields=["pending_institution_name", "pending_commune_code",
                             "pending_commune_name"])
    return user


def _annuaire(nom="Mairie - Quimper", type_code="mairie", domain=None):
    return {"nom": nom, "type_service_local": type_code, "domain": domain}


def _mairie(nom, commune="29232", code_type="MAIRIE", actif=True):
    itype, _ = InstitutionType.objects.get_or_create(
        code=code_type, defaults={"libelle": "Mairie"})
    return Institution.objects.create(
        nom=nom, type=itype, commune_code=commune, commune_nom="Quimper", actif=actif)


class TestUneCommuneUneMairie:
    def test_une_institution_existante_est_reutilisee_malgre_un_autre_nom(self, candidat):
        """LE test : c'est ce recoupement qui n'existait pas."""
        existante = _mairie("Quimper")

        trouvee = find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Mairie - Quimper"))

        assert trouvee.pk == existante.pk
        assert Institution.objects.filter(commune_code="29232").count() == 1

    def test_le_nom_existant_nest_pas_ecrase_par_celui_de_lannuaire(self, candidat):
        """Le nom a pu être choisi par un administrateur : l'annuaire ne le corrige pas."""
        _mairie("Quimper")

        trouvee = find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Mairie - Quimper"))

        assert trouvee.nom == "Quimper"

    def test_la_casse_du_type_ne_cree_pas_de_doublon(self, candidat):
        """L'annuaire rend « mairie », le catalogue contient « MAIRIE » : un seul type."""
        _mairie("Quimper", code_type="MAIRIE")
        avant = InstitutionType.objects.filter(code__iexact="MAIRIE").count()

        find_or_create_institution_from_annuaire(candidat, _annuaire(type_code="mairie"))

        assert InstitutionType.objects.filter(code__iexact="MAIRIE").count() == avant
        assert Institution.objects.filter(commune_code="29232").count() == 1

    def test_un_type_inconnu_est_cree_en_majuscules(self, candidat):
        find_or_create_institution_from_annuaire(
            candidat, _annuaire(type_code="syndicat_mixte"))

        assert InstitutionType.objects.filter(code="SYNDICAT_MIXTE").exists()
        assert not InstitutionType.objects.filter(code="syndicat_mixte").exists()

    def test_un_type_different_sur_la_meme_commune_nest_pas_confondu(self, candidat):
        """Une police municipale et une mairie partagent la commune sans être la même
        institution."""
        police, _ = InstitutionType.objects.get_or_create(
            code="POLICE_MUNICIPALE", defaults={"libelle": "Police municipale"})
        Institution.objects.create(nom="Police municipale de Quimper", type=police,
                                   commune_code="29232", commune_nom="Quimper")

        trouvee = find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Mairie - Quimper", type_code="mairie"))

        assert trouvee.nom == "Mairie - Quimper"
        assert Institution.objects.filter(commune_code="29232").count() == 2


class TestCeQuiNeDoitPasEtreRessuscite:
    def test_une_institution_retiree_du_service_nest_pas_reactivee(self, candidat):
        """Une collectivité délibérément désactivée ne doit pas revenir parce qu'un inconnu
        s'inscrit. Créer une nouvelle institution est alors le comportement juste."""
        retiree = _mairie("Quimper", actif=False)

        trouvee = find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Mairie - Quimper"))

        assert trouvee.pk != retiree.pk
        assert trouvee.actif is True
        retiree.refresh_from_db()
        assert retiree.actif is False

    def test_la_plus_ancienne_lemporte_quand_il_y_a_deja_deux_actives(self, candidat):
        """Base déjà polluée par l'ancien comportement : on se raccroche à la plus ancienne,
        celle qui porte le plus d'histoire, au lieu d'en ajouter une troisième."""
        ancienne = _mairie("Quimper")
        _mairie("Mairie - Quimper")

        trouvee = find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Hôtel de Ville de Quimper"))

        assert trouvee.pk == ancienne.pk
        assert Institution.objects.filter(commune_code="29232").count() == 2


class TestRepliSurLeNom:
    def test_une_institution_sans_commune_reste_retrouvee_par_son_nom(self, candidat):
        """Associations et services de l'État n'ont pas de code commune : le filtre
        territorial ne peut pas les voir, le repli historique reste nécessaire."""
        itype, _ = InstitutionType.objects.get_or_create(
            code="ASSOCIATION", defaults={"libelle": "Association"})
        sans_commune = Institution.objects.create(nom="Protection Civile 29", type=itype)

        trouvee = find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Protection Civile 29", type_code="association"))

        assert trouvee.pk == sans_commune.pk

    def test_la_commune_est_completee_sur_une_institution_qui_nen_avait_pas(self, candidat):
        """Ce qui permet au recoupement territorial de fonctionner la fois suivante."""
        itype, _ = InstitutionType.objects.get_or_create(
            code="MAIRIE", defaults={"libelle": "Mairie"})
        sans_commune = Institution.objects.create(nom="Mairie - Quimper", type=itype)

        find_or_create_institution_from_annuaire(candidat, _annuaire(nom="Mairie - Quimper"))

        sans_commune.refresh_from_db()
        assert sans_commune.commune_code == "29232"


class TestTracabilite:
    def test_le_rattachement_a_un_autre_nom_est_consigne(self, candidat, rf):
        """Sans cette trace, « j'ai été rattaché à une institution qui ne porte pas le nom que
        l'annuaire m'a montré » reste inexplicable à qui relit la main courante."""
        AuditAction.objects.get_or_create(
            code="MODIFICATION", defaults={"libelle": "Modification"})
        _mairie("Quimper")
        requete = rf.post("/")
        requete.user = candidat

        find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Mairie - Quimper"), request=requete)

        traces = AuditLog.objects.filter(objet_type="Institution")
        assert any("aucune seconde institution créée" in (t.commentaire or "")
                   for t in traces)

    def test_aucune_trace_inutile_quand_les_noms_concordent(self, candidat, rf):
        _mairie("Mairie - Quimper")
        requete = rf.post("/")
        requete.user = candidat

        find_or_create_institution_from_annuaire(
            candidat, _annuaire(nom="Mairie - Quimper"), request=requete)

        assert not AuditLog.objects.filter(
            objet_type="Institution", commentaire__icontains="aucune seconde").exists()
