"""L'alerte de la commune à ses habitants : elle ne part qu'à ceux qui l'ont demandée ou que la
crise touche, par les canaux retenus, et elle dit ce qu'elle est devenue."""
from core.tests.outils_chiffre import filtrer_chiffre
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
    partis = {"sms": []}

    def matrix_interdit(*a, **k):
        raise AssertionError("Matrix est arrêté : plus rien ne doit y partir")
    monkeypatch.setattr(matrix, "envoyer_dm", matrix_interdit)
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
    def test_par_defaut_lalerte_part_par_lapplication(self, agent, mairie, habitant, envois):
        avec_appli, sans_appli = habitant("avec-appli"), habitant("sans-appli")
        for h in (avec_appli, sans_appli):
            _abonner(h, mairie)
        notifications_application.enregistrer_appareil(avec_appli, "installation-1")
        defaut = agent.get(URL).data["par_defaut"]
        assert defaut == ["APPLICATION"]
        assert "MATRIX" not in [c["code"] for c in agent.get(URL).data["apercu"]["canaux"]]

        reponse = agent.post(URL, {"titre": "Crue du Gier", "message": "Évacuez le quartier bas.", "canaux": defaut}, format="json")

        assert reponse.status_code == 201, reponse.data
        assert reponse.data["destinataires"] == 2
        assert "MATRIX" not in reponse.data["bilan"]
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
        reponse = agent.post(URL, {"titre": "Crue", "message": "Texte", "canaux": ["INTRAMUROS", "EMAIL"]}, format="json")

        assert reponse.data["bilan"]["INTRAMUROS"]["partis"] == 0 and "pas encore branché" in reponse.data["bilan"]["INTRAMUROS"]["note"]
        assert reponse.data["bilan"]["EMAIL"]["partis"] == 1   # le reste part quand même

    def test_un_canal_en_panne_narrete_pas_les_autres(self, agent, mairie, habitant, monkeypatch):
        cible = habitant("resilient")
        _abonner(cible, mairie)
        notifications_application.enregistrer_appareil(cible, "installation-2")

        def panne(*a, **k):
            raise RuntimeError("application indisponible")
        monkeypatch.setattr(notifications_application, "notifier", panne)

        bilan = agent.post(URL, {"titre": "Crue", "message": "Texte", "canaux": ["APPLICATION", "EMAIL"]}, format="json").data["bilan"]

        assert bilan["APPLICATION"] == {"partis": 0, "echecs": 1, "note": ""} and bilan["EMAIL"]["partis"] == 1

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
        assert NotificationApplication.objects.filter(utilisateur=auteur).count() == 1
        assert not NotificationApplication.objects.filter(utilisateur=cible).exists()
        assert "MATRIX" not in alerte.bilan
        assert alerte.bilan["APPLICATION"]["partis"] == 1 and "vous seul" in alerte.bilan["APPLICATION"]["note"]


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


