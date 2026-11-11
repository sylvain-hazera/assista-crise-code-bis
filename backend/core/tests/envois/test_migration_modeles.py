"""Migration des envois vers le catalogue de modèles : le texte ne doit PAS changer.

Le risque de cette migration est unique et il est silencieux : remplacer un texte en dur par un
modèle dont le défaut diffère d'une virgule change le contenu d'un mail sans que rien ne le
signale. Les tests ci-dessous comparent donc le rendu du modèle au texte exact qui partait
avant, caractère par caractère.

C'est aussi ce qui permet de migrer les 48 points d'envoi **par lots** : chaque lot vient avec
sa comparaison, plutôt qu'un commit de 37 extractions de f-strings où la casse serait invisible.
"""
import pytest
from django.core import mail

from core.branding import send_modele_mail
from core.modeles_messages import CATALOGUE, rendre

#: Les clés déjà migrées. Une clé ajoutée ici sans sa comparaison ci-dessous fait échouer
#: `test_toute_cle_migree_est_comparee` : on ne migre pas sans vérifier.
CLES_MIGREES = {
    "COMPTE_VALIDE",
    "COMPTE_REFUSE",
    "COMPTE_EN_ATTENTE_VALIDATION",
    "MOT_DE_PASSE_OUBLIE",
}

#: Pour chaque clé migrée : les valeurs, et le texte EXACT qui partait avant la migration.
#: `[SIGNATURE]` vaut « Cordialement,\nL'équipe Assista-Crise » hors marque blanche, ce que
#: `{signature}` produisait déjà.
SIGNATURE = "Cordialement,\nL'équipe Assista-Crise"

COMPARAISONS = {
    "COMPTE_VALIDE": (
        {"PRENOM": "Jean", "NOM": "Dupont", "TYPE_COMPTE": "Secours organisés"},
        "Votre compte a été validé !",
        "Bonjour Jean Dupont,\n\n"
        "Bonne nouvelle ! Votre compte (Secours organisés) a été validé.\n"
        "Vous pouvez maintenant vous connecter et accéder à toutes les fonctionnalités.\n\n"
        + SIGNATURE,
    ),
    "COMPTE_REFUSE": (
        {"PRENOM": "Jean", "NOM": "Dupont", "TYPE_COMPTE": "Secours organisés",
         "MOTIF": "Commune hors périmètre"},
        "Votre demande de compte a été refusée",
        "Bonjour Jean Dupont,\n\n"
        "Nous sommes désolés de vous informer que votre demande de compte "
        "(Secours organisés) n'a pas été acceptée.\n\n"
        "Raison : Commune hors périmètre\n\n"
        "Pour plus d'informations, vous pouvez nous contacter.\n\n"
        + SIGNATURE,
    ),
    "COMPTE_EN_ATTENTE_VALIDATION": (
        {"PRENOM": "Jean", "NOM": "Dupont", "TYPE_COMPTE": "Secours organisés"},
        "Compte créé - En attente de validation",
        "Bonjour Jean Dupont,\n\n"
        "Votre compte (Secours organisés) sur Assista-Crise a bien été créé.\n"
        "Cependant, il est en attente de validation par un administrateur.\n"
        "Vous recevrez un email dès que votre compte sera validé.\n\n"
        + SIGNATURE,
    ),
    "MOT_DE_PASSE_OUBLIE": (
        {"PRENOM": "Jean", "NOM": "Dupont",
         "LIEN_REINITIALISATION": "https://exemple.invalide/reinit/MQ/MQ:sig"},
        "Réinitialisation de votre mot de passe Assista-Crise",
        "Bonjour Jean Dupont,\n\n"
        "Vous avez demandé la réinitialisation du mot de passe de votre compte "
        "Assista-Crise.\n\n"
        "Pour choisir un nouveau mot de passe, cliquez sur le lien suivant :\n"
        "https://exemple.invalide/reinit/MQ/MQ:sig\n\n"
        "Ce lien est valable 7 jours et ne peut être utilisé qu'une seule fois. Si vous "
        "n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet email : votre "
        "mot de passe actuel reste valable.\n\n"
        + SIGNATURE,
    ),
}


