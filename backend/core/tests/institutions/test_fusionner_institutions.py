"""Fusion de deux Institution désignant la même collectivité.

Le doublon vient de la création : `find_or_create_institution_from_annuaire` fait son
`get_or_create` sur le seul NOM, sans recouper le code commune ni le type. Une mairie déjà
enregistrée sous un nom court est donc recréée dès qu'un agent s'inscrit par l'annuaire
officiel, qui la nomme autrement. Constaté en production le 27/10/2026 sur la commune 29027 :
« Châteauneuf-du-Faou » et « Mairie - Châteauneuf-du-Faou », les deux déclarées acteur sur la
même crise, et un adjoint dont le compte pointait sur l'une pendant que son plan vivait sur
l'autre.

Ce que ces tests tiennent, dans l'ordre d'importance :
1. aucune donnée de travail ne disparaît en silence (un risque renseigné n'est jamais écarté) ;
2. la passe à blanc n'écrit rien — c'est elle qui autorise à lancer l'opération en confiance ;
3. `User.institution` suit, parce que c'est lui que lisent les vues territoriales et qu'un
   compte oublié là reste aveugle à sa propre commune sans aucun message ;
4. la fusion ne se contredit pas elle-même : l'absorbée ne doit pas se voir refabriquer une
   Zone « Mon territoire » par le signal d'enregistrement.
"""
import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import (
    AffectationRoleOperationnel, ContactInstitution, Crisis, ImplicationInstitution, Institution,
    InstitutionType, Plan, RisqueCommunal, RisqueMajeurType, RoleOperationnel,
    StatutImplication, Team, TypeImplication, User, Zone,
)


def _institution(nom, code_type="MAIRIE", commune="29027"):
    itype, _ = InstitutionType.objects.get_or_create(
        code=code_type, defaults={"libelle": "Mairie"})
    return Institution.objects.create(
        nom=nom, type=itype, commune_code=commune, commune_nom="Châteauneuf-du-Faou")


def _compte(email, nom, institution=None):
    return User.objects.create_user(
        username=email, email=email, password="x", last_name=nom, institution=institution)


def _fusionner(garder, absorber, **kwargs):
    call_command("fusionner_institutions", garder=str(garder.pk), absorber=str(absorber.pk),
                 **kwargs)


@pytest.fixture
def paire(db):
    """Le cas réel : l'ancienne porte les coordonnées officielles, la nouvelle porte le compte."""
    ancienne = _institution("Châteauneuf-du-Faou", "MAIRIE")
    ancienne.email = "mairie@exemple.bzh"
    ancienne.telephone = "02 98 81 75 41"
    ancienne.adresse = "8 Rue de la Mairie"
    ancienne.actif = False
    ancienne.save()
    nouvelle = _institution("Mairie - Châteauneuf-du-Faou", "mairie")
    return nouvelle, ancienne


class TestGardeFous:
    def test_deux_communes_differentes_sont_refusees(self, db):
        a = _institution("Mairie A", commune="29027")
        b = _institution("Mairie B", commune="33063")
        with pytest.raises(CommandError, match="Codes commune différents"):
            _fusionner(a, b)

    def test_une_institution_avec_elle_meme_est_refusee(self, db):
        a = _institution("Mairie A")
        with pytest.raises(CommandError, match="la même institution"):
            _fusionner(a, a)

    def test_identifiant_inconnu(self, db):
        a = _institution("Mairie A")
        with pytest.raises(CommandError, match="aucune institution"):
            call_command("fusionner_institutions", garder=str(a.pk),
                         absorber="00000000-0000-0000-0000-000000000000")


class TestPasseABlanc:
    """C'est elle qui rend l'opération acceptable sur une base de production : on lit le plan
    avant d'écrire. Si elle laissait la moindre trace, elle ne servirait à rien."""

    def test_rien_nest_ecrit(self, paire):
        nouvelle, ancienne = paire
        compte = _compte("agent@exemple.bzh", "DELAPORTE", institution=ancienne)
        Team.objects.create(name="Équipe historique", institution=ancienne)

        _fusionner(nouvelle, ancienne, a_blanc=True)

        compte.refresh_from_db()
        ancienne.refresh_from_db()
        assert compte.institution_id == ancienne.pk
        assert ancienne.actif is False
        assert ancienne.nom == "Châteauneuf-du-Faou"
        assert Team.objects.get(name="Équipe historique").institution_id == ancienne.pk