@pytest.mark.django_db
class TestMoyensDeTerrain:
    """18/11/2026, Sylvain : « Alerte de la population » décrit les moyens ; « Alerter les
    habitants » lance la procédure avec eux. « Tu dois pouvoir cocher porte-à-porte ou sirène :
    ça te sort la fiche pour déclencher la sirène ; pour le porte-à-porte, les contacts, et ça te
    propose de leur envoyer le message à relayer. Chaque action doit être tracée dans la main
    courante / journal de bord de la crise. »"""

    @pytest.fixture
    def moyens(self, agent):
        agent.post("/api/pcs-moyens-alerte/", {"type": "SIRENE", "description": "Toit de la mairie",
                                               "personne": "Paul Garde", "personne_telephone": "+33600000010"}, format="json")
        agent.post("/api/pcs-moyens-alerte/", {"type": "PORTE_A_PORTE", "description": "Quartier de la Rivière",
                                               "personne": "Lina Relais", "personne_telephone": "+33600000011"}, format="json")
        agent.post("/api/pcs-moyens-alerte/", {"type": "VEHICULE", "description": "Fourgon des services techniques"}, format="json")
        return {m["type"]: m for m in agent.get(URL).data["apercu"]["terrain"]}

    @pytest.fixture
    def crise(self, db):
        return Crisis.objects.create(name="Crue du Gier", type="INONDATION", location=Point(4.6, 45.5, srid=4326))

    def test_les_moyens_du_plan_sont_proposes_avec_leur_fiche(self, moyens):
        assert set(moyens) == {"SIRENE", "PORTE_A_PORTE", "VEHICULE"}
        sirene = moyens["SIRENE"]
        assert (sirene["type_libelle"], sirene["description"], sirene["personne"]) == ("Sirène", "Toit de la mairie", "Paul Garde")
        # Pas de fournisseur SMS : on ne promet pas un relais qu'on ne peut pas faire, et on dit pourquoi.
        assert sirene["peut_relayer"] is False and "fournisseur" in sirene["motif_relais"]
        assert "numéro" in moyens["VEHICULE"]["motif_relais"]

    def test_une_alerte_peut_ne_passer_que_par_le_terrain_et_laisse_sa_trace(self, agent, mairie, moyens, crise, envois):
        from core.models import JournalCollectivite
        reponse = agent.post(URL, {"titre": "Évacuation", "message": "Quittez le quartier bas.", "canaux": [],
                                   "terrain": [moyens["SIRENE"]["id"]], "crise": str(crise.id)}, format="json")
        assert reponse.status_code == 201, reponse.data
        (action,) = reponse.data["terrain"]
        assert (action["type_libelle"], action["personne"], action["relais"]) == ("Sirène", "Paul Garde", "")
        # Main courante : le fait et le moyen, jamais le texte de l'alerte ni un numéro.
        (ligne,) = AuditLog.objects.filter(objet_type="MoyenAlertePCS", crise=crise)
        assert "Sirène (Toit de la mairie) — déclenchement demandé" in ligne.commentaire
        assert "Quittez" not in ligne.commentaire and "0600" not in ligne.commentaire
        # Journal de bord de la crise.
        (note,) = JournalCollectivite.objects.filter(crise=crise)
        assert "Sirène" in note.contenu and "Paul Garde" in note.contenu
        assert envois["sms"] == []

    def test_le_message_a_relayer_part_au_porte_a_porte(self, agent, mairie, moyens, crise, envois):
        ConfigurationEnvoiInstitution.objects.create(institution=mairie, fournisseur_sms="brevo", sms_cle_api="cle-de-test", sms_expediteur="Mairie")
        moyens = {m["type"]: m for m in agent.get(URL).data["apercu"]["terrain"]}
        assert moyens["PORTE_A_PORTE"]["peut_relayer"] is True and moyens["VEHICULE"]["peut_relayer"] is False
        ids = [moyens["PORTE_A_PORTE"]["id"], moyens["VEHICULE"]["id"]]
        reponse = agent.post(URL, {"titre": "Évacuation", "message": "Quittez le quartier bas.", "canaux": [],
                                   "terrain": ids, "relayer": ids, "crise": str(crise.id)}, format="json")
        actions = {a["type_libelle"]: a for a in reponse.data["terrain"]}
        assert actions["Porte-à-porte"]["relais"] == "message envoyé par SMS"
        assert envois["sms"] == [("+33600000011", "Évacuation — Quittez le quartier bas.")]
        # Le véhicule n'a pas de numéro : rien ne part, et on le dit.
        assert actions["Véhicule avec haut-parleur"]["relais"] == "" and "numéro" in actions["Véhicule avec haut-parleur"]["note"]

    def test_on_ne_declenche_pas_le_moyen_d_une_autre_commune(self, agent, moyens, create_user, envois):
        itype = InstitutionType.objects.get(code="MAIRIE")
        voisine = Institution.objects.create(nom="Mairie voisine", type=itype, commune_code="42186")
        voisin = create_user(username="voisin@test.fr", email="voisin@test.fr", type="AUT_LOCALE")
        voisin.institution = voisine
        voisin.save()
        client = APIClient()
        client.force_authenticate(user=voisin)
        reponse = client.post(URL, {"titre": "Essai", "message": "Texte", "canaux": ["MATRIX"], "terrain": [moyens["SIRENE"]["id"]]}, format="json")
        assert reponse.status_code == 201 and reponse.data["terrain"] == []
        assert not filtrer_chiffre(AuditLog.objects.filter(objet_type="MoyenAlertePCS"), commentaire__contains="déclenchement").exists()

    def test_sans_canal_ni_moyen_rien_ne_part(self, agent):
        assert agent.post(URL, {"titre": "Crue", "message": "Texte", "canaux": []}, format="json").status_code == 400