class TestLeTexteNAPasChange:

    def test_toute_cle_migree_est_comparee(self):
        """On ne migre pas un envoi sans comparer son texte au précédent."""
        assert CLES_MIGREES == set(COMPARAISONS), (
            "une clé migrée n'a pas de comparaison, ou l'inverse"
        )

    @pytest.mark.parametrize("cle", sorted(COMPARAISONS))
    def test_le_rendu_du_modele_est_identique_a_l_ancien_texte(self, cle):
        valeurs, sujet_attendu, corps_attendu = COMPARAISONS[cle]
        modele = CATALOGUE[cle]
        # Les valeurs que `send_modele_mail` fournit d'office, hors marque blanche.
        toutes = {"SIGNATURE": SIGNATURE, "INSTITUTION": "Assista-Crise", **valeurs}

        assert rendre(modele.sujet, toutes, pour_envoi=True) == sujet_attendu
        assert rendre(modele.corps, toutes, pour_envoi=True) == corps_attendu


@pytest.mark.django_db
class TestEnvoiParModele:

    @pytest.fixture
    def requete(self, rf, create_user):
        requete = rf.post('/api/x/')
        requete.user = create_user(username='mig@test.fr', email='mig@test.fr')
        return requete

    def test_sans_institution_le_defaut_part_tel_quel(self, requete):
        """Le cas le plus courant : pas de marque blanche, donc le texte d'origine."""
        valeurs, sujet, corps = COMPARAISONS["COMPTE_VALIDE"]
        send_modele_mail(requete, None, "COMPTE_VALIDE", valeurs,
                         recipient_list=["dest@essai.invalide"])

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == sujet
        assert mail.outbox[0].body == corps

    def test_une_cle_inconnue_rend_None_sans_envoyer(self, requete):
        """C'est ce qui permet à un appelant non migré de garder son texte en dur : la fonction
        dit « je ne sais pas » au lieu d'envoyer un message vide."""
        assert send_modele_mail(requete, None, "CLE_INEXISTANTE", {},
                                recipient_list=["dest@essai.invalide"]) is None
        assert len(mail.outbox) == 0

    def test_le_lien_est_bien_resolu_a_l_envoi(self, requete):
        """Rendu avec `pour_envoi=True` : sans cela le mail dirait « cliquez sur
        [LIEN_REINITIALISATION] »."""
        valeurs, _, _ = COMPARAISONS["MOT_DE_PASSE_OUBLIE"]
        send_modele_mail(requete, None, "MOT_DE_PASSE_OUBLIE", valeurs,
                         recipient_list=["dest@essai.invalide"])

        assert "https://exemple.invalide/reinit/MQ/MQ:sig" in mail.outbox[0].body
        assert "[LIEN_REINITIALISATION]" not in mail.outbox[0].body

    def test_le_texte_reecrit_par_l_institution_remplace_le_defaut(self, requete, db):
        from core.models import Institution, InstitutionType, ModeleMessage

        itype, _ = InstitutionType.objects.get_or_create(code='AASC_MIG',
                                                         defaults={'libelle': 'Association'})
        institution = Institution.objects.create(nom="Association Migration", type=itype,
                                                 nom_affichage="Reserve Migration")
        ModeleMessage.objects.create(
            institution=institution, cle="COMPTE_VALIDE",
            corps="Salut [PRENOM], c'est bon.\n\n[SIGNATURE]")

        send_modele_mail(requete, institution, "COMPTE_VALIDE",
                         {"PRENOM": "Jean", "NOM": "Dupont", "TYPE_COMPTE": "Bénévole"},
                         recipient_list=["dest@essai.invalide"])

        assert "Salut Jean, c'est bon." in mail.outbox[0].body
        assert "Reserve Migration" in mail.outbox[0].body
        # Le sujet n'a pas été réécrit : il retombe sur le défaut, sans qu'on ait eu à le
        # recopier.
        assert mail.outbox[0].subject == "Votre compte a été validé !"