class TestTransfert:
    def test_le_compte_suit(self, paire):
        """`User.institution` est ce que lisent les vues territoriales
        (zone_scoping._institution_commune_or_400) : un compte laissé sur l'absorbée reçoit
        « Aucune commune associée à votre institution » sur la moitié de l'application."""
        nouvelle, ancienne = paire
        compte = _compte("agent@exemple.bzh", "DELAPORTE", institution=ancienne)

        _fusionner(nouvelle, ancienne)

        compte.refresh_from_db()
        assert compte.institution_id == nouvelle.pk

    def test_les_equipes_et_les_plans_suivent(self, paire):
        nouvelle, ancienne = paire
        Team.objects.create(name="Cellule de crise", institution=ancienne)
        Plan.objects.create(nom="Dispositif tempête", institution=ancienne)

        _fusionner(nouvelle, ancienne)

        assert Team.objects.get(name="Cellule de crise").institution_id == nouvelle.pk
        assert Plan.objects.get(nom="Dispositif tempête").institution_id == nouvelle.pk

    def test_les_coordonnees_officielles_sont_reprises_a_la_demande(self, paire):
        """L'institution créée par l'annuaire hérite de l'adresse personnelle du premier
        inscrit ; celle créée à la main par un administrateur porte le standard de la mairie."""
        nouvelle, ancienne = paire
        nouvelle.email = "adjoint@exemple.bzh"
        nouvelle.save()

        _fusionner(nouvelle, ancienne, reprendre_identite=True)

        nouvelle.refresh_from_db()
        assert nouvelle.email == "mairie@exemple.bzh"
        assert nouvelle.telephone == "02 98 81 75 41"
        assert nouvelle.adresse == "8 Rue de la Mairie"

    def test_sans_le_drapeau_lidentite_nest_pas_touchee(self, paire):
        nouvelle, ancienne = paire
        nouvelle.email = "adjoint@exemple.bzh"
        nouvelle.save()

        _fusionner(nouvelle, ancienne)

        nouvelle.refresh_from_db()
        assert nouvelle.email == "adjoint@exemple.bzh"


class TestRattachements:
    def test_la_fonction_precise_lemporte_sur_membre(self, paire):
        """« Membre » est le repli du formulaire ; « Adjoint » a été saisi par quelqu'un."""
        nouvelle, ancienne = paire
        compte = _compte("agent@exemple.bzh", "DELAPORTE")
        ContactInstitution.objects.create(
            utilisateur=compte, institution=ancienne, fonction="Adjoint",
            contact_principal=True)
        ContactInstitution.objects.create(
            utilisateur=compte, institution=nouvelle, fonction="Membre")

        _fusionner(nouvelle, ancienne)

        restants = ContactInstitution.objects.filter(utilisateur=compte)
        assert restants.count() == 1
        contact = restants.get()
        assert contact.institution_id == nouvelle.pk
        assert contact.fonction == "Adjoint"
        assert contact.contact_principal is True
        # La zone de l'absorbée disparaît avec elle : le rattachement doit viser celle qui reste.
        assert contact.zone_id == Zone.objects.get(
            institution=nouvelle, nom="Mon territoire").pk

    def test_un_contact_absent_de_la_survivante_est_deplace(self, paire):
        nouvelle, ancienne = paire
        compte = _compte("rcsc@exemple.bzh", "LARVOR")
        ContactInstitution.objects.create(
            utilisateur=compte, institution=ancienne, fonction="Rcsc")

        _fusionner(nouvelle, ancienne)

        contact = ContactInstitution.objects.get(utilisateur=compte)
        assert contact.institution_id == nouvelle.pk
        assert contact.fonction == "Rcsc"

    def test_un_seul_contact_principal_apres_fusion(self, paire):
        """`uq_contact_principal_institution` ne tolère qu'un principal : deux principaux, un de
        chaque côté, ne doivent pas faire échouer toute la fusion."""
        nouvelle, ancienne = paire
        un = _compte("un@exemple.bzh", "UN")
        deux = _compte("deux@exemple.bzh", "DEUX")
        ContactInstitution.objects.create(
            utilisateur=un, institution=ancienne, fonction="Adjoint", contact_principal=True)
        ContactInstitution.objects.create(
            utilisateur=deux, institution=nouvelle, fonction="Maire", contact_principal=True)

        _fusionner(nouvelle, ancienne)

        principaux = ContactInstitution.objects.filter(
            institution=nouvelle, contact_principal=True)
        assert principaux.count() == 1
        # Celui de la survivante garde la main : désigner le principal appartient à la
        # collectivité, pas à une opération de maintenance.
        assert principaux.get().utilisateur_id == deux.pk


