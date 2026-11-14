"""Mobiliser par l'application, et savoir ce que le message est devenu.

Demande de Sylvain du 14/11/2026 : « un feedback de qui a eu la notif, vu, lu, répondu (une
réponse négative est une réponse) ». Ce que ces tests verrouillent :

1. **La portée annoncée est un fait.** Le canal n'écrit qu'à qui a l'application ; les autres
   ne sont pas comptés « envoyés », sinon on économiserait un SMS qui, lui, serait arrivé.
2. **Chaque étape est datée une fois**, et entraîne les précédentes.
3. **Personne n'accuse à la place d'un autre**, ni ne lit ses notifications.
4. **Un « non » est une réponse** : il sort la personne des relances, et retire ses créneaux
   de la période — le moteur n'a qu'une règle, « pas de ligne = indisponible ».
5. **Répondre par le site compte aussi** dans le suivi de l'application.
"""
import datetime

import pytest
from django.utils import timezone

from core import notifications_application as moteur
from core.models import (
    AppareilMobile, CibleCampagne, DisponibiliteOffre, EtatCible, NotificationApplication,
)

from .test_campagnes_disponibilite import URL, _benevole, _campagne, _client, asso  # noqa: F401

APPLI = ["APPLICATION"]


def _telephone(utilisateur, **kwargs):
    return moteur.enregistrer_appareil(
        utilisateur, f"installation-{utilisateur.id}", "ANDROID", "0.4.0", **kwargs)


@pytest.mark.django_db
class TestPorteeDuCanal:

    def test_seuls_ceux_qui_ont_l_application_sont_notifies(self, create_user, asso):
        bureau, _ = _benevole(create_user, "nbur", asso, bureau=True)
        avec, _ = _benevole(create_user, "avec", asso)
        _benevole(create_user, "sans", asso)
        _telephone(avec)
        campagne = _campagne(asso, canaux=APPLI)

        reponse = _client(bureau).post(f"{URL}{campagne.id}/envoyer/")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["par_canal"]["APPLICATION"] == 1
        assert list(NotificationApplication.objects.values_list("utilisateur", flat=True)) == [avec.id]
        # Les autres sont dits injoignables, pas « envoyés » : c'est à eux qu'il faut un SMS.
        assert reponse.data["echecs"] == 2

    def test_l_apercu_annonce_la_portee_reelle(self, create_user, asso):
        bureau, _ = _benevole(create_user, "nbur2", asso, bureau=True)
        avec, _ = _benevole(create_user, "avec2", asso)
        _telephone(avec)
        campagne = _campagne(asso, canaux=APPLI)

        reponse = _client(bureau).post(f"{URL}{campagne.id}/apercu/")

        canal = next(c for c in reponse.data["canaux"] if c["code"] == "APPLICATION")
        assert canal["destinataires"] == 1
        assert canal["non_joignables"] == 1

    def test_un_telephone_muet_depuis_longtemps_ne_joint_plus_personne(self, create_user, asso):
        ancien, _ = _benevole(create_user, "ancien", asso)
        _telephone(ancien)
        AppareilMobile.objects.update(
            dernier_contact=timezone.now() - datetime.timedelta(days=moteur.APPAREIL_ACTIF_JOURS + 1))

        assert moteur.joignables_par_application([ancien.id]) == set()

    def test_un_telephone_qui_change_de_compte_suit_le_dernier_connecte(self, create_user, asso):
        premier, _ = _benevole(create_user, "premier", asso)
        second, _ = _benevole(create_user, "second", asso)
        moteur.enregistrer_appareil(premier, "meme-telephone-0001", "ANDROID", "0.4.0")
        moteur.enregistrer_appareil(second, "meme-telephone-0001", "ANDROID", "0.4.0")

        assert moteur.joignables_par_application([premier.id, second.id]) == {second.id}

    def test_le_titre_ne_dit_rien_du_motif(self, create_user, asso):
        """Il s'affiche sur l'écran verrouillé, par-dessus l'épaule."""
        bureau, _ = _benevole(create_user, "nbur3", asso, bureau=True)
        _telephone(bureau)
        campagne = _campagne(asso, canaux=APPLI, texte="Dispositif préfectoral en préparation.")

        _client(bureau).post(f"{URL}{campagne.id}/envoyer/")

        notification = NotificationApplication.objects.get()
        assert "préfectoral" not in notification.titre
        assert "préfectoral" in notification.corps

    def test_rien_n_est_en_clair_en_base(self, create_user, asso):
        from django.db import connection

        bureau, _ = _benevole(create_user, "nbur4", asso, bureau=True)
        _telephone(bureau)
        campagne = _campagne(asso, canaux=APPLI, texte="Vigilance rouge attendue jeudi.")
        _client(bureau).post(f"{URL}{campagne.id}/envoyer/")

        with connection.cursor() as curseur:
            curseur.execute("SELECT titre, corps FROM core_notificationapplication")
            titre, corps = curseur.fetchone()
        assert "disponible" not in titre
        assert "Vigilance" not in corps


