"""Accès au registre communal des personnes vulnérables.

**Changement de règle du 28/10/2026, délibéré.** Jusqu'ici, appartenir à la RCSC ou porter un
rôle RESPONSABLE suffisait à ouvrir le registre, et deux tests de ce fichier l'épinglaient
comme un acquis. L'art. R. 121-7 du CASF exige une désignation *nominative* par le maire : une
appartenance d'équipe est une fonction, pas un acte du maire visant une personne. Ces deux
tests affirment donc maintenant le contraire de ce qu'ils affirmaient — le membre de la RCSC
non désigné est refusé. Ce n'est pas une régression : c'est la règle qui a changé, et la mise
en conformité était la demande.

Ce qui est vérifié ici tient en une phrase : **il faut DEUX actes**, celui de la collectivité
(la désignation) et celui de la personne (l'engagement au secret), et aucun des deux ne vaut
sans l'autre.
"""
import pytest
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    Competence,
    DelegationCompetence,
    HabilitationRegistreVulnerables,
    Institution,
    InstitutionType,
    PersonneVulnerable,
    QualiteDesignataire,
    Team,
    VERSION_ENGAGEMENT_SECRET_REGISTRE,
)
from core.vulnerabilites import (
    NOM_COMPETENCE_VULNERABILITES,
    engagement_secret_signe,
    institution_accede_commune,
)

COMMUNE_CODE = "38185"


@pytest.fixture
def mairie(db):
    itype = InstitutionType.objects.create(code="MAIRIE_VULN_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie vulnerables test", type=itype, commune_code=COMMUNE_CODE)


@pytest.fixture
def association(db):
    itype = InstitutionType.objects.create(code="ASSO_VULN_TEST", libelle="Association")
    return Institution.objects.create(nom="Association vulnerables test", type=itype)


@pytest.fixture
def competence_vulnerables(db):
    # Déjà seedée par la migration 0201_seed_type_vulnerabilite_et_competence -- get_or_create
    # pour ne pas entrer en collision avec cette ligne déjà présente en base de test.
    competence, _ = Competence.objects.get_or_create(nom=NOM_COMPETENCE_VULNERABILITES)
    return competence


@pytest.fixture
def rcsc_team(db, mairie):
    return Team.objects.create(name="RCSC Test", institution=mairie, est_equipe_rcsc=True)


