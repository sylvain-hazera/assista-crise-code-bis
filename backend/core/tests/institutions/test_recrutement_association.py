"""Circuit de recrutement d'une association agréée de sécurité civile.

Les quatre étapes telles que l'association les pratique — demande reçue, prise en charge,
pièces et qualifications vérifiées, accepté — plus le refus, car un recrutement peut aussi se
conclure par un non et l'omettre obligerait à laisser des dossiers ouverts indéfiniment.

Ce que ces tests tiennent, dans l'ordre d'importance :

1. **Accepter fait tout d'un geste** : compte activé, rattachement posé, équipe rejointe,
   niveau opérationnel fixé. Demander au bureau de valider deux fois la même personne dans deux
   écrans produit des comptes acceptés mais non rattachés — c'est exactement ce qui a coûté un
   utilisateur le 27/10/2026.
2. **Un lien d'invitation n'accorde rien** : il pose une candidature. Qui devinerait un jeton
   obtiendrait une demande de plus à examiner, pas un accès.
3. **Recruter est un acte de gouvernance** : le bureau, pas les membres.
4. **Le circuit avance, il ne recule pas**, et une décision prise ne se reprend pas — accepter
   a ouvert des accès, les retirer est un autre acte (ContactInstitution.statut « Sorti »).
"""
import datetime

import pytest
from django.utils import timezone

from core.models import (
    AffectationRoleOperationnel, CandidatureAssociation, ContactInstitution, Institution,
    InstitutionType, InvitationAssociation, Team, UserRole,
)
from core.recrutement_association import (
    accepter, candidature_depuis_invitation, demander_a_rejoindre, marquer_verifiee,
    peut_instruire, prendre_en_charge, refuser,
)

Etape = CandidatureAssociation.Etape


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    institution, _ = Institution.objects.get_or_create(
        nom="AASC Recrutement Test", defaults={"type": itype, "actif": True})
    return institution


@pytest.fixture
def bureau(create_user, aasc):
    user = create_user(username="bureau-rec@test.fr", email="bureau-rec@test.fr",
                       type=UserRole.LOCAL_AUTHORITY, last_name="PRESIDENTE")
    ContactInstitution.objects.create(
        institution=aasc, utilisateur=user, fonction="Présidente",
        membre_bureau=True, actif=True)
    return user


