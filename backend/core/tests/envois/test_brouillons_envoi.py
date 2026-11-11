"""Fenêtre de relecture avant envoi : capture, masquage des liens, et envoi après relecture.

Demande du 11/11/2026. Ce que ces tests verrouillent :

1. **Aucun des 48 points d'envoi n'a changé.** La capture se fait dans `send_branded_mail` et la
   décision « faut-il relire ? » se déduit de la requête : un utilisateur authentifié, et aucun
   destinataire n'est son adresse → il écrit à un tiers. Les tests passent donc par
   `send_branded_mail`, jamais par une API de capture.
2. **Les liens magiques ne sortent jamais du serveur**, ni dans le brouillon stocké, ni dans la
   réponse d'API. Le cas qui le prouve : un administrateur déclenche une réinitialisation de mot
   de passe POUR QUELQU'UN D'AUTRE ; lui montrer le lien lui donnerait la main sur ce compte.
3. **Un accusé qu'on s'envoie à soi-même part directement.** Ouvrir un éditeur montrerait à
   quelqu'un le mail qu'il est en train de recevoir, avec son propre lien de connexion dedans.
4. **L'action a déjà eu lieu.** Abandonner un message ne la défait pas : d'où le motif
   obligatoire, pour qu'on sache plus tard pourquoi personne n'a été prévenu.
"""
import json

import pytest
from django.core import mail
from rest_framework.test import APIClient

from core.branding import send_branded_mail
from core.brouillons_envoi import masquer_les_liens
from core.models import (
    BrouillonEnvoi, ConfigurationEnvoiInstitution, ContactInstitution, Institution,
    InstitutionType,
)

LIEN = "https://exemple.invalide/activate-account/MQ/MQ:signature-secrete"


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_RELECTURE',
                                                     defaults={'libelle': 'Association'})
    inst = Institution.objects.create(nom="Association Relecture", type=itype,
                                      nom_affichage="Reserve Relecture")
    ConfigurationEnvoiInstitution.objects.create(institution=inst, relecture_avant_envoi=True)
    return inst


@pytest.fixture
def membre(create_user, institution):
    utilisateur = create_user(username='membre-relecture@test.fr',
                              email='membre-relecture@test.fr', type='SECOURS',
                              institution=institution)
    ContactInstitution.objects.create(institution=institution, utilisateur=utilisateur,
                                      actif=True)
    return utilisateur


def requete_de(rf, utilisateur, liens=()):
    requete = rf.post('/api/x/')
    requete.user = utilisateur
    if liens:
        requete._liens_magiques = list(liens)
    return requete


