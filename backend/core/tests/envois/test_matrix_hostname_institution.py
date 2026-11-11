"""Adresse de serveur Matrix propre à une institution, dans le mail d'enrôlement Element X.

Ce que ces tests verrouillent, et qui est la correction d'une erreur d'analyse du 11/11/2026 :
les deux usages de `MATRIX_SERVER_NAME` étaient confondus.

1. **Construire l'identité** (`core/matrix.py:matrix_user_id`) : intouchable. Synapse n'a qu'un
   seul `server_name`, inscrit dans chaque identifiant d'utilisateur et de salon, et il ne sait
   pas en héberger deux. Le changer casserait toutes les identités et tous les salons.
2. **Indiquer l'adresse à saisir dans Element X** : personnalisable. Le proxy sert déjà
   `matrix.reserve-resilience.org` vers le même Synapse, avec son propre certificat.

Confondre les deux faisait croire que rien n'était personnalisable. Le test
`test_l_identifiant_matrix_ne_change_PAS` est le garde qui empêche la correction d'aller trop
loin.
"""
import pytest
from django.core import mail

from core.institution_attachment import _envoyer_email_acces_messagerie_equipe
from core.matrix import MATRIX_SERVER_NAME, matrix_user_id
from core.models import Institution, InstitutionType, Team


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_MX',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom="Association Matrix Test", type=itype,
                                      nom_affichage="Reserve Matrix")


@pytest.fixture
def equipe(institution):
    return Team.objects.create(name="Coordination Départementale Essai",
                               institution=institution)


@pytest.fixture
def requete(rf, create_user):
    from django.contrib.auth.models import AnonymousUser

    requete = rf.post('/api/x/')
    # Anonyme : le message part directement au lieu d'être retenu pour relecture — ce test
    # porte sur son CONTENU, pas sur le circuit de relecture.
    requete.user = AnonymousUser()
    return requete


@pytest.fixture
def membre(create_user):
    return create_user(username='mx@test.fr', email='mx@test.fr', first_name='Jean',
                       last_name='Dupont')


@pytest.mark.django_db
class TestAdresseDansLeMail:

    def test_sans_domaine_propre_l_adresse_partagee_est_indiquee(self, requete, equipe,
                                                                 membre):
        _envoyer_email_acces_messagerie_equipe(membre, equipe, requete)
        assert len(mail.outbox) == 1
        assert MATRIX_SERVER_NAME in mail.outbox[0].body

    def test_avec_un_domaine_propre_c_est_lui_qui_est_indique(self, requete, institution,
                                                              equipe, membre):
        """Le bénévole saisit l'adresse de SON association. Le proxy la route vers le même
        Synapse — rien de plus n'est nécessaire côté serveur."""
        institution.matrix_hostname = "matrix.reserve-matrix.invalide"
        institution.save(update_fields=['matrix_hostname'])

        _envoyer_email_acces_messagerie_equipe(membre, equipe, requete)
        corps = mail.outbox[0].body
        assert "matrix.reserve-matrix.invalide" in corps
        # Et l'adresse partagée n'apparaît plus : c'était la fuite de marque à fermer.
        assert MATRIX_SERVER_NAME not in corps

    def test_le_nom_de_l_institution_est_dans_le_mail(self, requete, institution, equipe,
                                                      membre):
        _envoyer_email_acces_messagerie_equipe(membre, equipe, requete)
        assert "Reserve Matrix" in mail.outbox[0].body


@pytest.mark.django_db
class TestLIdentiteResteInchangee:

    def test_l_identifiant_matrix_ne_change_PAS(self, institution, membre):
        """LE GARDE DE CETTE CORRECTION. L'identifiant d'un compte Matrix est formé sur le
        `server_name` de Synapse, unique et partagé. Le faire dépendre de l'institution
        produirait des identifiants qui ne correspondent à aucun serveur — les comptes
        deviendraient injoignables et les salons existants inconsistants."""
        institution.matrix_hostname = "matrix.reserve-matrix.invalide"
        institution.save(update_fields=['matrix_hostname'])
        membre.institution = institution
        membre.save(update_fields=['institution'])

        identifiant = matrix_user_id(membre)
        assert identifiant.endswith(f":{MATRIX_SERVER_NAME}")
        assert "reserve-matrix.invalide" not in identifiant
