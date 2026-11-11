"""Import de bénévoles d'association : type de compte, équipe départementale, promotion.

L'arbitrage central du 11/11/2026 : **un bénévole n'est pas un agent**. L'import de personnel
communal créait des comptes `AUT_LOCALE` avec le rôle REFERENT et l'accès à la zone de
démonstration — c'est-à-dire qu'il faisait d'un adhérent un acteur institutionnel pour exprimer
« il est membre de l'association ». Trois choses différentes étaient dites dans un seul champ
global.

La séparation retenue :

| ce qu'on veut dire | où ça vit |
|---|---|
| ce que je peux faire sur la PLATEFORME | `User.type` |
| à quelle association j'appartiens | `ContactInstitution` |
| où j'interviens | l'équipe départementale |
| mon niveau dans l'association | `Team.membres_encadrement` |
"""
import pytest
from django.core import mail

from core.imports import importer_benevoles_association
from core.models import (
    ContactInstitution, EchelonEquipe, Institution, InstitutionType, Team, User, UserRole,
)

MAPPING = {"prenom": "PRENOM", "nom": "NOM", "email": "EMAIL", "telephone": "SMS",
           "code_postal": "CODE_POSTAL", "metier": "METIERS_FORMATIONS"}


def ligne(email, nom="Dupont", prenom="Jean", cp="33950", metier="Assureur", tel="33600000000"):
    return {"EMAIL": email, "NOM": nom, "PRENOM": prenom, "CODE_POSTAL": cp,
            "METIERS_FORMATIONS": metier, "SMS": tel}