class TestDoublonsEtTravailHumain:
    @pytest.fixture
    def crise(self, db):
        return Crisis.objects.create(
            name="Tempête", description="x", location=Point(-3.98, 48.19, srid=4326))

    def test_une_implication_en_double_est_ecartee(self, paire, crise):
        nouvelle, ancienne = paire
        for inst in (ancienne, nouvelle):
            ImplicationInstitution.objects.create(
                crise=crise, institution=inst, type_implication=TypeImplication.ACTEUR,
                statut=StatutImplication.VALIDEE)

        _fusionner(nouvelle, ancienne)

        assert ImplicationInstitution.objects.filter(crise=crise).count() == 1
        assert ImplicationInstitution.objects.get(crise=crise).institution_id == nouvelle.pk

    def test_une_implication_unique_est_deplacee(self, paire, crise):
        nouvelle, ancienne = paire
        ImplicationInstitution.objects.create(
            crise=crise, institution=ancienne, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE)

        _fusionner(nouvelle, ancienne)

        assert ImplicationInstitution.objects.get(crise=crise).institution_id == nouvelle.pk

    def test_un_risque_vide_en_double_est_ecarte(self, paire):
        nouvelle, ancienne = paire
        rtype = RisqueMajeurType.objects.get_or_create(nom="Inondation")[0]
        for inst in (ancienne, nouvelle):
            RisqueCommunal.objects.create(institution=inst, risque_type=rtype)

        _fusionner(nouvelle, ancienne)

        assert RisqueCommunal.objects.filter(risque_type=rtype).count() == 1

    def test_un_risque_RENSEIGNE_nest_jamais_ecarte(self, paire):
        """La règle qui compte. L'état des lieux d'un risque, c'est un agent qui l'a écrit :
        l'écarter parce qu'une ligne du même type existe ailleurs détruirait du travail. On
        préfère le laisser sur l'absorbée et le DIRE."""
        nouvelle, ancienne = paire
        rtype = RisqueMajeurType.objects.get_or_create(nom="Inondation")[0]
        garde = RisqueCommunal.objects.create(
            institution=ancienne, risque_type=rtype,
            etat_des_lieux="Deux ponts submersibles, repérés en 2024.")
        RisqueCommunal.objects.create(institution=nouvelle, risque_type=rtype)

        _fusionner(nouvelle, ancienne)

        garde.refresh_from_db()
        assert garde.institution_id == ancienne.pk
        assert "submersibles" in garde.etat_des_lieux

    def test_deux_roles_differents_cohabitent(self, paire):
        """La contrainte porte sur (utilisateur, institution, compétence, rôle) : deux rôles
        distincts ne sont pas un doublon, et trancher entre eux n'est pas le travail d'une
        fusion."""
        nouvelle, ancienne = paire
        compte = _compte("agent@exemple.bzh", "DELAPORTE")
        responsable = RoleOperationnel.objects.create(code="RESP", libelle="Responsable")
        correspondant = RoleOperationnel.objects.create(code="CORR", libelle="Correspondant")
        AffectationRoleOperationnel.objects.create(
            utilisateur=compte, institution=ancienne, role=responsable)
        AffectationRoleOperationnel.objects.create(
            utilisateur=compte, institution=nouvelle, role=correspondant)

        _fusionner(nouvelle, ancienne)

        assert AffectationRoleOperationnel.objects.filter(
            utilisateur=compte, institution=nouvelle).count() == 2


class TestPierreTombale:
    def test_labsorbee_est_desactivee_et_nommee_sans_ambiguite(self, paire):
        nouvelle, ancienne = paire

        _fusionner(nouvelle, ancienne)

        ancienne.refresh_from_db()
        assert ancienne.actif is False
        assert "fusionnée dans Mairie - Châteauneuf-du-Faou" in ancienne.nom

    def test_la_zone_de_labsorbee_nest_pas_refabriquee(self, paire):
        """`Institution.save()` appelle `_assurer_zone_mon_territoire`, qui recrée la zone.
        Enregistrer l'absorbée par `save()` lui en rendrait donc une aussitôt — et comme
        `Zone.institution` est en PROTECT, cette zone fantôme interdirait ensuite toute
        suppression définitive de l'enregistrement."""
        nouvelle, ancienne = paire
        avant = Zone.objects.filter(institution=ancienne).count()

        _fusionner(nouvelle, ancienne)

        assert Zone.objects.filter(institution=ancienne).count() == avant

    def test_relancer_la_fusion_ne_casse_rien(self, paire):
        """Une commande de maintenance se relance : après un doute, un Ctrl-C, ou une seconde
        lecture du plan."""
        nouvelle, ancienne = paire
        compte = _compte("agent@exemple.bzh", "DELAPORTE", institution=ancienne)
        Team.objects.create(name="Cellule de crise", institution=ancienne)

        _fusionner(nouvelle, ancienne)
        _fusionner(nouvelle, ancienne)

        compte.refresh_from_db()
        ancienne.refresh_from_db()
        assert compte.institution_id == nouvelle.pk
        assert Team.objects.get(name="Cellule de crise").institution_id == nouvelle.pk
        assert ancienne.nom.count("fusionnée dans") == 1