@pytest.fixture
def membre_simple(create_user, aasc):
    user = create_user(username="simple-rec@test.fr", email="simple-rec@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name="EQUIPIER")
    ContactInstitution.objects.create(
        institution=aasc, utilisateur=user, fonction="Équipier", actif=True)
    return user


@pytest.fixture
def candidat(create_user):
    """Compte créé mais pas encore activé : c'est l'état d'un nouvel inscrit."""
    user = create_user(username="candidat@test.fr", email="candidat@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name="CANDIDAT",
                       enabled=False, is_active=False)
    return user


class TestQuiPeutInstruire:
    def test_le_bureau_peut(self, bureau, aasc):
        assert peut_instruire(bureau, aasc) is True

    def test_un_membre_simple_ne_peut_pas(self, membre_simple, aasc):
        """Recruter est un acte de gouvernance, pas une prérogative de membre."""
        assert peut_instruire(membre_simple, aasc) is False

    def test_un_administrateur_peut(self, create_user, aasc):
        """Pour débloquer une association dont le bureau a perdu ses accès — pas parce que
        c'est son rôle habituel."""
        admin = create_user(username="admin-rec@test.fr", email="admin-rec@test.fr",
                            type=UserRole.ADMINISTRATOR, last_name="ADMIN")
        assert peut_instruire(admin, aasc) is True

    def test_le_bureau_dune_autre_association_ne_peut_pas(self, bureau, db):
        itype, _ = InstitutionType.objects.get_or_create(
            code="aasc", defaults={"libelle": "AASC"})
        autre, _ = Institution.objects.get_or_create(
            nom="AASC Voisine", defaults={"type": itype, "actif": True})

        assert peut_instruire(bureau, autre) is False

    def test_un_contact_desactive_ne_peut_plus(self, bureau, aasc):
        ContactInstitution.objects.filter(institution=aasc, utilisateur=bureau).update(
            actif=False)

        assert peut_instruire(bureau, aasc) is False


class TestDemandeDeRejoindre:
    def test_une_demande_cree_un_dossier_a_la_premiere_etape(self, aasc, candidat):
        candidature, creee = demander_a_rejoindre(aasc, candidat, message="Je veux aider.")

        assert creee is True
        assert candidature.etape == Etape.DEMANDE
        assert candidature.message_candidat == "Je veux aider."
        assert candidature.pris_en_charge_par_id is None

    def test_redemander_ne_cree_pas_un_second_dossier(self, aasc, candidat):
        """Deux dossiers ouverts se feraient instruire deux fois, et accepter deux fois."""
        premier, _ = demander_a_rejoindre(aasc, candidat)
        second, creee = demander_a_rejoindre(aasc, candidat)

        assert creee is False
        assert second.pk == premier.pk
        assert CandidatureAssociation.objects.filter(utilisateur=candidat).count() == 1

    def test_apres_un_refus_on_peut_redeposer(self, aasc, candidat, bureau):
        """Un refus n'est pas une interdiction à vie."""
        premier, _ = demander_a_rejoindre(aasc, candidat)
        refuser(premier, bureau, "Dossier incomplet, à revoir.")

        second, creee = demander_a_rejoindre(aasc, candidat)

        assert creee is True
        assert second.pk != premier.pk

    def test_une_demande_apres_acceptation_rend_le_dossier_existant(
            self, aasc, candidat, bureau):
        """La personne est déjà membre : lui ouvrir un nouveau dossier serait absurde."""
        premier, _ = demander_a_rejoindre(aasc, candidat)
        accepter(premier, bureau)

        second, creee = demander_a_rejoindre(aasc, candidat)

        assert creee is False
        assert second.pk == premier.pk


class TestLienDInvitation:
    @pytest.fixture
    def invitation(self, aasc, bureau):
        return InvitationAssociation.objects.create(
            institution=aasc, cree_par=bureau, libelle="Forum des associations 2026")

    def test_le_lien_pose_une_candidature_sans_rien_accorder(
            self, invitation, candidat, aasc):
        """LE point. Un jeton deviné donne une demande de plus à examiner, pas un accès."""
        candidature, creee = candidature_depuis_invitation(invitation.jeton, candidat)

        assert creee is True
        assert candidature.etape == Etape.DEMANDE
        assert candidature.invitation_id == invitation.pk
        candidat.refresh_from_db()
        assert candidat.institution_id is None
        assert candidat.is_active is False
        assert not ContactInstitution.objects.filter(
            institution=aasc, utilisateur=candidat).exists()

    def test_le_jeton_est_imprevisible(self, invitation, aasc, bureau):
        autre = InvitationAssociation.objects.create(institution=aasc, cree_par=bureau)

        assert invitation.jeton != autre.jeton
        assert len(invitation.jeton) >= 32

    def test_un_jeton_inconnu_ne_fait_rien(self, candidat):
        candidature, creee = candidature_depuis_invitation("jeton-invente", candidat)

        assert candidature is None
        assert creee is False

    def test_un_lien_expire_ne_fait_rien(self, invitation, candidat):
        """Un lien qui traîne sur un site public finit par être partagé n'importe où."""
        invitation.date_expiration = timezone.localdate() - datetime.timedelta(days=1)
        invitation.save(update_fields=["date_expiration"])

        candidature, _ = candidature_depuis_invitation(invitation.jeton, candidat)

        assert candidature is None

    def test_un_lien_desactive_ne_fait_rien(self, invitation, candidat):
        invitation.actif = False
        invitation.save(update_fields=["actif"])

        assert candidature_depuis_invitation(invitation.jeton, candidat)[0] is None

    def test_un_lien_dune_association_retiree_ne_fait_rien(self, invitation, candidat, aasc):
        aasc.actif = False
        aasc.save(update_fields=["actif"])

        assert candidature_depuis_invitation(invitation.jeton, candidat)[0] is None

    def test_lorigine_de_la_candidature_reste_lisible(self, invitation, candidat):
        """Savoir quelle action de recrutement a porté : c'est l'intérêt de nommer un lien."""
        candidature, _ = candidature_depuis_invitation(invitation.jeton, candidat)

        assert candidature.invitation.libelle == "Forum des associations 2026"


class TestInstruction:
    def test_la_prise_en_charge_nomme_son_instructeur(self, aasc, candidat, bureau):
        """Une candidature dont personne ne se sent responsable est une candidature qui dort."""
        candidature, _ = demander_a_rejoindre(aasc, candidat)

        prendre_en_charge(candidature, bureau)

        candidature.refresh_from_db()
        assert candidature.etape == Etape.PRISE_EN_CHARGE
        assert candidature.pris_en_charge_par_id == bureau.pk
        assert candidature.date_prise_en_charge is not None

    def test_un_membre_simple_ne_peut_pas_instruire(self, aasc, candidat, membre_simple):
        candidature, _ = demander_a_rejoindre(aasc, candidat)

        with pytest.raises(PermissionError):
            prendre_en_charge(candidature, membre_simple)

        candidature.refresh_from_db()
        assert candidature.etape == Etape.DEMANDE

    def test_le_circuit_peut_sauter_des_etapes(self, aasc, candidat, bureau):
        """Un bureau qui connaît la personne ne doit pas être forcé de cliquer trois fois pour
        dire oui."""
        candidature, _ = demander_a_rejoindre(aasc, candidat)

        accepter(candidature, bureau)

        candidature.refresh_from_db()
        assert candidature.etape == Etape.ACCEPTE

    def test_le_circuit_ne_recule_pas(self, aasc, candidat, bureau):
        """Une étape franchie l'a été par quelqu'un : la défranchir sans trace réécrirait
        l'instruction du dossier."""
        candidature, _ = demander_a_rejoindre(aasc, candidat)
        marquer_verifiee(candidature, bureau)

        with pytest.raises(ValueError):
            prendre_en_charge(candidature, bureau)

    def test_une_decision_prise_ne_se_reprend_pas(self, aasc, candidat, bureau):
        """Accepter a posé un rattachement et ouvert des accès : les retirer est un autre acte
        (ContactInstitution.statut « Sorti »), pas un retour en arrière du recrutement."""
        candidature, _ = demander_a_rejoindre(aasc, candidat)
        accepter(candidature, bureau)

        with pytest.raises(ValueError):
            refuser(candidature, bureau, "Changement d'avis.")


class TestAcceptation:
    """Accepter fait TOUT d'un geste. Deux validations dans deux écrans produisent des comptes
    acceptés mais non rattachés — ce qui a coûté un utilisateur le 27/10/2026."""

    @pytest.fixture
    def accepte(self, aasc, candidat, bureau):
        candidature, _ = demander_a_rejoindre(aasc, candidat)
        return accepter(candidature, bureau)

    def test_le_compte_est_active(self, accepte, candidat):
        candidat.refresh_from_db()
        assert candidat.enabled is True
        assert candidat.is_active is True

    def test_le_rattachement_est_pose(self, accepte, candidat, aasc):
        contact = ContactInstitution.objects.get(institution=aasc, utilisateur=candidat)
        assert contact.actif is True
        assert contact.fonction == "Membre"
        assert contact.membre_bureau is False
        assert contact.date_adhesion == timezone.localdate()

    def test_le_raccourci_user_institution_est_pose(self, accepte, candidat, aasc):
        """C'est lui que lisent les vues territoriales : l'oublier rend la personne aveugle à
        une partie de l'application sans aucun message."""
        candidat.refresh_from_db()
        assert candidat.institution_id == aasc.pk

    def test_la_personne_rejoint_lequipe_de_lassociation(self, accepte, candidat, aasc):
        assert Team.objects.filter(institution=aasc, members=candidat).exists()

    def test_son_niveau_est_intervenant(self, accepte, candidat, aasc):
        """Pas régulateur de crise : c'est au bureau d'élever ce niveau quand la personne est
        formée."""
        roles = AffectationRoleOperationnel.objects.filter(
            utilisateur=candidat, institution=aasc)
        assert [r.role.code for r in roles] == ["INTERVENANT"]

    def test_lacces_a_la_demonstration_est_ouvert(self, accepte, candidat):
        candidat.refresh_from_db()
        assert candidat.demo_role == candidat.type

    def test_la_decision_est_datee_et_signee(self, accepte, bureau):
        assert accepte.date_decision is not None
        assert accepte.pris_en_charge_par_id == bureau.pk


class TestRefus:
    def test_le_motif_est_obligatoire(self, aasc, candidat, bureau):
        """Un refus sans raison se represente à l'identique six mois plus tard, et personne ne
        sait pourquoi la personne avait été écartée."""
        candidature, _ = demander_a_rejoindre(aasc, candidat)

        with pytest.raises(ValueError, match="motif"):
            refuser(candidature, bureau, "   ")

        candidature.refresh_from_db()
        assert candidature.etape == Etape.DEMANDE

    def test_un_refus_motive_cloture_le_dossier(self, aasc, candidat, bureau):
        candidature, _ = demander_a_rejoindre(aasc, candidat)

        refuser(candidature, bureau, "Hors zone d'intervention de l'association.")

        candidature.refresh_from_db()
        assert candidature.etape == Etape.REFUSE
        assert "Hors zone" in candidature.motif_refus
        assert candidature.date_decision is not None

    def test_un_refus_naccorde_rien(self, aasc, candidat, bureau):
        candidature, _ = demander_a_rejoindre(aasc, candidat)

        refuser(candidature, bureau, "Dossier incomplet.")

        candidat.refresh_from_db()
        assert candidat.institution_id is None
        assert candidat.is_active is False
        assert not ContactInstitution.objects.filter(
            institution=aasc, utilisateur=candidat).exists()