@pytest.mark.django_db
class TestQuandLaFenetreSOuvre:

    def test_un_message_vers_un_tiers_est_retenu(self, rf, institution, membre):
        requete = requete_de(rf, membre)
        send_branded_mail(requete, institution, "Compte validé",
                          "Bonjour\n\n{signature}", ["benevole@essai.invalide"])

        assert len(mail.outbox) == 0, "le message ne doit pas partir avant relecture"
        brouillon = BrouillonEnvoi.objects.get()
        assert brouillon.statut == BrouillonEnvoi.Statut.A_RELIRE
        assert brouillon.destinataires == ["benevole@essai.invalide"]
        # Le texte de l'institution est déjà appliqué : on relit ce qui partira.
        assert "Reserve Relecture" in brouillon.corps

    def test_le_brouillon_est_annonce_sur_la_requete(self, rf, institution, membre):
        """C'est ce qui permet à l'interface d'ouvrir la fenêtre sans qu'aucun des 25 endpoints
        concernés ne change de contrat : un middleware pose l'identifiant en en-tête."""
        requete = requete_de(rf, membre)
        send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                          ["autre@essai.invalide"])
        assert getattr(requete, '_brouillons_envoi', []) == [str(BrouillonEnvoi.objects.get().id)]

    def test_un_accuse_que_l_on_s_envoie_a_soi_meme_part_directement(self, rf, institution,
                                                                     membre):
        """Le destinataire est l'acteur : lui ouvrir un éditeur lui montrerait le mail qu'il est
        en train de recevoir."""
        requete = requete_de(rf, membre)
        send_branded_mail(requete, institution, "Votre demande", "Corps\n\n{signature}",
                          [membre.email])

        assert not BrouillonEnvoi.objects.exists()
        assert len(mail.outbox) == 1

    def test_une_inscription_part_directement(self, rf, institution):
        """`request.user` anonyme : personne n'est là pour relire."""
        from django.contrib.auth.models import AnonymousUser

        requete = rf.post('/api/register/')
        requete.user = AnonymousUser()
        send_branded_mail(requete, institution, "Activation", "Corps\n\n{signature}",
                          ["nouveau@essai.invalide"])

        assert not BrouillonEnvoi.objects.exists()
        assert len(mail.outbox) == 1

    def test_sans_requete_le_message_part_directement(self, institution):
        """Supervision, pont radio, alerte sismique : aucun humain par construction."""
        send_branded_mail(None, institution, "Alerte", "Corps\n\n{signature}",
                          ["admin@essai.invalide"])
        assert not BrouillonEnvoi.objects.exists()
        assert len(mail.outbox) == 1

    def test_sans_activation_rien_ne_change(self, rf, institution, membre):
        """Une institution qui n'active pas la relecture ne doit RIEN voir changer."""
        config = institution.configuration_envoi
        config.relecture_avant_envoi = False
        config.save(update_fields=['relecture_avant_envoi'])

        send_branded_mail(requete_de(rf, membre), institution, "Sujet",
                          "Corps\n\n{signature}", ["autre@essai.invalide"])
        assert not BrouillonEnvoi.objects.exists()
        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestLesLiensNeSortentJamais:

    def test_le_lien_est_masque_dans_le_brouillon_stocke(self, rf, institution, membre):
        requete = requete_de(rf, membre, liens=[LIEN])
        send_branded_mail(requete, institution, "Réinitialisation",
                          f"Cliquez : {LIEN}\n\n{{signature}}", ["autre@essai.invalide"])

        brouillon = BrouillonEnvoi.objects.get()
        assert LIEN not in brouillon.corps
        assert "signature-secrete" not in brouillon.corps
        assert "[LIEN_1]" in brouillon.corps
        # La correspondance est gardée, chiffrée, pour l'envoi.
        assert json.loads(brouillon.liens_masques) == {"[LIEN_1]": LIEN}

    def test_l_api_ne_rend_jamais_la_correspondance(self, institution, membre, rf):
        requete = requete_de(rf, membre, liens=[LIEN])
        send_branded_mail(requete, institution, "Réinitialisation",
                          f"Cliquez : {LIEN}\n\n{{signature}}", ["autre@essai.invalide"])

        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.get(f"/api/brouillons-envoi/{BrouillonEnvoi.objects.get().id}/")
        assert reponse.status_code == 200
        corps_reponse = str(reponse.data)
        assert "signature-secrete" not in corps_reponse
        assert "liens_masques" not in reponse.data
        assert "[LIEN_1]" in reponse.data['corps']

    def test_un_lien_prefixe_d_un_autre_est_masque_en_entier(self, rf, institution, membre):
        """Un lien peut être le préfixe d'un autre — le même, avec un `?next=`. Masquer le
        court d'abord laisserait un fragment d'URL réelle dans le texte."""
        court = LIEN
        long = f"{LIEN}?next=%2Fsuivi"
        requete = requete_de(rf, membre, liens=[court, long])
        send_branded_mail(requete, institution, "Deux liens",
                          f"A : {long}\nB : {court}\n\n{{signature}}", ["autre@essai.invalide"])

        brouillon = BrouillonEnvoi.objects.get()
        assert "exemple.invalide" not in brouillon.corps
        assert "signature-secrete" not in brouillon.corps

    def test_masquer_les_liens_est_sans_effet_sans_lien_declare(self):
        masque, correspondance = masquer_les_liens(None, "Texte sans lien")
        assert masque == "Texte sans lien"
        assert correspondance == {}


