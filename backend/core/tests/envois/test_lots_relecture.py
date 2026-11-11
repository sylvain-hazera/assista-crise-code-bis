"""Lots de relecture : un texte générique validé une fois pour N destinataires.

Demande de Sylvain (11/11/2026) : « plutôt que valider 6 fois le même envoi, il ne pourrait pas
seulement voir le template avec des valeurs génériques et le valider qu'une fois ? »

Le raisonnement : faire relire deux cents fois le même texte n'est pas une relecture, c'est une
corvée que personne ne fera — et une relecture que personne ne fait est **pire** qu'une absence
de relecture, parce qu'elle donne l'illusion d'un contrôle.

Ce que ces tests verrouillent :

1. **Des messages identiques à un nom près forment UN lot**, et le relire une fois les envoie
   tous, chacun avec ses propres valeurs.
2. **Le corps stocké est générique** : ni le nom réel, ni le lien réel n'y figurent. Le lien
   était déjà masqué ; le nom l'est maintenant aussi.
3. **Le texte relu peut être réécrit** et la repersonnalisation s'applique quand même : c'est
   tout l'intérêt, sinon réécrire ferait partir « Bonjour [PRENOM] ».
4. **Le regroupement ne traverse pas les requêtes** : deux imports sont deux décisions.
5. **Un échec sur un destinataire n'empêche pas les autres**, et il est nommé.
"""
import pytest
from django.core import mail
from rest_framework.test import APIClient

from core.branding import send_branded_mail
from core.brouillons_envoi import generiser
from core.models import (
    BrouillonEnvoi, ConfigurationEnvoiInstitution, ContactInstitution, Institution,
    InstitutionType,
)

LIEN = "https://exemple.invalide/activate-account/MQ/MQ:signature"


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_LOT',
                                                     defaults={'libelle': 'Association'})
    inst = Institution.objects.create(nom="Association Lot", type=itype,
                                      nom_affichage="Reserve Lot")
    ConfigurationEnvoiInstitution.objects.create(institution=inst, relecture_avant_envoi=True)
    return inst


@pytest.fixture
def membre(create_user, institution):
    u = create_user(username='membre-lot@test.fr', email='membre-lot@test.fr', type='SECOURS',
                    institution=institution)
    ContactInstitution.objects.create(institution=institution, utilisateur=u, actif=True)
    return u


@pytest.fixture
def benevoles(create_user):
    """Six bénévoles, comme le fichier des Casques Jaunes."""
    noms = [("Virginie", "Duparc"), ("Philippe", "Faugeron"), ("Jeff", "Hagnier"),
            ("Mikael", "Millac"), ("Jacques", "Laurent"), ("Agnes", "Lamy")]
    return [
        create_user(username=f"{p.lower()}.{n.lower()}@essai.invalide",
                    email=f"{p.lower()}.{n.lower()}@essai.invalide",
                    first_name=p, last_name=n)
        for p, n in noms
    ]


def requete_de(rf, utilisateur, liens=()):
    r = rf.post('/api/x/')
    r.user = utilisateur
    if liens:
        r._liens_magiques = list(liens)
    return r


def envoyer_les_six(requete, institution, benevoles):
    """Ce que fait un import : un message par bénévole, dans LA MÊME requête."""
    for b in benevoles:
        # Chacun a son propre lien magique, comme à l'inscription.
        requete._liens_magiques = [f"{LIEN}-{b.first_name}"]
        send_branded_mail(
            requete, institution,
            subject=f"Bienvenue {b.first_name}",
            message=(f"Bonjour {b.first_name} {b.last_name},\n\n"
                     f"Activez votre compte : {LIEN}-{b.first_name}\n\n{{signature}}"),
            recipient_list=[b.email],
        )


