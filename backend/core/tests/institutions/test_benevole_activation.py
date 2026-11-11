"""Enrôlement d'un bénévole importé : le drapeau qui lui ouvre sa fiche, et son mail.

Deux choses se jouent ici, et aucune des deux n'est vérifiable depuis le navigateur :

1. **`est_benevole_association`**, qui décide de l'entrée « Ma fiche de bénévole » du menu. Il
   répond à « cette personne est-elle adhérente d'une association ? », ce qui n'est PAS la même
   question que `acces_membres_association` (« qui administre des membres ?»). Un administrateur
   est vrai pour la seconde et faux pour la première : lui proposer de compléter une fiche
   d'adhérent n'aurait pas de sens.
2. **le mail d'activation**, qui doit emmener sur la fiche. Un bénévole qui atterrit sur
   l'accueil ne saura jamais qu'une fiche l'attendait — c'est tout l'objet du `next`.
"""
import pytest

from core.models import ContactInstitution, Institution, InstitutionType, UserRole
from core.serializers import UserSerializer


@pytest.fixture
def type_aasc_benevole(db):
    return InstitutionType.objects.create(code="AASC", libelle="Association agréée")


@pytest.fixture
def type_mairie_benevole(db):
    return InstitutionType.objects.create(code="MAIRIE_BENEV_TEST", libelle="Mairie")


@pytest.fixture
def association(db, type_aasc_benevole):
    return Institution.objects.create(nom="Reserve essai benevole", type=type_aasc_benevole)


def _est_benevole(user):
    return UserSerializer(user).data["est_benevole_association"]


@pytest.mark.django_db
class TestEstBenevoleAssociation:

    def test_un_rattachement_actif_a_une_aasc_suffit(self, create_user, association):
        """Le critère est le rattachement, pas le type de compte : un bénévole reste
        UTIL_SIMPLE jusqu'à ce qu'on le désigne encadrant."""
        user = create_user(username="b1@essai.invalide", email="b1@essai.invalide",
                           type=UserRole.SIMPLE_USER)
        ContactInstitution.objects.create(institution=association, utilisateur=user,
                                          actif=True)

        assert _est_benevole(user) is True

    def test_un_rattachement_desactive_ne_compte_pas(self, create_user, association):
        """Un membre sorti perd ses accès : lui laisser la fiche serait lui laisser une porte
        sur l'association qu'il a quittée."""
        user = create_user(username="b2@essai.invalide", email="b2@essai.invalide",
                           type=UserRole.SIMPLE_USER)
        ContactInstitution.objects.create(institution=association, utilisateur=user,
                                          actif=False)

        assert _est_benevole(user) is False

    def test_un_rattachement_a_une_mairie_ne_compte_pas(self, create_user,
                                                        type_mairie_benevole):
        mairie = Institution.objects.create(nom="Mairie essai benevole",
                                            type=type_mairie_benevole, commune_code="29026")
        user = create_user(username="b3@essai.invalide", email="b3@essai.invalide",
                           type=UserRole.LOCAL_AUTHORITY)
        ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)

        assert _est_benevole(user) is False

    def test_un_administrateur_sans_rattachement_est_faux(self, create_user):
        """La distinction d'avec `acces_membres_association`, qui est vrai pour lui : il
        administre des membres, il n'est bénévole de personne."""
        admin = create_user(username="adm@essai.invalide", email="adm@essai.invalide",
                            type=UserRole.ADMINISTRATOR)

        donnees = UserSerializer(admin).data
        assert donnees["est_benevole_association"] is False
        assert donnees["acces_membres_association"] is True


@pytest.mark.django_db
class TestMailActivationBenevole:

    def test_le_lien_emmene_sur_la_fiche_a_completer(self, rf, create_user, association,
                                                     mailoutbox):
        """Le `next` est ce qui distingue cet envoi de celui des comptes institutionnels : sans
        lui, la personne atterrit sur l'accueil et la fiche reste vide."""
        from core.views import send_benevole_account_email

        benevole = create_user(username="b4@essai.invalide", email="b4@essai.invalide",
                               first_name="Marie", type=UserRole.SIMPLE_USER)
        requete = rf.post("/api/imports/benevoles/")
        requete.user = benevole

        send_benevole_account_email(requete, benevole, association)

        assert len(mailoutbox) == 1
        corps = mailoutbox[0].body
        assert "next=%2Fma-fiche-benevole" in corps
        # Le vocabulaire des comptes institutionnels ne doit PAS revenir ici : un bénévole des
        # Casques Jaunes n'y reconnaît rien de sa situation.
        assert "compte institutionnel" not in corps
        assert "justificatifs" in corps

    def test_la_marque_est_celle_de_l_institution_d_accueil(self, rf, create_user, association,
                                                            mailoutbox):
        """La marque est résolue depuis l'INSTITUTION passée en argument, et non depuis le Host
        de la requête d'import : c'est l'association qui écrit à ses membres, même si le membre
        du bureau lance l'import depuis un autre domaine.

        Hors marque blanche configurée, `get_mail_branding` rend « Assista-Crise » : ce test
        vérifie donc la PROVENANCE de la marque, pas un nom en particulier. Une institution
        avec son domaine (Réserve Résilience) y mettra le sien.
        """
        from core.branding import get_mail_branding
        from core.views import send_benevole_account_email

        benevole = create_user(username="b5@essai.invalide", email="b5@essai.invalide",
                               first_name="Paul", type=UserRole.SIMPLE_USER)
        # Un Host étranger à l'association : ce qui en sort ne doit rien devoir à ce domaine.
        requete = rf.post("/api/imports/benevoles/", HTTP_HOST="autre.invalide")
        requete.user = benevole

        send_benevole_account_email(requete, benevole, association)

        attendu = get_mail_branding(association)["nom_expediteur"]
        assert mailoutbox[0].to == ["b5@essai.invalide"]
        assert mailoutbox[0].subject == f"Votre accès bénévole {attendu}"