@pytest.mark.django_db
class TestEnvoiApresRelecture:

    @pytest.fixture
    def brouillon(self, rf, institution, membre):
        requete = requete_de(rf, membre, liens=[LIEN])
        send_branded_mail(requete, institution, "Réinitialisation",
                          f"Cliquez : {LIEN}\n\n{{signature}}", ["autre@essai.invalide"])
        return BrouillonEnvoi.objects.get()

    def test_l_envoi_restaure_le_vrai_lien(self, brouillon, membre):
        """Les vrais liens sont remis ICI et nulle part ailleurs."""
        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.post(f"/api/brouillons-envoi/{brouillon.id}/envoyer/", {},
                              format='json')

        assert reponse.status_code == 200, reponse.data
        assert len(mail.outbox) == 1
        assert LIEN in mail.outbox[0].body
        brouillon.refresh_from_db()
        assert brouillon.statut == BrouillonEnvoi.Statut.ENVOYE

    def test_le_texte_relu_remplace_le_texte_capture(self, brouillon, membre):
        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.post(f"/api/brouillons-envoi/{brouillon.id}/envoyer/",
                              {"corps": "Texte réécrit : [LIEN_1]"}, format='json')

        assert reponse.status_code == 200
        assert "Texte réécrit" in mail.outbox[0].body
        # Le placeholder conservé par le relecteur est résolu à l'envoi.
        assert LIEN in mail.outbox[0].body
        brouillon.refresh_from_db()
        assert brouillon.modifie_par_relecteur is True

    def test_un_corps_vide_est_refuse(self, brouillon, membre):
        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.post(f"/api/brouillons-envoi/{brouillon.id}/envoyer/",
                              {"corps": "   "}, format='json')
        assert reponse.status_code == 400
        assert len(mail.outbox) == 0

    def test_un_brouillon_ne_part_pas_deux_fois(self, brouillon, membre):
        client = APIClient()
        client.force_authenticate(user=membre)
        client.post(f"/api/brouillons-envoi/{brouillon.id}/envoyer/", {}, format='json')
        reponse = client.post(f"/api/brouillons-envoi/{brouillon.id}/envoyer/", {},
                              format='json')
        assert reponse.status_code == 400
        assert len(mail.outbox) == 1

    def test_l_abandon_exige_un_motif(self, brouillon, membre):
        """L'action qui a produit ce message a déjà eu lieu : abandonner ne la défait pas, et il
        faut pouvoir savoir plus tard pourquoi personne n'a été prévenu."""
        client = APIClient()
        client.force_authenticate(user=membre)

        sans = client.post(f"/api/brouillons-envoi/{brouillon.id}/abandonner/", {},
                           format='json')
        assert sans.status_code == 400

        avec = client.post(f"/api/brouillons-envoi/{brouillon.id}/abandonner/",
                           {"motif": "Prévenu par téléphone"}, format='json')
        assert avec.status_code == 200
        brouillon.refresh_from_db()
        assert brouillon.statut == BrouillonEnvoi.Statut.ABANDONNE
        assert len(mail.outbox) == 0

    def test_un_compte_d_une_autre_institution_ne_voit_pas_le_brouillon(self, brouillon,
                                                                        create_user):
        itype = InstitutionType.objects.get(code='AASC_RELECTURE')
        autre = Institution.objects.create(nom="Autre Relecture", type=itype)
        intrus = create_user(username='intrus-rel@test.fr', email='intrus-rel@test.fr',
                             type='SECOURS', institution=autre)
        ContactInstitution.objects.create(institution=autre, utilisateur=intrus, actif=True)
        client = APIClient()
        client.force_authenticate(user=intrus)

        assert client.get(f"/api/brouillons-envoi/{brouillon.id}/").status_code == 404

    def test_tout_membre_actif_de_l_institution_peut_relire(self, brouillon, institution,
                                                            create_user):
        """La relecture est un geste d'équipe : celui qui a validé un compte à 18 h ne doit pas
        être le seul à pouvoir faire partir le message."""
        collegue = create_user(username='collegue-rel@test.fr', email='collegue-rel@test.fr',
                               type='SECOURS', institution=institution)
        ContactInstitution.objects.create(institution=institution, utilisateur=collegue,
                                          actif=True)
        client = APIClient()
        client.force_authenticate(user=collegue)

        assert client.post(f"/api/brouillons-envoi/{brouillon.id}/envoyer/", {},
                           format='json').status_code == 200