@pytest.fixture
def asso(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_IMP',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom="Association Import", type=itype)


@pytest.fixture
def equipes(asso):
    gironde = Team.objects.create(name="Gironde", institution=asso,
                                  echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="33")
    savoie = Team.objects.create(name="Haute-Savoie", institution=asso,
                                 echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="74")
    return gironde, savoie


@pytest.fixture
def requete(rf, create_user):
    from django.contrib.auth.models import AnonymousUser

    r = rf.post('/api/x/')
    r.user = AnonymousUser()
    return r


@pytest.mark.django_db
class TestTypeDeCompte:

    def test_un_benevole_est_UTIL_SIMPLE_et_non_acteur_institutionnel(self, requete, asso,
                                                                      equipes):
        """L'arbitrage central. `AUT_LOCALE` passe `IsInstitutionalActor` et ouvre une grande
        partie de la plateforme : le donner à deux mille adhérents confondrait ce qu'on peut
        faire sur la PLATEFORME avec ce qu'on est dans l'ASSOCIATION."""
        importer_benevoles_association(requete, asso, [ligne("b1@essai.invalide")], MAPPING)

        u = User.objects.get(username="b1@essai.invalide")
        assert u.type == UserRole.SIMPLE_USER
        assert u.is_active is False  # en attente d'activation par son lien magique

    def test_aucun_role_operationnel_n_est_pose(self, requete, asso, equipes):
        """L'import de personnel posait REFERENT, un niveau de responsabilité, à tout le
        monde."""
        from core.models import AffectationRoleOperationnel

        importer_benevoles_association(requete, asso, [ligne("b2@essai.invalide")], MAPPING)
        u = User.objects.get(username="b2@essai.invalide")
        assert not AffectationRoleOperationnel.objects.filter(utilisateur=u).exists()

    def test_aucun_acces_a_la_zone_de_demonstration(self, requete, asso, equipes):
        importer_benevoles_association(requete, asso, [ligne("b3@essai.invalide")], MAPPING)
        assert not User.objects.get(username="b3@essai.invalide").demo_role

    def test_un_compte_deja_institutionnel_n_est_JAMAIS_retrograde(self, requete, asso,
                                                                    equipes, create_user):
        """Un agent de mairie peut aussi être bénévole : l'import ne doit pas lui retirer ses
        accès professionnels."""
        agent = create_user(username="agent@essai.invalide", email="agent@essai.invalide",
                            type='AUT_LOCALE')
        importer_benevoles_association(requete, asso, [ligne("agent@essai.invalide")], MAPPING)
        agent.refresh_from_db()
        assert agent.type == 'AUT_LOCALE'


@pytest.mark.django_db
class TestEquipeDepartementale:

    def test_le_benevole_rejoint_l_equipe_de_son_departement(self, requete, asso, equipes):
        gironde, savoie = equipes
        importer_benevoles_association(
            requete, asso,
            [ligne("g@essai.invalide", cp="33950"), ligne("s@essai.invalide", cp="74600")],
            MAPPING)

        assert gironde.members.filter(username="g@essai.invalide").exists()
        assert savoie.members.filter(username="s@essai.invalide").exists()
        assert not gironde.members.filter(username="s@essai.invalide").exists()

    def test_le_zero_initial_supprime_par_excel_est_rattrape(self, requete, asso):
        """Un tableur rend « 1000 » pour « 01000 » (Ain). Refuser ferait échouer tout un
        département pour une particularité d'Excel."""
        ain = Team.objects.create(name="Ain", institution=asso,
                                  echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="01")
        importer_benevoles_association(requete, asso, [ligne("a@essai.invalide", cp="1000")],
                                       MAPPING)
        assert ain.members.filter(username="a@essai.invalide").exists()

    def test_un_departement_indeterminable_cree_le_compte_mais_le_signale(self, requete, asso,
                                                                          equipes):
        """La Corse partage le préfixe 20 entre 2A et 2B. Refuser la ligne entière punirait le
        bénévole d'une imprécision de fichier : le compte existe, c'est son rattachement
        territorial qui attend."""
        bilan = importer_benevoles_association(
            requete, asso, [ligne("corse@essai.invalide", cp="20000")], MAPPING)

        assert User.objects.filter(username="corse@essai.invalide").exists()
        assert bilan["sans_equipe"] == 1
        assert "Corse" in bilan["erreurs"][0]["message"]

    def test_un_departement_sans_equipe_est_signale(self, requete, asso, equipes):
        """Code postal valide, mais l'association n'a pas d'équipe pour ce département."""
        bilan = importer_benevoles_association(
            requete, asso, [ligne("x@essai.invalide", cp="87000")], MAPPING)
        assert bilan["sans_equipe"] == 1


@pytest.mark.django_db
class TestAppartenanceEtInvitation:

    def test_le_rattachement_a_l_association_est_pose(self, requete, asso, equipes):
        importer_benevoles_association(requete, asso, [ligne("c@essai.invalide")], MAPPING)
        contact = ContactInstitution.objects.get(utilisateur__username="c@essai.invalide")
        assert contact.institution == asso
        assert contact.actif is True
        assert contact.membre_bureau is False
        # Le métier déclaré est l'information la plus utile à côté du nom dans la liste.
        assert contact.fonction == "Assureur"

    def test_sans_metier_la_fonction_vaut_Benevole(self, requete, asso, equipes):
        importer_benevoles_association(requete, asso,
                                       [ligne("d@essai.invalide", metier="")], MAPPING)
        assert ContactInstitution.objects.get(
            utilisateur__username="d@essai.invalide").fonction == "Bénévole"

    def test_le_mail_d_activation_part(self, requete, asso, equipes):
        importer_benevoles_association(requete, asso, [ligne("e@essai.invalide")], MAPPING)
        assert len(mail.outbox) == 1
        assert "e@essai.invalide" in mail.outbox[0].to

    def test_sans_invitation_aucun_mail(self, requete, asso, equipes):
        importer_benevoles_association(requete, asso, [ligne("f@essai.invalide")], MAPPING,
                                       inviter=False)
        assert len(mail.outbox) == 0

    def test_une_ligne_sans_email_est_signalee_sans_arreter_l_import(self, requete, asso,
                                                                      equipes):
        bilan = importer_benevoles_association(
            requete, asso,
            [ligne("", nom="SansMail"), ligne("ok@essai.invalide")], MAPPING)
        assert bilan["crees"] == 1
        assert any("obligatoires" in e["message"] for e in bilan["erreurs"])

    def test_reimporter_le_meme_fichier_est_sans_risque(self, requete, asso, equipes):
        importer_benevoles_association(requete, asso, [ligne("r@essai.invalide")], MAPPING)
        bilan = importer_benevoles_association(requete, asso, [ligne("r@essai.invalide")],
                                               MAPPING)
        assert bilan["crees"] == 0 and bilan["rattaches"] == 1
        assert User.objects.filter(username="r@essai.invalide").count() == 1


@pytest.mark.django_db
class TestPromotionALEncadrement:
    """Un bénévole est UTIL_SIMPLE ; encadrer, c'est gérer les autres, donc il faut l'accès
    institutionnel. La promotion suit la désignation plutôt que de demander un second geste
    dans un autre écran, qui serait oublié une fois sur deux.

    **Jamais de rétrogradation en sens inverse** : retirer quelqu'un de l'encadrement ne lui
    retire pas son type de compte. Il peut l'avoir pour une autre raison — membre du bureau,
    agent d'une mairie — et une rétrogradation automatique le priverait d'accès sans que
    personne ne l'ait décidé."""

    @pytest.fixture
    def client_bureau(self, create_user, asso):
        from rest_framework.test import APIClient

        u = create_user(username='bureau-promo@test.fr', email='bureau-promo@test.fr',
                        type='SECOURS', institution=asso)
        ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True,
                                          membre_bureau=True)
        client = APIClient()
        client.force_authenticate(user=u)
        return client

    def test_designer_un_benevole_comme_encadrement_le_promeut(self, client_bureau, requete,
                                                                asso, equipes):
        from django.urls import reverse

        gironde, _ = equipes
        importer_benevoles_association(requete, asso, [ligne("promu@essai.invalide")], MAPPING)
        benevole = User.objects.get(username="promu@essai.invalide")
        assert benevole.type == UserRole.SIMPLE_USER

        reponse = client_bureau.post(
            reverse('team-definir-encadrement', args=[gironde.id]),
            {'membres_encadrement': [str(benevole.id)]}, format='json')
        assert reponse.status_code == 200, reponse.data

        benevole.refresh_from_db()
        assert benevole.type == UserRole.ORGANIZED_RESCUE

    def test_la_promotion_est_tracee_en_main_courante(self, client_bureau, requete, asso,
                                                       equipes):
        from django.urls import reverse

        from core.models import AuditLog

        gironde, _ = equipes
        importer_benevoles_association(requete, asso, [ligne("trace@essai.invalide")], MAPPING)
        benevole = User.objects.get(username="trace@essai.invalide")

        client_bureau.post(reverse('team-definir-encadrement', args=[gironde.id]),
                           {'membres_encadrement': [str(benevole.id)]}, format='json')

        lignes = AuditLog.objects.filter(objet_type="User", objet_id=benevole.id)
        assert any("promu" in (l.commentaire or '') for l in lignes)

    def test_retirer_de_l_encadrement_NE_retrograde_PAS(self, client_bureau, requete, asso,
                                                         equipes):
        from django.urls import reverse

        gironde, _ = equipes
        importer_benevoles_association(requete, asso, [ligne("garde@essai.invalide")], MAPPING)
        benevole = User.objects.get(username="garde@essai.invalide")
        url = reverse('team-definir-encadrement', args=[gironde.id])

        client_bureau.post(url, {'membres_encadrement': [str(benevole.id)]}, format='json')
        client_bureau.post(url, {'membres_encadrement': []}, format='json')

        benevole.refresh_from_db()
        assert benevole.type == UserRole.ORGANIZED_RESCUE, (
            "la rétrogradation automatique priverait d'accès quelqu'un qui peut en avoir "
            "besoin pour une autre raison"
        )

    def test_un_compte_deja_institutionnel_n_est_pas_touche(self, client_bureau, asso,
                                                             equipes, create_user):
        from django.urls import reverse

        gironde, _ = equipes
        agent = create_user(username='agent-promo@test.fr', email='agent-promo@test.fr',
                            type='AUT_LOCALE')
        gironde.members.add(agent)

        client_bureau.post(reverse('team-definir-encadrement', args=[gironde.id]),
                           {'membres_encadrement': [str(agent.id)]}, format='json')
        agent.refresh_from_db()
        assert agent.type == 'AUT_LOCALE'