@pytest.mark.django_db
class TestEtapes:

    def _notifiee(self, create_user, asso, nom):
        benevole, _ = _benevole(create_user, nom, asso)
        _telephone(benevole)
        campagne = _campagne(asso, canaux=APPLI)
        CibleCampagne.objects.create(campagne=campagne, utilisateur=benevole,
                                     etat=EtatCible.CONTACTE, environment="PROD")
        notification = moteur.notifier(benevole, "CAMPAGNE", "Titre", "Corps", campagne=campagne)
        return benevole, campagne, notification

    def test_lire_la_liste_n_accuse_rien(self, create_user, asso):
        benevole, _c, notification = self._notifiee(create_user, asso, "e1")

        reponse = _client(benevole).get("/api/mes-notifications/")

        assert [n["titre"] for n in reponse.data] == ["Titre"]
        notification.refresh_from_db()
        assert notification.date_remise is None

    def test_lue_entraine_vue_et_remise(self, create_user, asso):
        benevole, _c, notification = self._notifiee(create_user, asso, "e2")

        _client(benevole).post("/api/mes-notifications/accuser/",
                               {"ids": [str(notification.id)], "etape": "LUE"}, format="json")

        notification.refresh_from_db()
        assert notification.date_remise and notification.date_vue and notification.date_lue

    def test_une_etape_n_est_datee_qu_une_fois(self, create_user, asso):
        benevole, _c, notification = self._notifiee(create_user, asso, "e3")
        client = _client(benevole)
        corps = {"ids": [str(notification.id)], "etape": "REMISE"}
        client.post("/api/mes-notifications/accuser/", corps, format="json")
        notification.refresh_from_db()
        premiere = notification.date_remise

        reponse = client.post("/api/mes-notifications/accuser/", corps, format="json")

        notification.refresh_from_db()
        assert notification.date_remise == premiere
        assert reponse.data["avancees"] == 0

    def test_personne_n_accuse_pour_un_autre(self, create_user, asso):
        _b, _c, notification = self._notifiee(create_user, asso, "e4")
        intrus, _ = _benevole(create_user, "intrus", asso)

        reponse = _client(intrus).post(
            "/api/mes-notifications/accuser/",
            {"ids": [str(notification.id)], "etape": "LUE"}, format="json")

        assert reponse.data["avancees"] == 0
        notification.refresh_from_db()
        assert notification.date_lue is None
        assert _client(intrus).get("/api/mes-notifications/").data == []

    def test_un_identifiant_mal_forme_n_empeche_pas_les_autres(self, create_user, asso):
        benevole, _c, notification = self._notifiee(create_user, asso, "e5")

        reponse = _client(benevole).post(
            "/api/mes-notifications/accuser/",
            {"ids": ["pas-un-uuid", str(notification.id)], "etape": "VUE"}, format="json")

        assert reponse.data["avancees"] == 1

    def test_le_suivi_rend_les_etapes_a_l_encadrement(self, create_user, asso):
        bureau, _ = _benevole(create_user, "nbur5", asso, bureau=True)
        benevole, campagne, notification = self._notifiee(create_user, asso, "e6")
        moteur.accuser(benevole, [notification.id], "VUE")

        cibles = _client(bureau).get(f"{URL}{campagne.id}/cibles/").data
        suivi = _client(bureau).get(f"{URL}{campagne.id}/").data["suivi"]["application"]

        ligne = next(c for c in cibles if c["utilisateur"] == benevole.id)["application"]
        assert ligne["remise"] and ligne["vue"] and ligne["lue"] is None
        assert suivi == {"notifiees": 1, "remises": 1, "vues": 1, "lues": 0,
                         "repondu": 0, "repondu_non": 0}

    def test_des_notifications_coupees_sont_dites(self, create_user, asso):
        """« Remise » ne veut alors pas dire « prévenue »."""
        benevole, campagne, _n = self._notifiee(create_user, asso, "e7")
        _telephone(benevole, notifications_autorisees=False)

        assert moteur.suivi_par_personne(campagne)[benevole.id]["notifications_autorisees"] is False