@pytest.fixture
def maire(create_user, mairie):
    """Le premier compte de la mairie : c'est lui qui amorce le dispositif en se désignant."""
    user = create_user(username="maire@test.fr", email="maire@test.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    return user


def _agent(create_user, mairie, nom):
    user = create_user(username=nom, email=nom, type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    return user


def _designer(mairie, utilisateur, par, qualite=QualiteDesignataire.MAIRE):
    return HabilitationRegistreVulnerables.objects.create(
        institution=mairie, utilisateur=utilisateur, accordee_par=par,
        qualite_accordant=qualite, attestation_accordant=True,
    )


def _signer(user):
    user.engagement_secret_registre_le = timezone.now()
    user.engagement_secret_registre_version = VERSION_ENGAGEMENT_SECRET_REGISTRE
    user.save(update_fields=[
        "engagement_secret_registre_le", "engagement_secret_registre_version",
    ])
    return user


def _request_for(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


@pytest.mark.django_db
class TestLesDeuxActes:
    def test_membre_rcsc_non_designe_est_refuse(self, create_user, mairie, rcsc_team):
        """Inversion assumée de l'ancienne règle : l'équipe ne vaut pas désignation.

        C'est le cœur de la mise en conformité R. 121-7. Un agent peut très bien être dans la
        RCSC pour armer un centre d'accueil sans avoir à connaître l'adresse des personnes
        vulnérables de la commune."""
        user = _agent(create_user, mairie, "rcsc-membre@test.fr")
        rcsc_team.members.add(user)
        _signer(user)

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False

    def test_designe_qui_na_pas_signe_est_refuse(self, create_user, mairie, maire):
        """La désignation seule n'ouvre rien : elle ouvre l'écran qui fait signer."""
        user = _agent(create_user, mairie, "designe-non-signe@test.fr")
        _designer(mairie, user, maire)

        assert engagement_secret_signe(user) is False
        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False

    def test_designe_et_signataire_a_acces(self, create_user, mairie, maire):
        user = _agent(create_user, mairie, "designe-signe@test.fr")
        _designer(mairie, user, maire)
        _signer(user)

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is True

    def test_habilitation_retiree_ferme_lacces(self, create_user, mairie, maire):
        user = _agent(create_user, mairie, "retire@test.fr")
        habilitation = _designer(mairie, user, maire)
        _signer(user)
        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is True

        habilitation.actif = False
        habilitation.save(update_fields=["actif"])

        # L'engagement reste signé : c'est bien la désignation qui porte l'accès.
        assert engagement_secret_signe(user) is True
        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False

    def test_habilitation_echue_ferme_lacces(self, create_user, mairie, maire):
        """Une échéance dépassée vaut un retrait -- c'est l'intérêt de la poser sur un
        remplacement saisonnier : elle se referme sans que personne y pense."""
        user = _agent(create_user, mairie, "echu@test.fr")
        habilitation = _designer(mairie, user, maire)
        _signer(user)
        habilitation.date_fin = timezone.now() - timezone.timedelta(minutes=1)
        habilitation.save(update_fields=["date_fin"])

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False

    def test_engagement_sur_une_version_perimee_est_redemande(self, create_user, mairie, maire):
        """Un engagement pris sur un autre texte n'engage à rien : si le texte change, la
        signature est redemandée."""
        user = _agent(create_user, mairie, "ancienne-version@test.fr")
        _designer(mairie, user, maire)
        user.engagement_secret_registre_le = timezone.now()
        user.engagement_secret_registre_version = "1999-01"
        user.save(update_fields=[
            "engagement_secret_registre_le", "engagement_secret_registre_version",
        ])

        assert engagement_secret_signe(user) is False
        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False

    def test_agent_mairie_sans_rien_est_refuse(self, create_user, mairie):
        user = _agent(create_user, mairie, "agent-simple@test.fr")

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False


@pytest.mark.django_db
class TestInstitutionTierceDeleguee:
    def test_delegation_active_et_engagement_signe_donnent_acces(
        self, create_user, mairie, association, competence_vulnerables
    ):
        """Une délégation est elle-même un acte de la mairie : elle n'a pas à être redoublée
        d'une désignation individuelle. Seul l'engagement au secret s'y ajoute."""
        DelegationCompetence.objects.create(
            institution_source=mairie, institution_cible=association,
            competence=competence_vulnerables, active=True,
            communes=[COMMUNE_CODE],
        )
        user = create_user(username="asso-deleguee@test.fr", email="asso-deleguee@test.fr", type="SECOURS")
        user.institution = association
        user.save()
        _signer(user)

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is True

    def test_delegation_active_sans_engagement_est_refusee(
        self, create_user, mairie, association, competence_vulnerables
    ):
        DelegationCompetence.objects.create(
            institution_source=mairie, institution_cible=association,
            competence=competence_vulnerables, active=True,
            communes=[COMMUNE_CODE],
        )
        user = create_user(username="asso-non-signee@test.fr", email="asso-non-signee@test.fr", type="SECOURS")
        user.institution = association
        user.save()

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False

    def test_institution_tierce_sans_delegation_est_refusee(self, create_user, association):
        user = create_user(username="asso-non-deleguee@test.fr", email="asso-non-deleguee@test.fr", type="SECOURS")
        user.institution = association
        user.save()
        _signer(user)

        assert institution_accede_commune(_request_for(user), COMMUNE_CODE) is False


@pytest.mark.django_db
class TestPersonneVulnerableViewSet:
    def _payload(self):
        return {
            "nom": "Dupont", "prenom": "Jeanne", "adresse": "1 rue du Test, 38185",
            "commune_code": COMMUNE_CODE, "mode_consentement": "VOLONTAIRE",
        }

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_creation_refusee_sans_habilitation(self, create_user, mairie):
        user = _agent(create_user, mairie, "agent-refuse@test.fr")
        _signer(user)

        response = self._client(user).post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert response.status_code == 403
        assert "nommément désignées" in str(response.data)

    def test_creation_refusee_tant_que_lengagement_nest_pas_signe(self, create_user, mairie, maire):
        """Le refus doit dire LEQUEL des deux actes manque : c'est le seul moyen pour que la
        page sache quoi proposer, et ici le geste est à un clic de l'utilisateur."""
        user = _agent(create_user, mairie, "non-signe-api@test.fr")
        _designer(mairie, user, maire)

        response = self._client(user).post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert response.status_code == 403
        assert "secret professionnel" in str(response.data)

    def test_creation_acceptee_pour_un_designe_signataire(self, create_user, mairie, maire):
        user = _agent(create_user, mairie, "createur@test.fr")
        _designer(mairie, user, maire)
        _signer(user)

        response = self._client(user).post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert response.status_code == 201, response.data
        personne = PersonneVulnerable.objects.get(pk=response.data["id"])
        assert personne.institution_declarante_id == mairie.id
        assert personne.nom == "Dupont"  # déchiffré transparemment à la lecture ORM

    def test_lecture_fermee_tant_que_lengagement_nest_pas_signe(self, create_user, mairie, maire):
        """La liste doit être vide, et non pas partiellement filtrée : tant que l'engagement
        n'est pas pris, aucune donnée du registre ne sort."""
        redacteur = _agent(create_user, mairie, "redacteur@test.fr")
        _designer(mairie, redacteur, maire)
        _signer(redacteur)
        self._client(redacteur).post("/api/personnes-vulnerables/", self._payload(), format="json")

        lecteur = _agent(create_user, mairie, "lecteur-non-signe@test.fr")
        _designer(mairie, lecteur, maire)

        response = self._client(lecteur).get("/api/personnes-vulnerables/")
        assert response.status_code == 200
        assert response.data == [] or response.data.get("results") == []

    def test_administrateur_lit_mais_nenregistre_pas(self, create_user, mairie, maire):
        """« Par la collectivité et pas l'administrateur » : un administrateur de plateforme est
        sous-traitant au sens du RGPD. Il garde une lecture d'exploitation, journalisée, mais
        inscrire quelqu'un au registre mettrait une personne non désignée par le maire dans la
        chaîne de traitement, ce que R. 121-7 interdit."""
        redacteur = _agent(create_user, mairie, "redacteur-admin@test.fr")
        _designer(mairie, redacteur, maire)
        _signer(redacteur)
        self._client(redacteur).post("/api/personnes-vulnerables/", self._payload(), format="json")

        admin = create_user(username="admin-registre@test.fr", email="admin-registre@test.fr", type="ADMIN")
        _signer(admin)
        client = self._client(admin)

        lecture = client.get("/api/personnes-vulnerables/")
        assert lecture.status_code == 200
        lignes = lecture.data if isinstance(lecture.data, list) else lecture.data["results"]
        assert len(lignes) == 1

        ecriture = client.post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert ecriture.status_code == 403
        assert "collectivité" in str(ecriture.data)

    def test_administrateur_non_signataire_ne_lit_rien(self, create_user, mairie, maire):
        """Le secret professionnel de R. 121-7 vise quiconque traite ces données, éditeur
        compris : pas de dispense d'engagement pour l'administrateur."""
        redacteur = _agent(create_user, mairie, "redacteur-admin2@test.fr")
        _designer(mairie, redacteur, maire)
        _signer(redacteur)
        self._client(redacteur).post("/api/personnes-vulnerables/", self._payload(), format="json")

        admin = create_user(username="admin-non-signe@test.fr", email="admin-non-signe@test.fr", type="ADMIN")

        response = self._client(admin).get("/api/personnes-vulnerables/")
        assert response.status_code == 200
        assert response.data == [] or response.data.get("results") == []

    def test_champs_sensibles_illisibles_en_base_brute(self, create_user, mairie, maire):
        from django.db import connection

        user = _agent(create_user, mairie, "chiffre@test.fr")
        _designer(mairie, user, maire)
        _signer(user)
        response = self._client(user).post("/api/personnes-vulnerables/", self._payload(), format="json")
        assert response.status_code == 201

        with connection.cursor() as cursor:
            cursor.execute("SELECT nom, adresse FROM core_personnevulnerable WHERE id = %s", [response.data["id"]])
            nom_brut, adresse_brut = cursor.fetchone()
        assert "Dupont" not in nom_brut
        assert "Test" not in adresse_brut


@pytest.mark.django_db
class TestDesignationParLAPI:
    URL = "/api/habilitations-registre-vulnerables/"

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_le_maire_se_designe_lui_meme(self, maire, mairie):
        """Amorçage : sans cela, une commune qui démarre n'aurait personne pour ouvrir le
        registre, le premier compte de la mairie étant celui du maire ou d'un adjoint."""
        response = self._client(maire).post(self.URL, {
            "utilisateur": str(maire.id), "qualite_accordant": "MAIRE",
            "attestation_accordant": True, "fonction": "Maire",
        }, format="json")

        assert response.status_code == 201, response.data
        habilitation = HabilitationRegistreVulnerables.objects.get(pk=response.data["id"])
        assert habilitation.institution_id == mairie.id
        assert habilitation.accordee_par_id == maire.id
        assert habilitation.attestation_accordant is True

    def test_un_agent_ne_peut_pas_se_designer_lui_meme(self, create_user, mairie):
        """Tout l'objet de R. 121-7 : l'habilitation émane du maire. Un agent qui s'auto-désigne
        contournerait la désignation."""
        agent = _agent(create_user, mairie, "auto-designation@test.fr")

        response = self._client(agent).post(self.URL, {
            "utilisateur": str(agent.id), "qualite_accordant": "AGENT",
            "attestation_accordant": True,
        }, format="json")

        assert response.status_code == 400
        assert "se désigner lui-même" in str(response.data)

    def test_la_designation_exige_lattestation_sur_lhonneur(self, create_user, mairie, maire):
        agent = _agent(create_user, mairie, "sans-attestation@test.fr")

        response = self._client(maire).post(self.URL, {
            "utilisateur": str(agent.id), "qualite_accordant": "MAIRE",
        }, format="json")

        assert response.status_code == 400
        assert "honneur" in str(response.data)

    def test_la_designation_exige_une_qualite_declaree(self, create_user, mairie, maire):
        agent = _agent(create_user, mairie, "sans-qualite@test.fr")

        response = self._client(maire).post(self.URL, {
            "utilisateur": str(agent.id), "attestation_accordant": True,
        }, format="json")

        assert response.status_code == 400
        assert "quel titre" in str(response.data)

    def test_on_ne_designe_pas_quelquun_dune_autre_collectivite(
        self, create_user, mairie, association, maire
    ):
        etranger = create_user(username="etranger@test.fr", email="etranger@test.fr", type="SECOURS")
        etranger.institution = association
        etranger.save()

        response = self._client(maire).post(self.URL, {
            "utilisateur": str(etranger.id), "qualite_accordant": "MAIRE",
            "attestation_accordant": True,
        }, format="json")

        assert response.status_code == 400
        assert "délégation de compétence" in str(response.data)

    def test_une_seule_habilitation_vivante_par_personne(self, create_user, mairie, maire):
        agent = _agent(create_user, mairie, "doublon@test.fr")
        _designer(mairie, agent, maire)

        response = self._client(maire).post(self.URL, {
            "utilisateur": str(agent.id), "qualite_accordant": "MAIRE",
            "attestation_accordant": True,
        }, format="json")

        assert response.status_code == 400
        assert "déjà habilitée" in str(response.data)

    def test_un_administrateur_ne_designe_pas_a_la_place_du_maire(self, create_user, mairie):
        admin = create_user(username="admin-designe@test.fr", email="admin-designe@test.fr", type="ADMIN")
        admin.institution = mairie
        admin.save()
        agent = _agent(create_user, mairie, "cible-admin@test.fr")

        response = self._client(admin).post(self.URL, {
            "utilisateur": str(agent.id), "qualite_accordant": "MAIRE",
            "attestation_accordant": True,
        }, format="json")

        assert response.status_code == 403
        assert "sous-traitant" in str(response.data)

    def test_le_retrait_exige_un_motif_et_ne_supprime_rien(self, create_user, mairie, maire):
        agent = _agent(create_user, mairie, "a-retirer@test.fr")
        habilitation = _designer(mairie, agent, maire)
        client = self._client(maire)

        sans_motif = client.post(f"{self.URL}{habilitation.id}/retirer/", {}, format="json")
        assert sans_motif.status_code == 400

        avec_motif = client.post(
            f"{self.URL}{habilitation.id}/retirer/", {"motif": "Mutation"}, format="json")
        assert avec_motif.status_code == 200, avec_motif.data

        habilitation.refresh_from_db()
        assert habilitation.actif is False
        assert habilitation.motif_retrait == "Mutation"
        assert habilitation.retiree_par_id == maire.id
        assert habilitation.date_retrait is not None

    def test_une_habilitation_ne_se_supprime_pas(self, create_user, mairie, maire):
        """La trace de qui a été habilité, par qui et jusqu'à quand est ce qui permet de
        répondre, un an plus tard, à « qui avait accès le jour de la canicule ? »."""
        agent = _agent(create_user, mairie, "a-detruire@test.fr")
        habilitation = _designer(mairie, agent, maire)

        response = self._client(maire).delete(f"{self.URL}{habilitation.id}/")

        assert response.status_code == 403
        assert HabilitationRegistreVulnerables.objects.filter(pk=habilitation.id).exists()


@pytest.mark.django_db
class TestMonEtatEtEngagement:
    URL = "/api/habilitations-registre-vulnerables/"

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_mon_etat_annonce_lengagement_a_signer_et_sert_les_textes(
        self, create_user, mairie, maire
    ):
        agent = _agent(create_user, mairie, "etat@test.fr")
        _designer(mairie, agent, maire)

        response = self._client(agent).get(f"{self.URL}mon-etat/")

        assert response.status_code == 200, response.data
        assert response.data["a_un_titre"] is True
        assert response.data["engagement_a_signer"] is True
        assert response.data["engagement_signe"] is False
        assert response.data["lecture_seule_administrateur"] is False
        # Les textes viennent du serveur : un texte juridique signé doit avoir une version et
        # une seule origine, pas une copie dans le code de la page.
        assert "226-13" in response.data["texte_engagement"]
        assert "secret professionnel" in response.data["rappel_bandeau"]
        assert response.data["engagement_version_courante"] == VERSION_ENGAGEMENT_SECRET_REGISTRE

    def test_signer_lengagement_ouvre_lacces(self, create_user, mairie, maire):
        agent = _agent(create_user, mairie, "signature@test.fr")
        _designer(mairie, agent, maire)
        client = self._client(agent)

        response = client.post(f"{self.URL}signer-engagement/", {"accepte": True}, format="json")

        assert response.status_code == 200, response.data
        assert response.data["engagement_signe"] is True
        agent.refresh_from_db()
        assert agent.engagement_secret_registre_version == VERSION_ENGAGEMENT_SECRET_REGISTRE
        assert institution_accede_commune(_request_for(agent), COMMUNE_CODE) is True

    def test_signer_sans_accepter_explicitement_est_refuse(self, create_user, mairie, maire):
        agent = _agent(create_user, mairie, "non-accepte@test.fr")
        _designer(mairie, agent, maire)

        response = self._client(agent).post(
            f"{self.URL}signer-engagement/", {"accepte": False}, format="json")

        assert response.status_code == 400
        agent.refresh_from_db()
        assert agent.engagement_secret_registre_le is None

    def test_sans_titre_il_ny_a_rien_a_signer(self, create_user, mairie):
        """Une signature qui n'engage personne sur rien encombrerait le journal et laisserait
        croire à une habilitation."""
        agent = _agent(create_user, mairie, "sans-titre@test.fr")

        response = self._client(agent).post(
            f"{self.URL}signer-engagement/", {"accepte": True}, format="json")

        assert response.status_code == 403
        agent.refresh_from_db()
        assert agent.engagement_secret_registre_le is None

    def test_mon_etat_previent_ladministrateur_quil_est_en_lecture_seule(self, create_user):
        """Le lui dire plutôt que de le laisser buter sur un 403 au premier enregistrement."""
        admin = create_user(username="admin-etat@test.fr", email="admin-etat@test.fr", type="ADMIN")

        response = self._client(admin).get(f"{self.URL}mon-etat/")

        assert response.status_code == 200
        assert response.data["lecture_seule_administrateur"] is True
        assert response.data["a_un_titre"] is True
        assert response.data["peut_designer"] is False

    def test_chacun_voit_sa_designation_et_celles_de_sa_collectivite(
        self, create_user, mairie, association, maire
    ):
        agent = _agent(create_user, mairie, "visibilite@test.fr")
        _designer(mairie, agent, maire)
        exterieur = create_user(username="exterieur@test.fr", email="exterieur@test.fr", type="SECOURS")
        exterieur.institution = association
        exterieur.save()

        vue_agent = self._client(agent).get(self.URL)
        assert vue_agent.status_code == 200
        lignes = vue_agent.data if isinstance(vue_agent.data, list) else vue_agent.data["results"]
        assert len(lignes) == 1

        vue_exterieure = self._client(exterieur).get(self.URL)
        lignes_ext = (
            vue_exterieure.data if isinstance(vue_exterieure.data, list)
            else vue_exterieure.data["results"]
        )
        assert lignes_ext == []


URL_PDF = "/api/personnes-vulnerables/pdf/"


@pytest.mark.django_db
class TestEditionPdfDuRegistre:
    """L'annexe nominative du plan communal de sauvegarde : elle ne se sort que depuis le
    registre, par quelqu'un qui a les deux actes (désignation et engagement au secret)."""

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _teneur(self, create_user, mairie, maire, nom="teneur-pdf@test.fr"):
        user = _agent(create_user, mairie, nom)
        _designer(mairie, user, maire)
        _signer(user)
        return user

    def _inscrire(self, mairie, nom, commune=COMMUNE_CODE, actif=True, zone=None):
        return PersonneVulnerable.objects.create(
            institution_declarante=mairie, commune_code=commune, zone=zone, nom=nom, prenom="Jeanne",
            adresse="1 rue du Test", mode_consentement="VOLONTAIRE", actif=actif,
        )

    def test_le_teneur_du_registre_obtient_un_pdf_et_lacte_est_trace_sans_les_noms(
            self, create_user, mairie, maire):
        from core.models import AuditLog

        teneur = self._teneur(create_user, mairie, maire)
        inscrite = self._inscrire(mairie, "Dupont")
        self._inscrire(mairie, "Radiee", actif=False)             # radiée : hors du document
        self._inscrire(mairie, "Voisine", commune="38421")        # autre commune : hors du document

        reponse = self._client(teneur).get(URL_PDF)

        assert reponse.status_code == 200
        assert reponse["Content-Type"] == "application/pdf"
        assert reponse.content.startswith(b"%PDF")
        assert COMMUNE_CODE in reponse["Content-Disposition"]

        trace = AuditLog.objects.filter(objet_type="PersonneVulnerable", action__code="EXPORT").latest("date_action")
        assert trace.utilisateur == teneur
        assert trace.objets_ids == [inscrite.id]
        assert "1 fiche(s)" in trace.commentaire
        assert "Dupont" not in trace.commentaire

    def test_refuse_a_qui_nest_pas_designe(self, create_user, mairie):
        agent = _agent(create_user, mairie, "pdf-non-designe@test.fr")
        _signer(agent)

        reponse = self._client(agent).get(URL_PDF)

        assert reponse.status_code == 403
        assert "nommément désignées" in str(reponse.data)

    def test_refuse_tant_que_lengagement_au_secret_nest_pas_signe(self, create_user, mairie, maire):
        agent = _agent(create_user, mairie, "pdf-non-signe@test.fr")
        _designer(mairie, agent, maire)

        reponse = self._client(agent).get(URL_PDF)

        assert reponse.status_code == 403
        assert "secret professionnel" in str(reponse.data)

    def test_ladministrateur_de_la_plateforme_lit_mais_nimprime_pas(self, create_user, mairie, maire):
        """Lire pour exploiter n'est pas sortir la liste sur papier : ce second geste est un
        acte de la collectivité, comme l'inscription."""
        self._inscrire(mairie, "Dupont")
        admin = create_user(username="admin-pdf@test.fr", email="admin-pdf@test.fr", type="ADMIN")
        _signer(admin)

        reponse = self._client(admin).get(URL_PDF, {"commune_code": COMMUNE_CODE})

        assert reponse.status_code == 403
        assert "collectivité" in str(reponse.data)

    def test_on_nimprime_pas_le_registre_dune_autre_commune(self, create_user, mairie, maire):
        teneur = self._teneur(create_user, mairie, maire, "teneur-ailleurs@test.fr")

        reponse = self._client(teneur).get(URL_PDF, {"commune_code": "38421"})

        assert reponse.status_code == 403

    def test_les_fiches_sont_rangees_par_quartier_puis_par_nom(self, mairie):
        from core.models import Zone
        from core.registre_vulnerables_pdf import SANS_QUARTIER, lignes_du_registre

        centre = Zone.objects.create(nom="Centre", institution=mairie)
        bourg = Zone.objects.create(nom="bourg", institution=mairie)
        self._inscrire(mairie, "Zola", zone=centre)
        self._inscrire(mairie, "Sansquartier")
        self._inscrire(mairie, "arnaud", zone=centre)
        self._inscrire(mairie, "Martin", zone=bourg)

        groupes = lignes_du_registre(PersonneVulnerable.objects.filter(institution_declarante=mairie))

        assert [quartier for quartier, _ in groupes] == ["bourg", "Centre", SANS_QUARTIER]
        assert [fiche["nom"] for fiche in groupes[1][1]] == ["arnaud Jeanne", "Zola Jeanne"]

    def test_une_saisie_avec_des_chevrons_ne_fait_pas_echouer_ledition(self):
        """Une adresse comme « Bât. <B> & annexe » est une saisie ordinaire, et le moteur de
        mise en page lit les chevrons comme du balisage."""
        from core.registre_vulnerables_pdf import generer_pdf_registre

        groupes = [("Centre", [{
            "nom": "Dupont Jeanne", "adresse": "Bât. <B> & annexe, 1 rue du Test", "telephone": "",
            "besoins": ["Aide à l'évacuation"], "aidant": "Paul <fils> — 0600000000",
        }])]

        pdf = generer_pdf_registre(groupes, commune="Essai (38185)", edite_par="Agent d'essai")
        vide = generer_pdf_registre([], commune="Essai (38185)", edite_par="Agent d'essai")

        assert pdf.startswith(b"%PDF") and vide.startswith(b"%PDF")


URL_SECTEURS = "/api/personnes-vulnerables/secteurs/"


@pytest.mark.django_db
class TestSecteursSurLaCarte:
    """« Une personne sensible dans les environs » : un cercle, jamais un point. Visible de tous
    les acteurs institutionnels ; rien ne filtre au clic ; en habitat isolé le cercle s'élargit."""

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _teneur(self, create_user, mairie, maire, nom="teneur-carte@test.fr"):
        user = _agent(create_user, mairie, nom)
        _designer(mairie, user, maire)
        _signer(user)
        return user

    def _adresse(self, libelle, longitude, latitude):
        from django.contrib.gis.geos import Point

        from core.models import AdresseSimuleeInondation
        return AdresseSimuleeInondation.objects.create(
            commune_code=COMMUNE_CODE, adresse=libelle, location=Point(longitude, latitude, srid=4326))

    def _bourg(self):
        """Six adresses serrées (une dizaine de mètres d'écart) : le domicile et ses voisins."""
        for i in range(6):
            self._adresse(f"{i + 1} Rue du Bourg 38185 Grenoble", 5.7200 + i * 0.0001, 45.1800)

    def _inscrire(self, mairie, adresse, nom="Dupont"):
        return PersonneVulnerable.objects.create(
            institution_declarante=mairie, commune_code=COMMUNE_CODE, nom=nom, prenom="Jeanne",
            adresse=adresse, mode_consentement="VOLONTAIRE")

    def test_tout_acteur_institutionnel_voit_les_secteurs_mais_pas_le_registre(self, create_user, mairie, maire):
        """Les cercles ne disent rien du registre : toute l'équipe peut les voir. Le registre
        lui-même reste fermé à qui n'est pas désigné, et rien n'est servi sans connexion."""
        self._bourg()
        self._inscrire(mairie, "1 rue du Bourg", nom="Nomtressecret")
        non_designe = _agent(create_user, mairie, "carte-non-designe@test.fr")
        admin = create_user(username="admin-carte@test.fr", email="admin-carte@test.fr", type="ADMIN")

        reponse = self._client(non_designe).get(URL_SECTEURS)
        assert reponse.status_code == 200 and reponse.data["situees"] == 1
        assert "Nomtressecret" not in str(reponse.data)
        assert self._client(non_designe).get("/api/personnes-vulnerables/").data in ([], {"results": []}) \
            or self._client(non_designe).get("/api/personnes-vulnerables/").status_code == 403
        assert self._client(admin).get(URL_SECTEURS, {"commune_code": COMMUNE_CODE}).status_code == 200
        assert APIClient().get(URL_SECTEURS, {"commune_code": COMMUNE_CODE}).status_code in (401, 403)

    def test_le_cercle_contient_le_domicile_sans_etre_centre_dessus_et_ne_porte_rien(self, create_user, mairie, maire):
        from core.models import AuditLog
        from core.secteurs_vulnerables import RAYON_M, _distance_m

        self._bourg()
        fiche = self._inscrire(mairie, "3, rue du Bourg — 38185 Grenoble", nom="Nomtressecret")
        domicile = (5.7202, 45.1800)

        reponse = self._client(self._teneur(create_user, mairie, maire)).get(URL_SECTEURS)

        assert reponse.status_code == 200 and reponse.data["situees"] == 1 and reponse.data["non_situees"] == 0
        assert reponse.data["libelle"] == "Personne sensible dans les environs"
        cercle = reponse.data["features"][0]
        assert cercle["properties"] == {}                       # rien ne filtre au clic
        assert "Nomtressecret" not in str(reponse.data) and str(fiche.id) not in str(reponse.data)
        contour = cercle["geometry"]["coordinates"][0]
        centre = (sum(p[0] for p in contour[:-1]) / (len(contour) - 1), sum(p[1] for p in contour[:-1]) / (len(contour) - 1))
        ecart = _distance_m(centre, domicile)
        assert 0.5 < ecart < RAYON_M                            # ni centré sur la maison, ni à côté d'elle
        assert abs(_distance_m(contour[0], centre) - RAYON_M) < 1   # 100 m en zone habitée
        trace = AuditLog.objects.filter(objet_type="PersonneVulnerable", action__code="LECTURE").latest("date_action")
        assert trace.objets_ids == [fiche.id] and "Nomtressecret" not in trace.commentaire

    def test_le_decalage_est_le_meme_a_chaque_affichage(self, create_user, mairie, maire):
        """Un décalage tiré au hasard à chaque fois se laisserait retrouver en superposant dix
        affichages."""
        self._bourg()
        self._inscrire(mairie, "2 rue du Bourg")
        client = self._client(self._teneur(create_user, mairie, maire))

        premier = client.get(URL_SECTEURS).data["features"][0]["geometry"]
        second = client.get(URL_SECTEURS).data["features"][0]["geometry"]

        assert premier == second

    def test_en_habitat_isole_le_cercle_selargit_jusqua_ne_plus_designer_une_maison(self, create_user, mairie, maire):
        from core.secteurs_vulnerables import RAYON_M, _distance_m

        # Une ferme seule ; ses premiers voisins sont à 300 m environ.
        self._adresse("Lieu-dit Le Mas 38185 Grenoble", 5.8000, 45.2000)
        for i in range(5):
            self._adresse(f"{i + 1} Chemin des Voisins 38185 Grenoble", 5.8038 + i * 0.0001, 45.2000)
        self._inscrire(mairie, "Lieu-dit Le Mas")

        contour = self._client(self._teneur(create_user, mairie, maire)).get(URL_SECTEURS).data["features"][0]["geometry"]["coordinates"][0]

        centre = (sum(p[0] for p in contour[:-1]) / (len(contour) - 1), sum(p[1] for p in contour[:-1]) / (len(contour) - 1))
        rayon = _distance_m(contour[0], centre)
        assert rayon > RAYON_M * 1.5                              # plus large que les 100 m ordinaires
        assert _distance_m(centre, (5.8000, 45.2000)) < rayon     # et la ferme est toujours dedans

    def test_une_fiche_quon_ne_sait_pas_situer_est_comptee_pas_devinee(self, create_user, mairie, maire):
        self._bourg()
        self._inscrire(mairie, "12 impasse Introuvable")

        reponse = self._client(self._teneur(create_user, mairie, maire)).get(URL_SECTEURS)

        assert reponse.data["features"] == [] and reponse.data["non_situees"] == 1 and reponse.data["releve_disponible"] is True

    def test_la_meme_adresse_se_reconnait_ecrite_de_deux_facons(self):
        from core.secteurs_vulnerables import cle_d_adresse

        assert cle_d_adresse("12bis, rue de l'Église 42400 Saint-Chamond") == "12 bis rue de l eglise"
        assert cle_d_adresse("12 BIS Rue de l'Eglise") == "12 bis rue de l eglise"


@pytest.mark.django_db
class TestRattachementAuxAdresses:
    """Chaque fiche du registre se rattache à une adresse de la commune : le lien est enregistré
    une fois (chiffré), la recherche se fait dans le relevé local, et il sert ensuite pour le
    niveau d'eau, la carte et les dégâts constatés."""

    def _client(self, create_user, mairie, maire, nom="teneur-adresses@test.fr"):
        user = _agent(create_user, mairie, nom)
        _designer(mairie, user, maire)
        _signer(user)
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _releve(self):
        from django.contrib.gis.geos import Point

        from core.models import AdresseSimuleeInondation
        lignes = (("38185_0001_00012", "12 Rue de l'Église 38185 Grenoble", 1.5),
                  ("38185_0001_00112", "112 Rue de l'Église 38185 Grenoble", None),
                  ("38185_0002_00003", "3 Chemin du Moulin 38185 Grenoble", 0.5))
        for rang, (ban, libelle, seuil) in enumerate(lignes):
            AdresseSimuleeInondation.objects.create(
                commune_code=COMMUNE_CODE, ban_id=ban, adresse=libelle, seuil_inondation_metres=seuil, altitude_metres=212.0,
                location=Point(5.72 + rang * 0.001, 45.18, srid=4326))

    def _fiche(self, mairie, adresse, nom="Dupont", **champs):
        return PersonneVulnerable.objects.create(
            institution_declarante=mairie, commune_code=COMMUNE_CODE, nom=nom, prenom="Jeanne", adresse=adresse,
            mode_consentement="VOLONTAIRE", **champs)

    def test_la_recherche_dadresse_se_fait_dans_le_releve_local_et_reste_reservee(self, create_user, mairie, maire):
        self._releve()
        client = self._client(create_user, mairie, maire)

        reponse = client.get("/api/personnes-vulnerables/adresses/", {"q": "12 eglise"})

        assert reponse.status_code == 200 and reponse.data["releve_disponible"] is True
        # Le numéro tapé en entier passe devant « 12 » trouvé dans « 112 ».
        assert [a["ban_id"] for a in reponse.data["adresses"]] == ["38185_0001_00012", "38185_0001_00112"]
        assert client.get("/api/personnes-vulnerables/adresses/", {"q": "mo"}).data["adresses"] == []
        non_designe = APIClient()
        non_designe.force_authenticate(user=_signer(_agent(create_user, mairie, "non-designe-adresses@test.fr")))
        assert non_designe.get("/api/personnes-vulnerables/adresses/", {"q": "eglise"}).status_code == 403

    def test_une_fiche_se_cree_rattachee_et_le_lien_est_chiffre_en_base(self, create_user, mairie, maire):
        from django.db import connection

        self._releve()
        client = self._client(create_user, mairie, maire)

        cree = client.post("/api/personnes-vulnerables/", {
            "nom": "Martin", "prenom": "Paul", "adresse": "12 rue de l'église", "adresse_ban_id": "38185_0001_00012",
            "mode_consentement": "VOLONTAIRE", "commune_code": COMMUNE_CODE}, format="json")

        assert cree.status_code == 201, cree.data
        assert cree.data["adresse_ban_id"] == "38185_0001_00012"
        with connection.cursor() as curseur:
            curseur.execute("SELECT adresse_ban_id FROM core_personnevulnerable WHERE id = %s", [cree.data["id"]])
            en_base = curseur.fetchone()[0]
        assert en_base and "38185_0001_00012" not in en_base        # rien en clair
        # Un identifiant qui ne désigne aucune adresse de la commune n'est pas gardé.
        refus = client.post("/api/personnes-vulnerables/", {
            "nom": "Martin", "prenom": "Luc", "adresse": "ailleurs", "adresse_ban_id": "75056_9999_00001",
            "mode_consentement": "VOLONTAIRE", "commune_code": COMMUNE_CODE}, format="json")
        assert refus.status_code == 400 and "adresse_ban_id" in refus.data

    def test_letat_propose_ladresse_identique_ou_les_ressemblantes_et_on_rattache(self, create_user, mairie, maire):
        self._releve()
        exacte = self._fiche(mairie, "3, chemin du Moulin", nom="Exacte")
        proche = self._fiche(mairie, "12 rue de l Eglize", nom="Proche")
        perdue = self._fiche(mairie, "Lieu-dit Les Granges", nom="Perdue")
        self._fiche(mairie, "peu importe", nom="Faite", adresse_ban_id="38185_0001_00112")
        client = self._client(create_user, mairie, maire)

        etat = client.get("/api/personnes-vulnerables/rattachement/").data

        assert etat["fiches"] == 4 and etat["rattachees"] == 1 and etat["exactes"] == 1
        par_id = {fiche["id"]: fiche for fiche in etat["a_rattacher"]}
        assert par_id[str(exacte.id)]["propositions"] == [
            {"ban_id": "38185_0002_00003", "adresse": "3 Chemin du Moulin 38185 Grenoble", "exacte": True}]
        assert par_id[str(proche.id)]["propositions"][0]["ban_id"] == "38185_0001_00012"
        assert par_id[str(proche.id)]["propositions"][0]["exacte"] is False
        assert par_id[str(perdue.id)]["propositions"] == []
        assert etat["a_rattacher"][-1]["id"] == str(perdue.id)        # sans proposition : en fin de liste

        # Les correspondances exactes d'un coup ; les ressemblances, une à une.
        apres = client.post("/api/personnes-vulnerables/rattacher-exactes/", {}, format="json").data
        assert apres["rattachees_a_l_instant"] == 1 and apres["rattachees"] == 2
        assert client.post(f"/api/personnes-vulnerables/{proche.id}/rattacher/", {"ban_id": "38185_0001_00012"},
                           format="json").status_code == 200
        proche.refresh_from_db()
        assert proche.adresse_ban_id == "38185_0001_00012" and proche.adresse == "12 rue de l Eglize"   # texte non réécrit
        assert client.post(f"/api/personnes-vulnerables/{proche.id}/rattacher/", {"ban_id": "inconnu"}, format="json").status_code == 400
        client.post(f"/api/personnes-vulnerables/{proche.id}/rattacher/", {"ban_id": ""}, format="json")
        proche.refresh_from_db()
        assert proche.adresse_ban_id is None

    def test_le_lien_sert_pour_le_niveau_deau_et_les_degats_meme_si_le_texte_ne_se_retrouve_pas(self, create_user, mairie, maire):
        from core.models import Habitation, StatutEvaluationHabitation

        self._releve()
        # Un texte que la comparaison ne retrouverait jamais ; le lien, lui, tient.
        fiche = self._fiche(mairie, "chez sa fille, près de l'église", adresse_ban_id="38185_0001_00012")
        Habitation.objects.create(adresse="12 Rue de l'Église", commune_code=COMMUNE_CODE, ban_id="38185_0001_00012",
                                  statut_evaluation=StatutEvaluationHabitation.DEGATS_FORTS)
        client = self._client(create_user, mairie, maire)

        reponse = client.get("/api/personnes-vulnerables/exposition/").data

        assert reponse["seuils"] == {str(fiche.id): 1.5} and reponse["non_situees"] == 0
        assert reponse["degats"] == {str(fiche.id): "Dégâts forts"}
        assert client.get(URL_SECTEURS).data["situees"] == 1