@pytest.mark.django_db
class TestRegroupement:

    def test_six_messages_identiques_forment_UN_lot(self, rf, institution, membre,
                                                    benevoles):
        envoyer_les_six(requete_de(rf, membre), institution, benevoles)

        assert BrouillonEnvoi.objects.count() == 6
        lots = set(BrouillonEnvoi.objects.values_list('lot', flat=True))
        assert len(lots) == 1 and None not in lots

    def test_un_seul_texte_est_propose_a_la_relecture(self, rf, institution, membre,
                                                      benevoles):
        """Le cœur de la demande : six envois, une validation."""
        envoyer_les_six(requete_de(rf, membre), institution, benevoles)

        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.get("/api/brouillons-envoi/lots-a-relire/")

        assert reponse.status_code == 200, reponse.data
        assert len(reponse.data) == 1
        assert reponse.data[0]['effectif'] == 6
        assert len(reponse.data[0]['destinataires_du_lot']) == 6

    def test_le_corps_propose_est_GENERIQUE(self, rf, institution, membre, benevoles):
        """Ni le nom réel, ni le lien réel. Le lien était déjà masqué ; le nom l'est aussi."""
        envoyer_les_six(requete_de(rf, membre), institution, benevoles)

        client = APIClient()
        client.force_authenticate(user=membre)
        corps = client.get("/api/brouillons-envoi/lots-a-relire/").data[0]['corps']

        assert "[PRENOM]" in corps and "[NOM]" in corps
        assert "[LIEN_1]" in corps
        for b in benevoles:
            assert b.first_name not in corps
            assert b.last_name not in corps
        assert "exemple.invalide" not in corps

    def test_deux_requetes_font_deux_lots(self, rf, institution, membre, benevoles):
        """Deux imports sont deux décisions : les fondre ferait valider d'un geste des
        messages qu'on n'a pas vus partir ensemble."""
        envoyer_les_six(requete_de(rf, membre), institution, benevoles[:3])
        envoyer_les_six(requete_de(rf, membre), institution, benevoles[3:])

        assert len(set(BrouillonEnvoi.objects.values_list('lot', flat=True))) == 2

    def test_des_textes_differents_ne_se_regroupent_pas(self, rf, institution, membre,
                                                        benevoles):
        requete = requete_de(rf, membre)
        send_branded_mail(requete, institution, "A", "Texte A\n\n{signature}",
                          [benevoles[0].email])
        send_branded_mail(requete, institution, "B", "Texte B tout autre\n\n{signature}",
                          [benevoles[1].email])

        assert len(set(BrouillonEnvoi.objects.values_list('lot', flat=True))) == 2


