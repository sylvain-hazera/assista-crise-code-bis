"""Qui crée une institution, et comment une institution en aide une autre.

Deux décisions de Sylvain du 12/11/2026, prises après une revue d'accès :

1. **« Une association n'a aucune raison de créer une autre institution, sauf une filiale
   fille »** — une association nationale crée son comité départemental, une mairie crée son
   CCAS ou sa médiathèque. Dans les deux cas la fille existe SOUS sa mère. Ce qui est retiré,
   ce n'est pas le droit de créer : c'est le droit de créer À CÔTÉ, au même rang qu'une mairie
   du référentiel national (d'où les « Mairie debug test » qui y traînaient).
2. **« Il faut qu'une institution puisse contacter une institution en situation de crise pour
   proposer son aide »** — le mécanisme existait (déclaration d'acteur, validée par la
   collectivité) ; il manquait le geste et le moyen de savoir à qui parler.

Ce que ces tests tiennent :

- une institution créée par un compte non administrateur est TOUJOURS rattachée à la sienne ;
- les types du référentiel national (mairie, préfecture, SDIS…) lui restent fermés ;
- le rattachement ne se déplace pas depuis le formulaire : il dit qui répond de la fille ;
- l'import en masse, qui crée sans mère, est réservé aux administrateurs ;
- proposer son aide crée bien une déclaration EN ATTENTE pour une association, VALIDÉE pour
  une collectivité, et refuse le doublon en disant où en est la première ;
- la liste des référents donne les coordonnées de l'ORGANISATION, jamais celles du
  responsable : on passe par le standard, comme au téléphone.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Besoin, ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType,
    StatutImplication, TypeImplication, UserRole,
)


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def type_mairie(db):
    t, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie", "est_public": True})
    return t


@pytest.fixture
def type_aasc(db):
    return InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "Association agréée"})[0]


@pytest.fixture
def type_ccas(db):
    return InstitutionType.objects.get_or_create(
        code="CCAS", defaults={"libelle": "CCAS"})[0]


@pytest.fixture
def mairie(db, type_mairie):
    return Institution.objects.create(nom="Mairie de Test Création", type=type_mairie)


@pytest.fixture
def association(db, type_aasc):
    return Institution.objects.create(nom="Association Nationale Test", type=type_aasc)


def _membre(create_user, institution, nom, role=UserRole.ORGANIZED_RESCUE):
    user = create_user(username=f"{nom.lower()}-crea@test.fr",
                       email=f"{nom.lower()}-crea@test.fr", type=role, last_name=nom)
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    user.refresh_from_db()
    return user


class TestQuiPeutCreerUneInstitution:
    def test_une_association_cree_une_fille_rattachee_a_elle(
            self, create_user, association, type_aasc):
        """Le cas nommé : une association nationale crée son comité départemental."""
        membre = _membre(create_user, association, "NATIONAL")

        reponse = _client(membre).post(reverse("institution-list"), {
            "nom": "Comité départemental Test", "type": str(type_aasc.id)}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        fille = Institution.objects.get(nom="Comité départemental Test")
        # Rattachée d'office, sans que personne ne l'ait demandé : c'est la seule valeur
        # possible, la proposer dans le formulaire n'aurait fait qu'ouvrir une faille.
        assert fille.institution_parente_id == association.id

    def test_une_mairie_cree_son_ccas(self, create_user, mairie, type_ccas):
        agent = _membre(create_user, mairie, "AGENT", role=UserRole.LOCAL_AUTHORITY)

        reponse = _client(agent).post(reverse("institution-list"), {
            "nom": "CCAS de Test", "type": str(type_ccas.id)}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert Institution.objects.get(nom="CCAS de Test").institution_parente_id == mairie.id

    def test_le_referentiel_national_reste_ferme(self, create_user, association, type_mairie):
        """LE test. C'est ce qui produisait des « Mairie debug test » au même rang que les
        vraies mairies."""
        membre = _membre(create_user, association, "AMBITIEUX")

        reponse = _client(membre).post(reverse("institution-list"), {
            "nom": "Mairie inventée", "type": str(type_mairie.id)}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert not Institution.objects.filter(nom="Mairie inventée").exists()

    def test_la_parente_envoyee_par_le_client_est_ignoree(
            self, create_user, association, mairie, type_aasc):
        """Sinon la règle ne vaudrait rien : il suffirait de désigner une autre mère."""
        membre = _membre(create_user, association, "MALIN")

        _client(membre).post(reverse("institution-list"), {
            "nom": "Fille détournée", "type": str(type_aasc.id),
            "institution_parente": str(mairie.id)}, format="json")

        assert Institution.objects.get(
            nom="Fille détournée").institution_parente_id == association.id

    def test_un_administrateur_cree_sans_mere(self, create_user, type_mairie):
        """Il tient le référentiel national : lui fermer la porte fermerait la seule qui
        compte."""
        admin = create_user(username="admin-crea@test.fr", email="admin-crea@test.fr",
                            type=UserRole.ADMINISTRATOR)

        reponse = _client(admin).post(reverse("institution-list"), {
            "nom": "Mairie de Vraie Commune", "type": str(type_mairie.id)}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert Institution.objects.get(
            nom="Mairie de Vraie Commune").institution_parente_id is None

    def test_le_rattachement_ne_se_deplace_pas(self, create_user, association, mairie,
                                               type_aasc):
        """Il dit qui répond de cette institution : le laisser modifier permettrait de sortir
        une fille de sa mère sans que personne ne l'ait décidé."""
        membre = _membre(create_user, association, "DEPLACEUR")
        fille = Institution.objects.create(
            nom="Fille à déplacer", type=type_aasc, institution_parente=association)
        ContactInstitution.objects.create(institution=fille, utilisateur=membre, actif=True)

        reponse = _client(membre).patch(
            reverse("institution-detail", args=[str(fille.id)]),
            {"institution_parente": str(mairie.id)}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        fille.refresh_from_db()
        assert fille.institution_parente_id == association.id

    def test_l_import_en_masse_est_reserve_aux_administrateurs(self, create_user, association):
        """Il crée des institutions SANS mère : c'est alimenter le référentiel national."""
        membre = _membre(create_user, association, "IMPORTEUR")

        reponse = _client(membre).post(reverse("import_institutions"), {}, format="multipart")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name="Crue entraide", type="INONDATION",
                                 location="POINT (5.0 45.0)")


