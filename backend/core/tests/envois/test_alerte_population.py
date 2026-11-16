"""L'alerte de la commune à ses habitants : elle ne part qu'à ceux qui l'ont demandée ou que la
crise touche, par les canaux retenus, et elle dit ce qu'elle est devenue."""
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core import alerte_population, matrix, notifications_application
from core.models import (
    AbonnementAlerte, AlertePopulation, AuditLog, ConfigurationEnvoiInstitution, Crisis, Institution,
    InstitutionType, NotificationApplication,
)

URL = "/api/alertes-population/"


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie de l'alerte", type=itype, commune_code="42207")


@pytest.fixture
def agent(create_user, mairie):
    user = create_user(username="agent-alerte@test.fr", email="agent-alerte@test.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def habitant(create_user):
    def _habitant(nom, telephone=None):
        return create_user(username=f"{nom}@test.fr", email=f"{nom}@test.fr", type="UTIL_SIMPLE", phone_number=telephone)
    return _habitant


@pytest.fixture
def envois(monkeypatch):
    """Les canaux simulés : on retient ce qui serait parti, rien ne sort."""
    partis = {"matrix": [], "sms": []}
    monkeypatch.setattr(matrix, "envoyer_dm", lambda user, texte, *a, **k: partis["matrix"].append((user.id, texte)))
    monkeypatch.setattr("core.envoi_sms.envoyer_sms_pour_institution",
                        lambda institution, numero, message: (partis["sms"].append((numero, message)) or True, "ok"))
    return partis


def _abonner(habitant, mairie):
    return AbonnementAlerte.objects.create(utilisateur=habitant, institution=mairie)


@pytest.mark.django_db
class TestQuiRecoit:
    def test_les_abonnes_et_les_personnes_touchees_par_la_crise_et_personne_dautre(self, mairie, habitant):
        abonne, touche, ailleurs, desabonne, inconnu = (habitant(n) for n in ("abonne", "touche", "ailleurs", "desabonne", "inconnu"))
        crise = Crisis.objects.create(name="Crue", type="INONDATION", location=Point(4.51, 45.47, srid=4326))
        autre_mairie = Institution.objects.create(nom="Mairie voisine", type=mairie.type, commune_code="42218")
        _abonner(abonne, mairie)
        _abonner(ailleurs, autre_mairie)
        AbonnementAlerte.objects.create(utilisateur=desabonne, institution=mairie, actif=False)
        touche.affected_crisis = crise
        touche.save()

        assert set(alerte_population.destinataires(mairie, crise, "PROD")) == {abonne, touche}
        # Hors crise, seuls ceux qui l'ont demandé.
        assert set(alerte_population.destinataires(mairie, None, "PROD")) == {abonne}

    def test_chacun_sabonne_et_se_desabonne_pour_lui_meme(self, mairie, habitant):
        client = APIClient()
        client.force_authenticate(user=habitant("libre"))

        assert client.post(URL + "abonnement/", {"institution": str(mairie.id)}, format="json").status_code == 201
        assert [a["institution_nom"] for a in client.get(URL + "abonnement/").data] == ["Mairie de l'alerte"]
        assert client.delete(URL + "abonnement/", {"institution": str(mairie.id)}, format="json").status_code == 204
        assert client.get(URL + "abonnement/").data == []
        assert alerte_population.destinataires(mairie, None, "PROD").count() == 0


@pytest.mark.django_db
class TestEnvoi:
    def test_par_defaut_lalerte_part_par_la_messagerie_et_lapplication(self, agent, mairie, habitant, envois):
        avec_appli, sans_appli = habitant("avec-appli"), habitant("sans-appli")
        for h in (avec_appli, sans_appli):
            _abonner(h, mairie)
        notifications_application.enregistrer_appareil(avec_appli, "installation-1")
        defaut = agent.get(URL).data["par_defaut"]
        assert defaut == ["MATRIX", "APPLICATION"]

        reponse = agent.post(URL, {"titre": "Crue du Gier", "message": "Évacuez le quartier bas.", "canaux": defaut}, format="json")

        assert reponse.status_code == 201, reponse.data
        assert reponse.data["destinataires"] == 2
        assert reponse.data["bilan"]["MATRIX"]["partis"] == 2 and len(envois["matrix"]) == 2
        # L'application ne compte que ceux qu'elle peut réellement joindre.
        assert reponse.data["bilan"]["APPLICATION"]["partis"] == 1
        notification = NotificationApplication.objects.get(utilisateur=avec_appli)
        assert notification.urgent and notification.titre == "Crue du Gier"

    def test_le_message_nest_pas_stocke_en_clair_et_la_trace_ne_le_recopie_pas(self, agent, mairie, habitant, envois):
        from django.db import connection

        _abonner(habitant("lecteur"), mairie)

        reponse = agent.post(URL, {"titre": "Crue", "message": "TEXTE-CONFIDENTIEL de l'alerte", "canaux": ["MATRIX"]}, format="json")

        with connection.cursor() as curseur:
            curseur.execute("SELECT message FROM core_alertepopulation WHERE id = %s", [reponse.data["id"]])
            assert "TEXTE-CONFIDENTIEL" not in curseur.fetchone()[0]
        assert AlertePopulation.objects.get(pk=reponse.data["id"]).message == "TEXTE-CONFIDENTIEL de l'alerte"
        trace = AuditLog.objects.filter(objet_type="AlertePopulation", action__code="ENVOI_MASSE").latest("date_action")
        assert "TEXTE-CONFIDENTIEL" not in trace.commentaire and "1 destinataire" in trace.commentaire

    def test_le_sms_ne_part_que_si_la_collectivite_a_un_fournisseur(self, agent, mairie, habitant, envois):
        _abonner(habitant("mobile", telephone="+33600000001"), mairie)

        sans = agent.post(URL, {"titre": "Crue", "message": "Texte", "canaux": ["SMS"]}, format="json").data
        assert sans["bilan"]["SMS"]["partis"] == 0 and "fournisseur" in sans["bilan"]["SMS"]["note"] and envois["sms"] == []

        ConfigurationEnvoiInstitution.objects.create(institution=mairie, fournisseur_sms="brevo", sms_cle_api="cle-de-test",
                                                     sms_expediteur="Mairie")
        avec = agent.post(URL, {"titre": "Crue", "message": "Texte", "canaux": ["SMS"]}, format="json").data
        assert avec["bilan"]["SMS"]["partis"] == 1 and envois["sms"][0][0] == "+33600000001"

    def test_intramuros_est_prepare_mais_ne_fait_aucun_appel(self, agent, mairie, habitant, envois, monkeypatch):
        """La clé de la collectivité se range, chiffrée ; l'appel attend la documentation de
        leur API. Aucune requête ne part vers une adresse devinée."""
        import requests

        def interdit(*a, **k):
            raise AssertionError("aucun appel réseau ne doit partir pour IntraMuros")
        monkeypatch.setattr(requests, "post", interdit)
        monkeypatch.setattr(requests, "get", interdit)
        _abonner(habitant("lecteur-im"), mairie)
        ConfigurationEnvoiInstitution.objects.create(institution=mairie, intramuros_cle_api="cle-intramuros-de-test")

        canal = next(c for c in agent.get(URL).data["apercu"]["canaux"] if c["code"] == "INTRAMUROS")
        assert canal["disponible"] is False and "pas encore branché" in canal["motif"]
        reponse = agent.post(URL, {"titre": "Crue", "message": "Texte", "canaux": ["INTRAMUROS", "MATRIX"]}, format="json")

        assert reponse.data["bilan"]["INTRAMUROS"]["partis"] == 0 and "pas encore branché" in reponse.data["bilan"]["INTRAMUROS"]["note"]
        assert reponse.data["bilan"]["MATRIX"]["partis"] == 1   # le reste part quand même

    def test_un_canal_en_panne_narrete_pas_les_autres(self, agent, mairie, habitant, monkeypatch):
        cible = habitant("resilient")
        _abonner(cible, mairie)
        notifications_application.enregistrer_appareil(cible, "installation-2")

        def panne(*a, **k):
            raise RuntimeError("messagerie indisponible")
        monkeypatch.setattr(matrix, "envoyer_dm", panne)

        bilan = agent.post(URL, {"titre": "Crue", "message": "Texte", "canaux": ["MATRIX", "APPLICATION"]}, format="json").data["bilan"]

        assert bilan["MATRIX"] == {"partis": 0, "echecs": 1, "note": ""} and bilan["APPLICATION"]["partis"] == 1

    def test_en_zone_de_demonstration_lalerte_ne_part_qua_celui_qui_lenvoie(self, mairie, habitant, envois, create_user, monkeypatch):
        """Il constate le fonctionnement, et aucun habitant ne reçoit une fausse alerte."""
        from django.test import RequestFactory

        monkeypatch.setattr("core.permissions.get_active_environment", lambda request: "DEMO")
        cible = habitant("demo")
        AbonnementAlerte.objects.create(utilisateur=cible, institution=mairie, environment="DEMO")
        auteur = create_user(username="auteur-demo@test.fr", email="auteur-demo@test.fr", type="AUT_LOCALE")
        notifications_application.enregistrer_appareil(auteur, "installation-auteur")
        notifications_application.enregistrer_appareil(cible, "installation-cible")
        requete = RequestFactory().post("/")
        requete.user = auteur

        alerte = alerte_population.envoyer(requete, mairie, None, "Essai", "Texte", ["MATRIX", "APPLICATION"])

        assert alerte.destinataires == 1                               # ce qu'elle aurait touché
        assert [destinataire for destinataire, _ in envois["matrix"]] == [auteur.id]
        assert NotificationApplication.objects.filter(utilisateur=auteur).count() == 1
        assert not NotificationApplication.objects.filter(utilisateur=cible).exists()
        assert alerte.bilan["MATRIX"]["partis"] == 1 and "vous seul" in alerte.bilan["MATRIX"]["note"]


@pytest.mark.django_db
class TestRadio:
    def _canaux(self, mairie, crise=None):
        from core.models import CanalMeshCore, CanalMeshtastic, Team

        equipe = Team.objects.create(name="Logistique", institution=mairie)
        commune = CanalMeshCore.objects.create(institution=mairie, nom="Commune")
        CanalMeshCore.objects.create(institution=mairie, nom="Equipe", equipe=equipe)     # canal d'équipe : exclu
        CanalMeshtastic.objects.create(institution=mairie, nom="Commune-MT")
        return commune

    def test_lalerte_part_sur_le_canal_de_la_commune_jamais_sur_celui_dune_equipe(self, agent, mairie, envois):
        from core.models import MessageCanalMeshCore, MessageCanalMeshtastic

        commune = self._canaux(mairie)

        reponse = agent.post(URL, {"titre": "Crue du Gier", "message": "Évacuez le quartier bas.\nRendez-vous au gymnase.",
                                   "canaux": ["MESHCORE", "MESHTASTIC"]}, format="json")

        assert reponse.status_code == 201, reponse.data
        assert reponse.data["bilan"]["MESHCORE"]["partis"] == 1 and reponse.data["bilan"]["MESHTASTIC"]["partis"] == 1
        message = MessageCanalMeshCore.objects.get()
        assert message.canal == commune and message.statut == "EN_ATTENTE"
        assert message.contenu == "ALERTE Crue du Gier : Évacuez le quartier bas. Rendez-vous au gymnase."
        assert MessageCanalMeshtastic.objects.count() == 1

    def test_un_message_radio_est_raccourci(self, agent, mairie, envois):
        from core.models import MessageCanalMeshCore

        self._canaux(mairie)

        agent.post(URL, {"titre": "Crue", "message": "x" * 500, "canaux": ["MESHCORE"]}, format="json")

        assert len(MessageCanalMeshCore.objects.get().contenu) == alerte_population.LONGUEUR_RADIO

    def test_sans_canal_de_la_commune_la_radio_nest_pas_proposee(self, agent, mairie, envois):
        canaux = {c["code"]: c for c in agent.get(URL).data["apercu"]["canaux"]}

        assert canaux["MESHCORE"]["disponible"] is False and "canal MeshCore" in canaux["MESHCORE"]["motif"]
        assert canaux["MESHTASTIC"]["joignables"] is None

    def test_en_demonstration_la_radio_ne_part_pas(self, mairie, envois, create_user, monkeypatch):
        from django.test import RequestFactory

        from core.models import CanalMeshCore, MessageCanalMeshCore

        monkeypatch.setattr("core.permissions.get_active_environment", lambda request: "DEMO")
        CanalMeshCore.objects.create(institution=mairie, nom="Commune", environment="DEMO")
        requete = RequestFactory().post("/")
        requete.user = create_user(username="auteur-radio@test.fr", email="auteur-radio@test.fr", type="AUT_LOCALE")

        alerte = alerte_population.envoyer(requete, mairie, None, "Essai", "Texte", ["MESHCORE"])

        assert not MessageCanalMeshCore.objects.exists() and "radio ne part pas" in alerte.bilan["MESHCORE"]["note"]


@pytest.mark.django_db
class TestSabonner:
    def test_lhabitant_cherche_sa_commune_par_son_nom(self, mairie, habitant):
        client = APIClient()
        client.force_authenticate(user=habitant("chercheur"))

        assert client.get(URL + "collectivites/", {"q": "a"}).data == []          # trop court : rien
        trouvees = client.get(URL + "collectivites/", {"q": "alerte"}).data
        assert trouvees == [{"id": str(mairie.id), "nom": "Mairie de l'alerte"}]
        assert APIClient().get(URL + "collectivites/", {"q": "alerte"}).status_code in (401, 403)


@pytest.mark.django_db
class TestDroits:
    def test_un_habitant_nenvoie_pas_dalerte_et_il_faut_un_titre_un_message_et_un_canal(self, agent, habitant):
        client = APIClient()
        client.force_authenticate(user=habitant("curieux"))
        assert client.post(URL, {"titre": "x", "message": "y", "canaux": ["MATRIX"]}, format="json").status_code == 403
        assert APIClient().get(URL).status_code in (401, 403)

        assert agent.post(URL, {"titre": "", "message": "y", "canaux": ["MATRIX"]}, format="json").status_code == 400
        assert agent.post(URL, {"titre": "x", "message": "y", "canaux": []}, format="json").status_code == 400
        assert agent.post(URL, {"titre": "x", "message": "y", "canaux": ["PIGEON"]}, format="json").status_code == 400