@pytest.mark.django_db
class TestUnNonEstUneReponse:

    def _sollicite(self, create_user, asso, nom):
        benevole, offre = _benevole(create_user, nom, asso)
        _telephone(benevole)
        campagne = _campagne(asso, canaux=APPLI)
        cible = CibleCampagne.objects.create(campagne=campagne, utilisateur=benevole,
                                             etat=EtatCible.CONTACTE, environment="PROD")
        moteur.notifier(benevole, "CAMPAGNE", "Titre", campagne=campagne)
        return benevole, offre, campagne, cible

    def test_dire_non_vaut_reponse(self, create_user, asso):
        benevole, _o, campagne, cible = self._sollicite(create_user, asso, "n1")

        reponse = _client(benevole).post("/api/mes-disponibilites/indisponible/",
                                         {"campagne": str(campagne.id)}, format="json")

        assert reponse.status_code == 200, reponse.data
        cible.refresh_from_db()
        assert cible.etat == EtatCible.A_REPONDU
        assert cible.creneaux_declares == 0
        assert moteur.bilan(campagne)["repondu_non"] == 1

    def test_dire_non_retire_les_creneaux_de_la_periode_et_eux_seuls(self, create_user, asso):
        benevole, offre, campagne, _c = self._sollicite(create_user, asso, "n2")
        dedans = DisponibiliteOffre.objects.create(
            offer=offre, date=campagne.periode_debut, creneau="MATIN", environment="PROD")
        dehors = DisponibiliteOffre.objects.create(
            offer=offre, date=campagne.periode_fin + datetime.timedelta(days=3),
            creneau="MATIN", environment="PROD")

        _client(benevole).post("/api/mes-disponibilites/indisponible/",
                               {"campagne": str(campagne.id)}, format="json")

        assert not DisponibiliteOffre.objects.filter(pk=dedans.pk).exists()
        assert DisponibiliteOffre.objects.filter(pk=dehors.pk).exists()

    def test_qui_a_dit_non_n_est_pas_relance(self, create_user, asso):
        bureau, _ = _benevole(create_user, "nbur6", asso, bureau=True)
        benevole, _o, campagne, _c = self._sollicite(create_user, asso, "n3")
        _client(benevole).post("/api/mes-disponibilites/indisponible/",
                               {"campagne": str(campagne.id)}, format="json")
        avant = NotificationApplication.objects.filter(utilisateur=benevole).count()

        _client(bureau).post(f"{URL}{campagne.id}/relancer/")

        assert NotificationApplication.objects.filter(utilisateur=benevole).count() == avant

    def test_on_ne_repond_pas_a_une_campagne_qui_ne_nous_est_pas_adressee(self, create_user, asso):
        etranger, _ = _benevole(create_user, "n4", asso)
        campagne = _campagne(asso, canaux=APPLI)

        reponse = _client(etranger).post("/api/mes-disponibilites/indisponible/",
                                         {"campagne": str(campagne.id)}, format="json")

        assert reponse.status_code == 404

    def test_repondre_par_le_site_compte_dans_le_suivi_de_l_application(self, create_user, asso):
        benevole, _o, campagne, _c = self._sollicite(create_user, asso, "n5")

        _client(benevole).post("/api/mes-disponibilites/", {
            "date": str(campagne.periode_debut), "creneau": "SOIR", "disponible": True,
            "campagne": str(campagne.id),
        }, format="json")

        assert NotificationApplication.objects.get(utilisateur=benevole).date_reponse is not None
        bilan = moteur.bilan(campagne)
        assert bilan["repondu"] == 1 and bilan["repondu_non"] == 0

    def test_la_notification_dit_a_l_application_qu_on_a_repondu(self, create_user, asso):
        benevole, _o, campagne, _c = self._sollicite(create_user, asso, "n6")
        client = _client(benevole)
        assert client.get("/api/mes-notifications/").data[0]["campagne"]["repondu"] is False

        client.post("/api/mes-disponibilites/indisponible/",
                    {"campagne": str(campagne.id)}, format="json")

        assert client.get("/api/mes-notifications/").data[0]["campagne"]["repondu"] is True