@pytest.fixture
def besoin(db):
    return Besoin.objects.get_or_create(nom="Hébergement d'urgence")[0]


class TestProposerSonAide:
    def test_une_association_propose_et_attend_la_collectivite(
            self, create_user, association, crise, besoin):
        """Le mandat exigé d'une association qui n'intervient pas sur délégation."""
        membre = _membre(create_user, association, "VOLONTAIRE")

        reponse = _client(membre).post(
            reverse("crisis-proposer-aide", args=[str(crise.id)]),
            {"themes": [str(besoin.id)], "message": "Nous avons 20 lits disponibles."},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        implication = ImplicationInstitution.objects.get(crise=crise, institution=association)
        assert implication.type_implication == TypeImplication.ACTEUR
        assert implication.statut == StatutImplication.EN_ATTENTE
        assert implication.commentaire == "Nous avons 20 lits disponibles."

    def test_une_collectivite_est_acceptee_d_emblee(self, create_user, mairie, crise, besoin):
        agent = _membre(create_user, mairie, "AGENT2", role=UserRole.LOCAL_AUTHORITY)

        _client(agent).post(reverse("crisis-proposer-aide", args=[str(crise.id)]),
                            {"themes": [str(besoin.id)]}, format="json")

        assert ImplicationInstitution.objects.get(
            crise=crise, institution=mairie).statut == StatutImplication.VALIDEE

    def test_proposer_deux_fois_ne_cree_pas_deux_demandes(
            self, create_user, association, crise, besoin):
        """Une institution impatiente inonderait la collectivité le jour où elle en a le
        moins le temps."""
        membre = _membre(create_user, association, "INSISTANT")
        corps = {"themes": [str(besoin.id)]}
        _client(membre).post(reverse("crisis-proposer-aide", args=[str(crise.id)]),
                             corps, format="json")

        reponse = _client(membre).post(
            reverse("crisis-proposer-aide", args=[str(crise.id)]), corps, format="json")

        assert reponse.status_code == status.HTTP_409_CONFLICT
        assert reponse.data["statut"] == StatutImplication.EN_ATTENTE
        assert ImplicationInstitution.objects.filter(
            crise=crise, institution=association).count() == 1

    def test_sans_besoin_declare_la_proposition_est_refusee(
            self, create_user, association, crise):
        """« Nous pouvons aider » sans dire à quoi ne permet à personne de décider."""
        membre = _membre(create_user, association, "VAGUE")

        reponse = _client(membre).post(
            reverse("crisis-proposer-aide", args=[str(crise.id)]), {"themes": []},
            format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST

    def test_on_ne_propose_pas_au_nom_d_une_institution_etrangere(
            self, create_user, association, mairie, crise, besoin):
        membre = _membre(create_user, association, "USURPATEUR")

        reponse = _client(membre).post(
            reverse("crisis-proposer-aide", args=[str(crise.id)]),
            {"institution": str(mairie.id), "themes": [str(besoin.id)]}, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN


class TestSavoirAQuiParler:
    def test_les_collectivites_sont_en_tete(self, create_user, association, mairie, crise,
                                            besoin):
        """Ce sont elles qui acceptent une offre d'aide : les chercher dans la liste serait
        une perte de temps au mauvais moment."""
        for institution in (association, mairie):
            ImplicationInstitution.objects.create(
                crise=crise, institution=institution, type_implication=TypeImplication.ACTEUR,
                statut=StatutImplication.VALIDEE, environment="PROD")
        demandeur = _membre(create_user, association, "DEMANDEUR")

        reponse = _client(demandeur).get(
            reverse("crisis-referents", args=[str(crise.id)]))

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert reponse.data[0]["autorite_locale"] is True
        assert reponse.data[0]["nom"] == mairie.nom

    def test_les_coordonnees_rendues_sont_celles_de_l_organisation(
            self, create_user, mairie, association, crise):
        """On appelle le standard, pas le portable du responsable."""
        mairie.telephone = "0102030405"
        mairie.email = "contact@mairie-test.invalide"
        mairie.save()
        responsable = _membre(create_user, mairie, "RESPONSABLE",
                              role=UserRole.LOCAL_AUTHORITY)
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE, responsable=responsable, environment="PROD")
        demandeur = _membre(create_user, association, "DEMANDEUR2")

        ligne = _client(demandeur).get(
            reverse("crisis-referents", args=[str(crise.id)])).data[0]

        assert ligne["telephone"] == "0102030405"
        assert ligne["email"] == "contact@mairie-test.invalide"
        assert "RESPONSABLE" in (ligne["responsable_nom"] or "")
        # Et surtout : rien qui permette de joindre cette personne directement.
        assert "responsable_email" not in ligne
        assert "responsable_telephone" not in ligne

    def test_une_declaration_en_attente_n_apparait_pas(self, create_user, association,
                                                       mairie, crise):
        """Elle n'est pas encore un interlocuteur : la montrer ferait appeler quelqu'un qui
        n'a rien accepté."""
        ImplicationInstitution.objects.create(
            crise=crise, institution=association, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.EN_ATTENTE, environment="PROD")
        demandeur = _membre(create_user, mairie, "DEMANDEUR3",
                            role=UserRole.LOCAL_AUTHORITY)

        assert _client(demandeur).get(
            reverse("crisis-referents", args=[str(crise.id)])).data == []


class TestLEquipeNaitAvecLInstitutionFille:
    """Demande de Sylvain du 12/11/2026 : « la création de la médiathèque entraîne la création
    de l'équipe médiathèque, avec leurs coordonnées, et la possibilité de les contacter en
    campagne pour savoir si l'équipe médiathèque peut apporter son soutien pour les
    divertissements sur un centre d'accueil ».

    Une institution est une entité administrative : elle ne reçoit pas de campagne, ne porte
    pas de mission, n'entre pas dans la constitution d'équipe. C'est l'ÉQUIPE qui le fait.
    """

    def test_creer_une_mediatheque_cree_son_equipe(self, create_user, mairie, type_ccas):
        from core.models import Team

        agent = _membre(create_user, mairie, "AGENT3", role=UserRole.LOCAL_AUTHORITY)
        equipe_mairie = Team.objects.create(name="Équipe mairie", institution=mairie,
                                            environment="PROD")

        reponse = _client(agent).post(reverse("institution-list"), {
            "nom": "Médiathèque municipale", "type": str(type_ccas.id)}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        mediatheque = Institution.objects.get(nom="Médiathèque municipale")
        equipe = Team.objects.get(institution=mediatheque)
        assert equipe.name == "Médiathèque municipale"
        # Sous l'équipe de tête de la mère : c'est ce qui permet de la retrouver dans
        # l'arborescence, et de la solliciter avec le reste de la commune.
        assert equipe.equipe_parente_id == equipe_mairie.id
        # Celui qui crée n'en est PAS membre d'office : un DSI crée l'équipe de la
        # médiathèque sans en faire partie (correction de Sylvain).
        assert agent not in equipe.members.all()
        # Mais la réponse dit quelle équipe vient de naître, pour que l'écran propose d'y
        # entrer ou d'y inviter ses membres.
        assert reponse.data["equipe_creee"] == {"id": str(equipe.id), "name": equipe.name}

    def test_l_equipe_se_rattache_a_la_racine_et_non_a_une_sous_equipe(
            self, create_user, mairie, type_ccas):
        """Une mairie a dix équipes ; en choisir une au hasard donnerait un arbre faux."""
        from core.models import Team

        agent = _membre(create_user, mairie, "AGENT4", role=UserRole.LOCAL_AUTHORITY)
        racine = Team.objects.create(name="Racine mairie", institution=mairie,
                                     environment="PROD")
        Team.objects.create(name="Sous-équipe logistique", institution=mairie,
                            equipe_parente=racine, environment="PROD")

        _client(agent).post(reverse("institution-list"), {
            "nom": "CCAS rattaché", "type": str(type_ccas.id)}, format="json")

        equipe = Team.objects.get(institution__nom="CCAS rattaché")
        assert equipe.equipe_parente_id == racine.id

    def test_sans_equipe_chez_la_mere_l_equipe_fille_nait_sans_parente(
            self, create_user, association, type_aasc):
        """La mère n'a pas encore d'équipe : celle de la fille est créée quand même, en
        tête d'arbre. Elle se rattachera quand la mère aura la sienne — mieux vaut une équipe
        à déplacer qu'une institution sans personne à solliciter."""
        from core.models import Team

        membre = _membre(create_user, association, "SANSEQUIPE")

        reponse = _client(membre).post(reverse("institution-list"), {
            "nom": "Comité sans équipe mère", "type": str(type_aasc.id)}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED
        fille = Institution.objects.get(nom="Comité sans équipe mère")
        assert fille.institution_parente_id == association.id
        assert Team.objects.get(institution=fille).equipe_parente_id is None


class TestLaFicheDeLaNotification:
    """« Le régulateur en voit un résumé, clique dessus, et ouvre la fiche de la notification
    avec qui, quand, quoi, comment » (12/11/2026).

    Et les DEUX cas sont notifiés : une collectivité qui engage ses moyens est l'information
    la plus utile de la journée, même si aucune validation n'est requise."""

    def _regulateur(self, create_user, mairie, crise):
        from core.models import ImplicationInstitution

        regulateur = _membre(create_user, mairie, "REGUL", role=UserRole.LOCAL_AUTHORITY)
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE, responsable=regulateur, environment="PROD")
        return regulateur

    def test_la_notification_porte_qui_quand_quoi_comment(
            self, create_user, mairie, association, crise, besoin):
        from core.models import Notification

        regulateur = self._regulateur(create_user, mairie, crise)
        association.telephone = "0199887766"
        association.save()
        membre = _membre(create_user, association, "PROPOSANT")

        _client(membre).post(reverse("crisis-proposer-aide", args=[str(crise.id)]),
                             {"themes": [str(besoin.id)], "message": "20 lits disponibles"},
                             format="json")

        notification = Notification.objects.filter(utilisateur=regulateur).latest(
            "date_creation")
        libelles = {d["libelle"]: d["valeur"] for d in notification.details}
        assert libelles["Qui"] == association.nom
        assert "Quand" in libelles
        assert libelles["Sur quels besoins"] == besoin.nom
        assert "0199887766" in libelles["Comment les joindre"]
        assert libelles["Ce qu'ils proposent"] == "20 lits disponibles"
        # Et le clic mène quelque part, avec un bouton qui dit où.
        assert notification.lien == f"/admin/crises?id={crise.id}"
        assert notification.lien_libelle == "Ouvrir la crise"

    def test_une_collectivite_qui_s_engage_notifie_aussi(
            self, create_user, mairie, crise, besoin, type_mairie):
        """Avant, seule une déclaration EN ATTENTE prévenait quelqu'un : personne
        n'apprenait qu'une mairie voisine venait d'engager ses moyens."""
        from core.models import Notification

        regulateur = self._regulateur(create_user, mairie, crise)
        voisine = Institution.objects.create(nom="Mairie Voisine Renfort", type=type_mairie)
        agent = _membre(create_user, voisine, "VOISIN")

        _client(agent).post(reverse("crisis-proposer-aide", args=[str(crise.id)]),
                            {"themes": [str(besoin.id)]}, format="json")

        notification = Notification.objects.filter(utilisateur=regulateur).latest(
            "date_creation")
        assert "Mairie Voisine Renfort" in notification.titre
        libelles = {d["libelle"]: d["valeur"] for d in notification.details}
        assert "Aucune action attendue" in libelles["Ce qui est attendu de vous"]

    def test_la_fiche_ne_porte_aucune_donnee_personnelle(
            self, create_user, mairie, association, crise, besoin):
        """`details` n'est pas chiffré : on n'y met que ce qui peut être lu en clair dans la
        base — noms d'institutions, dates, libellés de besoin."""
        from core.models import Notification

        regulateur = self._regulateur(create_user, mairie, crise)
        membre = _membre(create_user, association, "DISCRET")

        _client(membre).post(reverse("crisis-proposer-aide", args=[str(crise.id)]),
                             {"themes": [str(besoin.id)]}, format="json")

        notification = Notification.objects.filter(utilisateur=regulateur).latest(
            "date_creation")
        contenu = " ".join(str(d["valeur"]) for d in notification.details)
        assert membre.email not in contenu
        assert "DISCRET" not in contenu


class TestEntrerOuInviterDansLEquipeFille:
    """« La création de l'équipe doit lui proposer de rentrer ou d'inviter les membres de la
    médiathèque via leur adresse mail » (Sylvain, 12/11/2026)."""

    def _mediatheque(self, create_user, mairie, type_ccas):
        from core.models import Team

        agent = _membre(create_user, mairie, "DSI", role=UserRole.LOCAL_AUTHORITY)
        Team.objects.create(name="Équipe mairie", institution=mairie, environment="PROD")
        _client(agent).post(reverse("institution-list"), {
            "nom": "Médiathèque à peupler", "type": str(type_ccas.id)}, format="json")
        fille = Institution.objects.get(nom="Médiathèque à peupler")
        return agent, fille, Team.objects.get(institution=fille)

    def test_le_createur_peut_choisir_d_y_entrer(self, create_user, mairie, type_ccas):
        agent, _fille, equipe = self._mediatheque(create_user, mairie, type_ccas)

        reponse = _client(agent).post(reverse("team-rejoindre", args=[str(equipe.id)]))

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert agent in equipe.members.all()

    def test_la_mere_invite_par_email_dans_l_equipe_de_sa_fille(
            self, create_user, mairie, type_ccas):
        """Sinon l'équipe naîtrait vide et le resterait : personne à la médiathèque n'a
        encore de compte pour s'inviter lui-même."""
        agent, fille, equipe = self._mediatheque(create_user, mairie, type_ccas)

        reponse = _client(agent).post(
            reverse("contactinstitution-inviter"),
            {"institution": str(fille.id), "equipe": str(equipe.id),
             "email": "bibliothecaire@essai.invalide"}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        invite = equipe.members.get()
        assert invite.email == "bibliothecaire@essai.invalide"
        assert ContactInstitution.objects.filter(
            institution=fille, utilisateur=invite).exists()

    def test_un_etranger_n_invite_pas_chez_la_fille(
            self, create_user, mairie, association, type_ccas):
        _agent, fille, equipe = self._mediatheque(create_user, mairie, type_ccas)
        etranger = _membre(create_user, association, "CURIEUX")

        reponse = _client(etranger).post(
            reverse("contactinstitution-inviter"),
            {"institution": str(fille.id), "equipe": str(equipe.id),
             "email": "intrus@essai.invalide"}, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_la_fille_n_agit_pas_pour_la_mere(self, create_user, mairie, type_ccas):
        """La hiérarchie descend, elle ne remonte pas."""
        from core.models import Team

        _agent, fille, _equipe = self._mediatheque(create_user, mairie, type_ccas)
        bibliothecaire = _membre(create_user, fille, "BIBLIO")
        equipe_mairie = Team.objects.get(name="Équipe mairie")

        reponse = _client(bibliothecaire).post(
            reverse("team-rejoindre", args=[str(equipe_mairie.id)]))

        assert reponse.status_code == status.HTTP_403_FORBIDDEN


class TestLesAtouts:
    """« Vous avez une médiathèque ? → divertissements. Une cantine scolaire ? → repas. »
    Partir de ce que l'institution POSSÈDE, proposer une idée, n'engager personne."""

    def test_le_catalogue_pose_des_questions_et_propose_des_idees(self, create_user, mairie):
        agent = _membre(create_user, mairie, "LECTEUR", role=UserRole.LOCAL_AUTHORITY)

        catalogue = _client(agent).get(reverse("institution-catalogue-atouts")).data

        loisirs = next(a for a in catalogue if a["cle"] == "LOISIRS")
        assert "médiathèque" in loisirs["question"]
        assert loisirs["besoin"] == "Se divertir"
        # Chaque entrée porte les quatre éléments : sans l'idée, ce n'est qu'un inventaire.
        assert all(a["question"] and a["besoin"] and a["idee"] for a in catalogue)

    def test_aucun_atout_ne_releve_du_soin(self):
        """Respirer, le pouls, la douleur : c'est le métier des secours, pas le nôtre."""
        from core.atouts import CATALOGUE

        import re

        texte = " ".join(f"{a['question']} {a['besoin']} {a['idee']}" for a in CATALOGUE).lower()
        # Mots entiers : « soin » est aussi dans « besoin », qui n'a rien de médical.
        for motif in (r"respir", r"médic", r"\bsoins?\b", r"bless", r"douleur"):
            assert not re.search(motif, texte), motif

    def test_une_institution_declare_ses_atouts(self, create_user, mairie):
        agent = _membre(create_user, mairie, "DECLARANT", role=UserRole.LOCAL_AUTHORITY)

        reponse = _client(agent).patch(
            reverse("institution-detail", args=[str(mairie.id)]),
            {"atouts": ["LOISIRS", "CUISINE", "LOISIRS"]}, format="json")

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        mairie.refresh_from_db()
        assert mairie.atouts == ["CUISINE", "LOISIRS"]

    def test_un_atout_invente_est_refuse(self, create_user, mairie):
        agent = _membre(create_user, mairie, "INVENTEUR", role=UserRole.LOCAL_AUTHORITY)

        reponse = _client(agent).patch(
            reverse("institution-detail", args=[str(mairie.id)]),
            {"atouts": ["HELIPORT"]}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST

    def test_les_referents_disent_ce_que_chacun_peut_apporter(
            self, create_user, mairie, association, crise):
        """Savoir qu'il y a déjà une cuisine sur place évite d'en proposer une seconde."""
        mairie.atouts = ["CUISINE", "DOUCHES"]
        mairie.save()
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE, environment="PROD")
        demandeur = _membre(create_user, association, "DEMANDEUR4")

        ligne = _client(demandeur).get(
            reverse("crisis-referents", args=[str(crise.id)])).data[0]

        assert ligne["peut_apporter"] == ["Boire et manger", "Être propre"]


class TestLaMainCouranteNeSeTrompePasDeCrise:
    def test_proposer_son_aide_n_ecrit_pas_une_crise_fantome(
            self, create_user, mairie, association, crise, besoin):
        """Défaut trouvé le 12/11/2026 : `proposer-aide` rend une implication, et son `id`
        était pris pour celui d'une crise par la traçabilité — une ligne de main courante
        partait avec une clé vers une crise inexistante."""
        from core.models import AuditLog

        regulateur = _membre(create_user, mairie, "REGUL2", role=UserRole.LOCAL_AUTHORITY)
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE, responsable=regulateur, environment="PROD")
        membre = _membre(create_user, association, "PROPOSANT2")

        _client(membre).post(reverse("crisis-proposer-aide", args=[str(crise.id)]),
                             {"themes": [str(besoin.id)]}, format="json")

        crises_citees = set(AuditLog.objects.exclude(crise_id=None)
                            .values_list("crise_id", flat=True))
        assert crises_citees <= {crise.id}