@pytest.mark.django_db
class TestEnvoiDuLot:

    @pytest.fixture
    def lot(self, rf, institution, membre, benevoles):
        envoyer_les_six(requete_de(rf, membre), institution, benevoles)
        return BrouillonEnvoi.objects.first()

    def test_valider_une_fois_envoie_les_six(self, lot, membre, benevoles):
        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.post(f"/api/brouillons-envoi/{lot.id}/envoyer-lot/", {},
                              format='json')

        assert reponse.status_code == 200, reponse.data
        assert reponse.data['envoyes'] == 6
        assert reponse.data['echecs'] == []
        assert len([m for m in mail.outbox if m.to]) == 6
        assert BrouillonEnvoi.objects.filter(
            statut=BrouillonEnvoi.Statut.A_RELIRE).count() == 0

    def test_chaque_message_repart_avec_SES_valeurs(self, lot, membre, benevoles):
        """La repersonnalisation est ce qui rend le lot acceptable : un texte validé une fois,
        six messages personnalisés."""
        client = APIClient()
        client.force_authenticate(user=membre)
        client.post(f"/api/brouillons-envoi/{lot.id}/envoyer-lot/", {}, format='json')

        par_destinataire = {m.to[0]: m.body for m in mail.outbox if m.to}
        for b in benevoles:
            corps = par_destinataire[b.email]
            assert f"Bonjour {b.first_name} {b.last_name}," in corps
            # Et son propre lien, pas celui du voisin.
            assert f"{LIEN}-{b.first_name}" in corps
            assert "[PRENOM]" not in corps and "[LIEN_1]" not in corps

    def test_le_texte_REECRIT_est_repersonnalise_aussi(self, lot, membre, benevoles):
        """Sinon réécrire le texte ferait partir « Bonjour [PRENOM] » à tout le monde."""
        client = APIClient()
        client.force_authenticate(user=membre)
        client.post(f"/api/brouillons-envoi/{lot.id}/envoyer-lot/",
                    {"corps": "Salut [PRENOM] ! Voici ton lien : [LIEN_1]"}, format='json')

        par_destinataire = {m.to[0]: m.body for m in mail.outbox if m.to}
        for b in benevoles:
            assert f"Salut {b.first_name} !" in par_destinataire[b.email]
            assert f"{LIEN}-{b.first_name}" in par_destinataire[b.email]

    def test_un_echec_n_empeche_pas_les_autres_et_il_est_nomme(self, lot, membre,
                                                               benevoles):
        """Sur un lot de deux cents, une adresse invalide ne doit pas empêcher les autres de
        partir. Et un lot « partiellement envoyé » qu'on croirait complet serait pire qu'un
        échec franc."""
        casse = BrouillonEnvoi.objects.exclude(pk=lot.pk).first()
        casse.destinataires = []
        casse.save(update_fields=['destinataires'])

        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.post(f"/api/brouillons-envoi/{lot.id}/envoyer-lot/", {},
                              format='json')

        assert reponse.data['envoyes'] == 5
        assert len(reponse.data['echecs']) == 1
        assert "destinataire" in reponse.data['echecs'][0]['motif'].lower()

    def test_un_brouillon_isole_s_envoie_par_le_meme_endpoint(self, rf, institution, membre,
                                                              benevoles):
        """L'appelant n'a pas à distinguer les deux cas."""
        requete = requete_de(rf, membre)
        send_branded_mail(requete, institution, "Seul", "Un seul message\n\n{signature}",
                          [benevoles[0].email])
        seul = BrouillonEnvoi.objects.get()

        client = APIClient()
        client.force_authenticate(user=membre)
        reponse = client.post(f"/api/brouillons-envoi/{seul.id}/envoyer-lot/", {},
                              format='json')
        assert reponse.data['envoyes'] == 1

    def test_le_lot_est_pris_dans_le_queryset_CLOISONNE(self, lot, create_user, institution):
        """Sans cela, valider un lot enverrait aussi les messages d'une institution qu'on n'a
        pas le droit de voir."""
        itype = InstitutionType.objects.get(code='AASC_LOT')
        autre = Institution.objects.create(nom="Autre Lot", type=itype)
        intrus = create_user(username='intrus-lot@test.fr', email='intrus-lot@test.fr',
                             type='SECOURS', institution=autre)
        ContactInstitution.objects.create(institution=autre, utilisateur=intrus, actif=True)

        client = APIClient()
        client.force_authenticate(user=intrus)
        assert client.post(f"/api/brouillons-envoi/{lot.id}/envoyer-lot/", {},
                           format='json').status_code == 404


class TestGenerisation:

    def test_les_valeurs_sont_remplacees_de_la_plus_longue_a_la_plus_courte(self):
        """Un prénom peut être contenu dans un nom (« Martin Martinez ») : commencer par la
        plus courte laisserait un fragment."""
        rendu = generiser("Martin Martinez", {"PRENOM": "Martin", "NOM": "Martinez"})
        assert rendu == "[PRENOM] [NOM]"

    def test_une_valeur_trop_courte_est_ignoree(self):
        """Remplacer « Li » par « [NOM] » massacrerait le texte partout où ces deux lettres
        apparaissent. Le message est alors relu tel quel — moins pratique, jamais faux."""
        assert generiser("Bonjour Li Wu, voici la liste",
                         {"PRENOM": "Li", "NOM": "Wu"}) == "Bonjour Li Wu, voici la liste"

    def test_l_email_est_generise_sans_casser_le_nom(self):
        rendu = generiser("jean.dupont@x.fr pour Jean Dupont",
                          {"EMAIL": "jean.dupont@x.fr", "PRENOM": "Jean", "NOM": "Dupont"})
        assert rendu == "[EMAIL] pour [PRENOM] [NOM]"