@pytest.mark.django_db
class TestBrouillonsOublies:
    """Une relecture oubliée ne doit pas priver quelqu'un de son information.

    L'action a déjà eu lieu : un compte validé dont le titulaire n'est jamais prévenu est pire
    qu'un texte non relu."""

    @pytest.fixture
    def brouillon_ancien(self, rf, institution, membre):
        from datetime import timedelta

        from django.utils import timezone

        requete = requete_de(rf, membre, liens=[LIEN])
        send_branded_mail(requete, institution, "Compte validé",
                          f"Cliquez : {LIEN}\n\n{{signature}}", ["autre@essai.invalide"])
        brouillon = BrouillonEnvoi.objects.get()
        # auto_now_add : on force la date par une mise à jour directe.
        BrouillonEnvoi.objects.filter(pk=brouillon.pk).update(
            date_creation=timezone.now() - timedelta(hours=48))
        brouillon.refresh_from_db()
        return brouillon

    def test_un_brouillon_trop_vieux_part_avec_un_statut_distinct(self, brouillon_ancien):
        """`EXPEDIE_AUTO` et non `ENVOYE` : c'est ce qui permet de mesurer si la relecture sert
        vraiment ou si elle est systématiquement oubliée."""
        from io import StringIO

        from django.core.management import call_command

        sortie = StringIO()
        call_command('expedier_brouillons_oublies', stdout=sortie)

        brouillon_ancien.refresh_from_db()
        assert brouillon_ancien.statut == BrouillonEnvoi.Statut.EXPEDIE_SANS_RELECTURE
        assert len(mail.outbox) == 1
        # Et le vrai lien a bien été restauré : un message envoyé sans relecture reste un
        # message utilisable.
        assert LIEN in mail.outbox[0].body

    def test_un_brouillon_recent_est_laisse_tranquille(self, rf, institution, membre):
        from io import StringIO

        from django.core.management import call_command

        send_branded_mail(requete_de(rf, membre), institution, "Récent",
                          "Corps\n\n{signature}", ["autre@essai.invalide"])
        call_command('expedier_brouillons_oublies', stdout=StringIO())

        assert BrouillonEnvoi.objects.get().statut == BrouillonEnvoi.Statut.A_RELIRE
        assert len(mail.outbox) == 0

    def test_compter_n_envoie_rien(self, brouillon_ancien):
        from io import StringIO

        from django.core.management import call_command

        sortie = StringIO()
        call_command('expedier_brouillons_oublies', compter=True, stdout=sortie)

        brouillon_ancien.refresh_from_db()
        assert brouillon_ancien.statut == BrouillonEnvoi.Statut.A_RELIRE
        assert len(mail.outbox) == 0
        assert "rien n'a été envoyé" in sortie.getvalue()

    def test_l_expedition_automatique_ne_recree_pas_un_brouillon(self, brouillon_ancien):
        """`request=None` : sans ce garde, chaque passage de la commande recréerait un brouillon
        au lieu d'envoyer, et rien ne partirait jamais."""
        from io import StringIO

        from django.core.management import call_command

        call_command('expedier_brouillons_oublies', stdout=StringIO())
        assert BrouillonEnvoi.objects.count() == 1


@pytest.mark.django_db
class TestGardeStructurelSurLesLiens:
    """Garde structurel : TOUT chemin de `build_magic_link` doit déclarer son lien.

    Le masquage se fait par VALEUR — un lien est masqué parce qu'on sait l'avoir créé. Un chemin
    de fabrication qui oublierait de se déclarer produirait donc un lien **non masqué** dans un
    brouillon, c'est-à-dire un porteur d'identité affiché à quelqu'un qui n'en est pas le
    titulaire. Ce test couvre les deux formes d'URL et toutes les actions connues, pour que
    l'ajout d'une troisième forme casse ici plutôt qu'en production."""

    @pytest.mark.parametrize("action", [
        # Les trois actions qui passent par une page du frontend…
        "activate-account", "magic-login", "reset-password",
        # …et une action sans page dédiée, qui prend l'autre forme d'URL (/api/<action>/…).
        "accuse-reception",
    ])
    def test_chaque_action_declare_son_lien(self, rf, membre, action):
        from core.views import build_magic_link

        requete = rf.post('/api/x/')
        requete.user = membre
        lien = build_magic_link(requete, membre, action)

        assert lien, "aucun lien produit"
        assert lien in getattr(requete, '_liens_magiques', []), (
            f"le lien de l'action « {action} » n'est pas déclaré : il ne serait pas masqué "
            "dans un brouillon de relecture"
        )

    def test_le_parametre_next_est_couvert(self, rf, membre):
        """`?next=` produit une URL différente du même lien : les deux doivent être déclarées,
        sinon la variante avec paramètre passerait en clair."""
        from core.views import build_magic_link

        requete = rf.post('/api/x/')
        requete.user = membre
        lien = build_magic_link(requete, membre, "magic-login", next_url="/suivi/42")
        assert "next=" in lien
        assert lien in requete._liens_magiques

    def test_sans_requete_le_lien_est_produit_quand_meme(self, membre):
        """Jamais bloquant : un appel sans requête (commande, tâche planifiée) doit rendre le
        lien. Il ne sera pas masqué — mais sans requête il n'y a pas de brouillon non plus."""
        from core.views import build_magic_link

        assert build_magic_link(None, membre, "activate-account")
