"""Le document du plan communal de sauvegarde : construit depuis ce qui existe déjà, il reprend
les textes de la commune tels quels, dit ce qui manque, et ne porte jamais le registre des
personnes vulnérables."""
from core.tests.outils_chiffre import filtrer_chiffre
import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core import document_pcs
from core.models import (
    AuditLog, CategorieInterlocuteurPCS, ContactInstitution, DossierPCS, ExercicePCS, FonctionPCS, Institution,
    InstitutionType, MoyenAlertePCS,
    InterlocuteurAlertePCS, PersonneVulnerable, Plan, PlanMissionModele, PointOperationnel, PointType,
    RevisionPCS, RisqueCommunal, RisqueMajeurType, Team,
)

URL = "/api/dossier-pcs/"


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie du document", type=itype, commune_code="42207")


@pytest.fixture
def agent(create_user, mairie):
    user = create_user(username="agent-pcs@test.fr", email="agent-pcs@test.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True, fonction="Secrétaire de mairie")
    return user


@pytest.fixture
def client(agent):
    c = APIClient()
    c.force_authenticate(user=agent)
    return c


def _plan_complet(mairie):
    """Ce qu'une commune a déjà saisi ailleurs dans l'application."""
    inondation = RisqueMajeurType.objects.get_or_create(nom="Inondation")[0]
    inondation.generalites = "Texte générique sur l'inondation."
    inondation.save()
    risque = RisqueCommunal.objects.create(
        institution=mairie, risque_type=inondation,
        etat_des_lieux="Le Gier déborde <rive gauche> & inonde le quartier bas.", enjeux="École Jean-Jaurès.")
    equipe = Team.objects.create(name="Équipe logistique", institution=mairie)
    type_point = PointType.objects.get_or_create(code="CARE_TEST", defaults={"libelle": "Centre d'accueil"})[0]
    gymnase = PointOperationnel.objects.create(nom="Gymnase municipal", type=type_point, capacite_accueil=120,
                                               adresse="2 rue du Stade")
    plan = Plan.objects.create(institution=mairie, nom="Dispositif inondation", description="Évacuation du quartier bas.")
    plan.risques.add(risque)
    plan.equipes.add(equipe)
    plan.points.add(gymnase)
    PlanMissionModele.objects.create(plan=plan, equipe=equipe, titre="Ouvrir le gymnase",
                                     description="Prendre les clés en mairie, allumer le chauffage.")
    for categorie, nom in ((CategorieInterlocuteurPCS.PREFECTURE, "SIDPC 42"), (CategorieInterlocuteurPCS.SDIS, "CODIS 42"),
                           (CategorieInterlocuteurPCS.GENDARMERIE_POLICE, "Brigade de Saint-Chamond")):
        i = InterlocuteurAlertePCS.objects.create(nom=nom, categorie=categorie, telephone="0477000000", environment="PROD")
        i.institutions.add(mairie)
    dossier = document_pcs.dossier_de(mairie, "PROD")
    dossier.arrete_numero, dossier.arrete_date = "2026-014", datetime.date(2026, 3, 2)
    dossier.lieu_pcc, dossier.modalites_activation = "Salle du conseil", "Le maire déclenche le plan dès la vigilance orange."
    dossier.save()
    for fonction, titulaire in ((FonctionPCS.Fonction.DOS, "Maire d'essai"), (FonctionPCS.Fonction.COORDINATION, "Adjointe d'essai")):
        FonctionPCS.objects.create(dossier=dossier, fonction=fonction, titulaire=titulaire, titulaire_telephone="0600000001",
                                   suppleant="Suppléant d'essai", suppleant_telephone="0600000002")
    MoyenAlertePCS.objects.create(dossier=dossier, type=MoyenAlertePCS.Type.SIRENE, description="Toit de la mairie")
    ExercicePCS.objects.create(dossier=dossier, date=timezone.localdate(), theme="Crue du Gier",
                               enseignements="Le gymnase n'avait pas de clés en mairie.")
    return plan


@pytest.mark.django_db
class TestRassembler:
    def test_reprend_tels_quels_les_textes_deja_rediges_par_la_commune(self, mairie, agent):
        _plan_complet(mairie)

        contenu = document_pcs.rassembler(mairie, "PROD")

        risque = contenu["risques"][0]
        assert risque["generalites"] == "Texte générique sur l'inondation."
        assert risque["etat_des_lieux"] == "Le Gier déborde <rive gauche> & inonde le quartier bas."
        dispositif = contenu["dispositifs"][0]
        assert dispositif["description"] == "Évacuation du quartier bas."
        assert dispositif["missions"][0]["description"] == "Prendre les clés en mairie, allumer le chauffage."
        assert contenu["points"][0]["capacite"] == 120
        # Le gymnase est au plan et la simulation n'a pas tourné : on ne sait pas si l'eau l'atteint.
        assert {m["partie"] for m in contenu["manques"]} == {"Enjeux", "Enjeux exposés", "Zones"}

    def test_un_plan_vide_dit_partie_par_partie_ce_qui_manque_et_ou_le_saisir(self, mairie):
        contenu = document_pcs.rassembler(mairie, "PROD")

        parties = [m["partie"] for m in contenu["manques"]]
        for attendue in ("Arrêté", "Risques", "Enjeux", "Activation", "Organisation", "Dispositifs",
                         "Annuaire de crise", "Soutien de la population", "Moyens humains",
                         "Poste de commandement", "Alerte de la population", "Exercices"):
            assert attendue in parties
        # Chaque manque mène quelque part : un écran nommé pour le papier, une adresse pour l'application.
        assert all(m["ou"] and m["route"].startswith("/admin/") for m in contenu["manques"])

    def test_signale_un_plan_qui_na_pas_ete_revu_depuis_cinq_ans(self, mairie):
        dossier = document_pcs.dossier_de(mairie, "PROD")
        dossier.arrete_numero, dossier.arrete_date = "2019-003", datetime.date(2019, 1, 10)
        dossier.save()

        assert "Mises à jour" in [m["partie"] for m in document_pcs.rassembler(mairie, "PROD")["manques"]]

        RevisionPCS.objects.create(dossier=dossier, date=timezone.localdate(), objet="Annuaire revu")
        assert "Mises à jour" not in [m["partie"] for m in document_pcs.rassembler(mairie, "PROD")["manques"]]

    def test_lannuaire_sans_prefecture_ni_secours_est_signale(self, mairie):
        i = InterlocuteurAlertePCS.objects.create(nom="Radio locale", categorie=CategorieInterlocuteurPCS.MEDIA,
                                                  environment="PROD")
        i.institutions.add(mairie)

        manque = next(m for m in document_pcs.rassembler(mairie, "PROD")["manques"] if m["partie"] == "Annuaire de crise")

        assert "Préfecture" in manque["message"] and "SDIS" in manque["message"]

    def test_ne_melange_pas_les_donnees_dune_autre_collectivite_ni_de_la_zone_de_demonstration(self, mairie):
        autre = Institution.objects.create(nom="Autre mairie", type=mairie.type, commune_code="42218")
        Plan.objects.create(institution=autre, nom="Dispositif d'ailleurs")
        Plan.objects.create(institution=mairie, nom="Dispositif de démonstration", environment="DEMO")

        assert document_pcs.rassembler(mairie, "PROD")["dispositifs"] == []
        assert [d["nom"] for d in document_pcs.rassembler(mairie, "DEMO")["dispositifs"]] == ["Dispositif de démonstration"]


@pytest.mark.django_db
class TestDocument:
    def test_le_pdf_sort_meme_avec_des_chevrons_dans_les_textes_et_meme_vide(self, mairie, agent):
        vide = document_pcs.generer_pdf(document_pcs.rassembler(mairie, "PROD"), edite_par="Agent d'essai")
        _plan_complet(mairie)
        plein = document_pcs.generer_pdf(document_pcs.rassembler(mairie, "PROD"), edite_par="Agent d'essai")

        assert vide.startswith(b"%PDF") and plein.startswith(b"%PDF")
        assert len(plein) > len(vide)

    def test_le_registre_des_personnes_vulnerables_ny_figure_jamais(self, mairie, agent):
        """Le document circule ; la liste nominative s'édite à part, depuis le registre."""
        PersonneVulnerable.objects.create(
            institution_declarante=mairie, commune_code="42207", nom="Nomtressecret", prenom="Jeanne",
            adresse="9 impasse Introuvable", mode_consentement="VOLONTAIRE")
        _plan_complet(mairie)

        contenu = document_pcs.rassembler(mairie, "PROD")

        assert "Nomtressecret" not in repr(contenu) and "impasse Introuvable" not in repr(contenu)

    def test_ledition_est_reservee_aux_comptes_institutionnels_et_inscrite_a_la_main_courante(
            self, client, mairie, create_user):
        _plan_complet(mairie)

        reponse = client.get(URL + "document/")

        assert reponse.status_code == 200
        assert reponse["Content-Type"] == "application/pdf" and reponse.content.startswith(b"%PDF")
        assert "42207" in reponse["Content-Disposition"]
        trace = AuditLog.objects.filter(objet_type="DossierPCS", action__code="EXPORT").latest("date_action")
        assert "Mairie du document" in trace.commentaire

        habitant = create_user(username="habitant-pcs@test.fr", email="habitant-pcs@test.fr", type="UTIL_SIMPLE")
        autre = APIClient()
        autre.force_authenticate(user=habitant)
        assert autre.get(URL + "document/").status_code == 403
        assert APIClient().get(URL + "document/").status_code in (401, 403)

    def test_un_compte_institutionnel_sans_collectivite_na_pas_de_plan(self, create_user):
        seul = create_user(username="sans-mairie@test.fr", email="sans-mairie@test.fr", type="AUT_LOCALE")
        c = APIClient()
        c.force_authenticate(user=seul)

        assert c.get(URL).status_code == 403


@pytest.mark.django_db
class TestDossier:
    def test_letat_dit_ce_que_le_document_reprendra_et_ce_qui_manque(self, client, mairie):
        _plan_complet(mairie)

        etat = client.get(URL).data

        assert etat["arrete_numero"] == "2026-014"
        assert etat["contenu"]["dispositifs"] == 1 and etat["contenu"]["missions_types"] == 1
        assert etat["contenu"]["interlocuteurs"] == 3
        assert [m["partie"] for m in etat["manques"]] == ["Enjeux", "Enjeux exposés", "Zones"]

    def test_chaque_paragraphe_du_plan_a_son_ecran_son_utilite_et_son_etat(self, client, mairie):
        """La table des matières du plan : un paragraphe sans écran ne se remplit pas, et un
        paragraphe sans usage en crise ne sert qu'à remplir un classeur."""
        _plan_complet(mairie)

        paragraphes = client.get(URL).data["paragraphes"]

        assert all(p["route"].startswith("/admin/") and p["reutilise"] for p in paragraphes)
        etat = {p["titre"]: p["etat"] for p in paragraphes}
        assert etat["Risques de la commune"] == "RENSEIGNE" and etat["Annuaire de crise"] == "RENSEIGNE"
        assert etat["Sites sensibles"] == "VIDE" and etat["Zones et quartiers"] == "VIDE"
        # Le registre ne se compte pas d'ici : il a ses propres droits.
        assert etat["Personnes vulnérables"] == "A_PART"

    def test_labsence_de_quartiers_est_dite_sans_empecher_quoi_que_ce_soit(self, client, mairie):
        zones = next(m for m in client.get(URL).data["manques"] if m["partie"] == "Zones")

        assert "Rien n'en dépend pour ouvrir une crise" in zones["message"]
        assert zones["route"] == "/admin/zones"

    def test_la_partie_administrative_se_complete_et_la_modification_est_tracee(self, client, mairie):
        reponse = client.patch(URL, {"arrete_numero": "2026-021", "arrete_date": "2026-11-16",
                                     "lieu_pcc": "Salle du conseil", "modalites_activation": "Sur décision du maire."},
                               format="json")

        assert reponse.status_code == 200
        dossier = DossierPCS.objects.get(institution=mairie)
        assert dossier.arrete_date == datetime.date(2026, 11, 16) and dossier.lieu_pcc == "Salle du conseil"
        assert "Arrêté" not in [m["partie"] for m in reponse.data["manques"]]
        assert AuditLog.objects.filter(objet_type="DossierPCS", action__code="MODIFICATION").exists()
        assert client.patch(URL, {"arrete_date": "16/11/2026"}, format="json").status_code == 400

    def test_une_mise_a_jour_sajoute_au_tableau_et_ne_se_date_pas_dans_le_futur(self, client, mairie, agent):
        reponse = client.post(URL + "revisions/", {"objet": "Annuaire de crise revu"}, format="json")

        assert reponse.status_code == 201
        revision = RevisionPCS.objects.get()
        assert revision.auteur == agent and revision.date == timezone.localdate()
        assert reponse.data["revisions"][0]["objet"] == "Annuaire de crise revu"

        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        assert client.post(URL + "revisions/", {"objet": "x", "date": demain}, format="json").status_code == 400
        assert client.post(URL + "revisions/", {"objet": "  "}, format="json").status_code == 400

    def test_chaque_collectivite_na_que_son_propre_dossier(self, client, mairie, create_user):
        client.patch(URL, {"arrete_numero": "2026-021"}, format="json")
        autre_mairie = Institution.objects.create(nom="Mairie voisine", type=mairie.type, commune_code="42218")
        voisin = create_user(username="voisin-pcs@test.fr", email="voisin-pcs@test.fr", type="AUT_LOCALE")
        voisin.institution = autre_mairie
        voisin.save()
        c = APIClient()
        c.force_authenticate(user=voisin)

        assert c.get(URL).data["arrete_numero"] == ""


@pytest.mark.django_db
class TestUnPlanIncompletNempecheRien:
    """La règle de conception : dans l'urgence on fait avec ce qu'on a, et l'on revient compléter.
    Rien de ce que `manques` relève n'est un préalable à l'ouverture d'une crise."""

    CRISE = {"name": "Crue du Gier", "type": "INONDATION", "location": "POINT (4.51 45.47)", "radius": 5}

    def test_une_crise_souvre_sans_quartiers_sans_dispositif_et_sans_annuaire(self, client, mairie):
        avant = [m["partie"] for m in client.get(URL).data["manques"]]
        assert {"Zones", "Dispositifs", "Annuaire de crise"} <= set(avant)

        reponse = client.post("/api/crises/", self.CRISE, format="json")

        assert reponse.status_code == 201, reponse.data
        # … et le plan reste lisible, avec les mêmes points à reprendre après coup.
        assert [m["partie"] for m in client.get(URL).data["manques"]] == avant

    def test_un_dispositif_sans_zone_ni_mission_type_sactive_quand_meme(self, client, mairie):
        plan = Plan.objects.create(institution=mairie, nom="Dispositif à peine commencé")
        equipe = Team.objects.create(name="Équipe du jour", institution=mairie)
        plan.equipes.add(equipe)

        reponse = client.post(f"/api/plans/{plan.id}/activer/", {"nouvelle_crise": self.CRISE}, format="json")

        assert reponse.status_code in (200, 201), reponse.data


@pytest.mark.django_db
class TestPosteDeCommandementAlerteExercices:
    """Trois paragraphes tenus en liste : organigramme et fiches réflexes, moyens d'alerte,
    exercices. Même API, toujours bornée à la collectivité de l'appelant."""

    def test_une_fonction_sans_fiche_ecrite_sort_avec_la_fiche_type_de_la_trame(self, client, mairie):
        reponse = client.post("/api/pcs-fonctions/", {"fonction": "SECRETARIAT", "titulaire": "Secrétaire d'essai"}, format="json")

        assert reponse.status_code == 201, reponse.data
        assert "journal de bord" in reponse.data["fiche_type"]
        fiche = document_pcs.rassembler(mairie, "PROD")["fonctions"][0]
        assert "Tient le standard" in fiche["consignes"] and fiche["fiche_propre"] is False

        client.patch(f"/api/pcs-fonctions/{reponse.data['id']}/", {"consignes": "Ouvrir la salle du conseil."}, format="json")
        fiche = document_pcs.rassembler(mairie, "PROD")["fonctions"][0]
        assert fiche["consignes"] == "Ouvrir la salle du conseil." and fiche["fiche_propre"] is True

    def test_les_noms_et_telephones_de_lorganigramme_sont_illisibles_en_base_brute(self, client, mairie):
        from django.db import connection

        reponse = client.post("/api/pcs-fonctions/", {"fonction": "DOS", "titulaire": "Nomdumaire", "titulaire_telephone": "0611223344"}, format="json")

        with connection.cursor() as curseur:
            curseur.execute("SELECT titulaire, titulaire_telephone FROM core_fonctionpcs WHERE id = %s", [reponse.data["id"]])
            nom, telephone = curseur.fetchone()
        assert "Nomdumaire" not in nom and "0611223344" not in telephone

    def test_lorganigramme_signale_labsence_de_coordinateur_puis_de_suppleant(self, client, mairie):
        def manque():
            return next((m["message"] for m in client.get(URL).data["manques"] if m["partie"] == "Poste de commandement"), None)

        assert "vide" in manque()
        dos = client.post("/api/pcs-fonctions/", {"fonction": "DOS", "titulaire": "Maire"}, format="json").data
        assert "coordinateur" in manque()
        coordination = client.post("/api/pcs-fonctions/", {"fonction": "COORDINATION", "titulaire": "Adjointe"}, format="json").data
        assert "suppléant" in manque()
        for ligne in (dos, coordination):
            client.patch(f"/api/pcs-fonctions/{ligne['id']}/", {"suppleant": "Suppléant"}, format="json")
        assert manque() is None

    def test_un_moyen_dalerte_ne_se_rattache_qua_un_quartier_de_sa_collectivite(self, client, mairie):
        from core.models import Zone

        autre = Institution.objects.create(nom="Mairie voisine", type=mairie.type, commune_code="42218")
        quartier = Zone.objects.create(nom="Quartier bas", institution=mairie)
        ailleurs = Zone.objects.create(nom="Quartier d'ailleurs", institution=autre)

        ok = client.post("/api/pcs-moyens-alerte/", {"type": "RELAIS", "zone": str(quartier.id), "personne": "Relais d'essai",
                                                     "personne_telephone": "0600000003"}, format="json")
        refus = client.post("/api/pcs-moyens-alerte/", {"type": "RELAIS", "zone": str(ailleurs.id)}, format="json")

        assert ok.status_code == 201 and ok.data["zone_nom"] == "Quartier bas"
        assert refus.status_code == 400

    def test_un_exercice_se_consigne_apres_coup_et_ses_enseignements_entrent_au_document(self, client, mairie):
        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        assert client.post("/api/pcs-exercices/", {"date": demain, "theme": "x"}, format="json").status_code == 400

        reponse = client.post("/api/pcs-exercices/", {"date": timezone.localdate().isoformat(), "theme": "Crue du Gier",
                                                      "enseignements": "Prévoir un double des clés."}, format="json")

        assert reponse.status_code == 201
        contenu = document_pcs.rassembler(mairie, "PROD")
        assert contenu["exercices"][0]["enseignements"] == "Prévoir un double des clés."
        assert document_pcs.generer_pdf(contenu, edite_par="Agent d'essai").startswith(b"%PDF")

    def test_une_collectivite_ne_voit_ni_ne_modifie_les_listes_dune_autre(self, client, mairie, create_user):
        ligne = client.post("/api/pcs-fonctions/", {"fonction": "DOS", "titulaire": "Maire"}, format="json").data
        autre = Institution.objects.create(nom="Mairie voisine", type=mairie.type, commune_code="42218")
        voisin = create_user(username="voisin-liste@test.fr", email="voisin-liste@test.fr", type="AUT_LOCALE")
        voisin.institution = autre
        voisin.save()
        c = APIClient()
        c.force_authenticate(user=voisin)

        assert c.get("/api/pcs-fonctions/").data == []
        assert c.patch(f"/api/pcs-fonctions/{ligne['id']}/", {"titulaire": "Usurpateur"}, format="json").status_code == 404
        assert c.delete(f"/api/pcs-fonctions/{ligne['id']}/").status_code == 404
        assert AuditLog.objects.filter(objet_type="FonctionPCS", action__code="CREATION").exists()


@pytest.mark.django_db
class TestDicrim:
    def test_le_document_des_habitants_ne_porte_aucune_donnee_personnelle(self, client, mairie):
        """Il s'affiche en mairie : ni l'annuaire, ni l'organigramme, ni les personnes relais."""
        _plan_complet(mairie)
        dossier = document_pcs.dossier_de(mairie, "PROD")
        MoyenAlertePCS.objects.create(dossier=dossier, type=MoyenAlertePCS.Type.RELAIS, personne="Relaisnominatif",
                                      personne_telephone="0611223344")
        contenu = document_pcs.rassembler(mairie, "PROD")

        public = document_pcs.texte_public_du_dicrim(contenu)

        for interdit in ("Relaisnominatif", "0611223344", "Maire d'essai", "SIDPC 42", "0477000000", "0600000001"):
            assert interdit not in public
        assert "Inondation" in public and "Gymnase municipal" in public and "Sirène" in public

    def test_le_dicrim_sedite_en_pdf_meme_pour_un_plan_vide(self, client, mairie):
        reponse = client.get(URL + "dicrim/")

        assert reponse.status_code == 200 and reponse.content.startswith(b"%PDF")
        assert "dicrim-42207" in reponse["Content-Disposition"]
        assert filtrer_chiffre(AuditLog.objects.filter(objet_type="DossierPCS", action__code="EXPORT"), commentaire__contains="DICRIM").exists()


@pytest.mark.django_db
class TestOrganigrammeEtEquipes:
    """L'organigramme et les équipes de la commune sont la même organisation vue de deux côtés.
    Relier une fonction à l'équipe qui la tient évite de nommer deux fois les mêmes personnes,
    et de recréer une équipe à chaque crise."""

    def _equipe(self, mairie, create_user, nom="Cellule municipale"):
        responsable = create_user(username=f"resp-{nom}@test.fr", email=f"resp-{nom}@test.fr", type="AUT_LOCALE",
                                  first_name="Camille", last_name="Responsable")
        adjoint = create_user(username=f"adj-{nom}@test.fr", email=f"adj-{nom}@test.fr", type="AUT_LOCALE",
                              first_name="Dominique", last_name="Adjoint")
        equipe = Team.objects.create(name=nom, institution=mairie, leader=responsable)
        equipe.membres_encadrement.add(responsable, adjoint)
        return equipe

    def test_le_responsable_et_lencadrement_de_lequipe_sont_repris_sans_ressaisie(self, client, mairie, create_user):
        equipe = self._equipe(mairie, create_user)

        reponse = client.post("/api/pcs-fonctions/", {"fonction": "COORDINATION", "equipe": str(equipe.id)}, format="json")

        assert reponse.status_code == 201, reponse.data
        personnes = reponse.data["personnes"]
        assert personnes["equipe"] == "Cellule municipale"
        assert "Responsable" in personnes["titulaire"] and "Adjoint" in personnes["suppleant"]
        # Plus de manque : la fonction a un titulaire et un suppléant, sans qu'on ait rien tapé.
        client.post("/api/pcs-fonctions/", {"fonction": "DOS", "equipe": str(equipe.id)}, format="json")
        assert "Poste de commandement" not in [m["partie"] for m in client.get(URL).data["manques"]]

    def test_un_nom_saisi_lemporte_sur_celui_de_lequipe(self, client, mairie, create_user):
        equipe = self._equipe(mairie, create_user)

        reponse = client.post("/api/pcs-fonctions/", {"fonction": "LOGISTIQUE", "equipe": str(equipe.id),
                                                      "titulaire": "Adjoint sans compte", "titulaire_telephone": "0600000009"}, format="json")

        assert reponse.data["personnes"]["titulaire"] == "Adjoint sans compte"
        assert reponse.data["personnes"]["titulaire_telephone"] == "0600000009"
        assert "Adjoint" in reponse.data["personnes"]["suppleant"]

    def test_on_ne_relie_pas_une_fonction_a_lequipe_dune_autre_collectivite(self, client, mairie, create_user):
        autre = Institution.objects.create(nom="Mairie voisine", type=mairie.type, commune_code="42218")
        ailleurs = Team.objects.create(name="Équipe d'ailleurs", institution=autre)

        reponse = client.post("/api/pcs-fonctions/", {"fonction": "SOUTIEN", "equipe": str(ailleurs.id)}, format="json")

        assert reponse.status_code == 400

    def test_chaque_point_du_demarrage_de_crise_retrouve_lequipe_de_sa_fonction(self, client, mairie, create_user):
        cellule = self._equipe(mairie, create_user, "Cellule municipale")
        accueil = self._equipe(mairie, create_user, "Équipe accueil")
        client.post("/api/pcs-fonctions/", {"fonction": "SECRETARIAT", "equipe": str(accueil.id)}, format="json")
        client.post("/api/pcs-fonctions/", {"fonction": "COORDINATION", "equipe": str(cellule.id)}, format="json")
        client.post("/api/pcs-fonctions/", {"fonction": "SOUTIEN", "equipe": str(accueil.id)}, format="json")

        par_point = client.get(URL).data["equipes_par_point"]

        # La coordination passe avant le secrétariat pour tenir la cellule de crise.
        assert par_point == {"CELLULE_CRISE": {"id": str(cellule.id), "nom": "Cellule municipale"},
                             "HEBERGEMENT": {"id": str(accueil.id), "nom": "Équipe accueil"}}

    def test_la_cellule_dune_crise_reprend_les_personnes_du_plan_mais_garde_son_propre_salon(
            self, client, mairie, create_user):
        """Un salon par crise, et les messages hors crise ne suivent pas : l'équipe de la crise
        est une équipe à part, composée d'office depuis l'équipe permanente."""
        from core.models import PointType, SalonMatrixEquipe

        PointType.objects.get_or_create(code="CELLULE_CRISE", defaults={"libelle": "Cellule de crise"})
        permanente = self._equipe(mairie, create_user)
        membre = create_user(username="membre-cellule@test.fr", email="membre-cellule@test.fr", type="AUT_LOCALE")
        permanente.members.add(membre)
        client.post("/api/pcs-fonctions/", {"fonction": "COORDINATION", "equipe": str(permanente.id)}, format="json")

        def cellule(nom):
            crise = client.post("/api/crises/", {"name": nom, "type": "INONDATION", "location": "POINT (4.51 45.47)",
                                                 "radius": 5}, format="json").data
            return Team.objects.get(pk=client.get(f"/api/crises/{crise['id']}/cellule/").data["equipe_id"])

        premiere, seconde = cellule("Crue du Gier"), cellule("Tempête")

        # Trois équipes distinctes, donc trois salons : celui du quotidien et un par crise.
        assert len({permanente.id, premiere.id, seconde.id}) == 3
        salons = {SalonMatrixEquipe.objects.get(equipe=e, type="INTERVENANTS").id for e in (premiere, seconde)}
        assert len(salons) == 2
        assert not SalonMatrixEquipe.objects.filter(equipe=permanente, id__in=salons).exists()
        # … mais les mêmes personnes, sans que personne les ait ressaisies.
        for equipe in (premiere, seconde):
            assert equipe.leader_id == permanente.leader_id
            assert set(equipe.membres_encadrement.all()) == set(permanente.membres_encadrement.all())
            assert membre in equipe.members.all()

    def test_une_equipe_permanente_se_reutilise_telle_quelle_sur_les_autres_points(self, client, mairie, create_user):
        """Une équipe prête à l'avance sert à la crise suivante : affectée à un centre d'accueil,
        elle reste elle-même. Seule la cellule de crise est recréée à chaque crise."""
        from core.models import PointOperationnel, PointType
        from core.views import _creer_equipe_pour_point
        from django.test import RequestFactory

        accueil = self._equipe(mairie, create_user, "Équipe accueil")
        client.post("/api/pcs-fonctions/", {"fonction": "SOUTIEN", "equipe": str(accueil.id)}, format="json")
        type_accueil = PointType.objects.get_or_create(code="HEBERGEMENT", defaults={"libelle": "Hébergement"})[0]
        gymnase = PointOperationnel.objects.create(nom="Gymnase", type=type_accueil)

        # L'assistant de démarrage propose l'équipe permanente elle-même pour ce point…
        assert client.get(URL).data["equipes_par_point"]["HEBERGEMENT"]["id"] == str(accueil.id)
        # … et une équipe qu'on choisirait de créer exprès n'est pas remplie d'office.
        requete = RequestFactory().get("/")
        requete.user = accueil.leader
        neuve = _creer_equipe_pour_point(gymnase, "Renfort accueil", mairie, requete)
        assert neuve.leader_id is None and neuve.members.count() == 0

    def test_sans_lien_la_cellule_de_crise_se_cree_comme_avant(self, client, mairie):
        from core.models import PointType

        PointType.objects.get_or_create(code="CELLULE_CRISE", defaults={"libelle": "Cellule de crise"})
        crise = client.post("/api/crises/", {"name": "Crue du Gier", "type": "INONDATION", "location": "POINT (4.51 45.47)",
                                             "radius": 5}, format="json").data

        reponse = client.get(f"/api/crises/{crise['id']}/cellule/")

        assert reponse.status_code == 200
        assert Team.objects.filter(pk=reponse.data["equipe_id"], name="Cellule de crise — Crue du Gier").exists()


@pytest.mark.django_db
class TestEnjeuxExposes:
    """Ce que l'eau atteint, et à partir de quel niveau : les enjeux du plan croisés avec la
    simulation d'inondation. Des hypothèses, que l'écran et le document disent telles."""

    def _simulation(self):
        """Deux niveaux d'eau : à 1 m un petit carré est inondé, à 2 m un carré plus large."""
        from django.contrib.gis.geos import MultiPolygon, Polygon

        from core.models import PalierInondationSimule

        def carre(demi):
            return MultiPolygon(Polygon.from_bbox((4.5 - demi, 45.4 - demi, 4.5 + demi, 45.4 + demi)), srid=4326)
        PalierInondationSimule.objects.create(commune_code="42207", niveau_metres=1.0, polygone=carre(0.001))
        PalierInondationSimule.objects.create(commune_code="42207", niveau_metres=2.0, polygone=carre(0.003))

    def _site(self, mairie, nom, longitude=None, latitude=None):
        from django.contrib.gis.geos import Point

        from core.models import CategorieSiteSensible, SiteSensible, SourceSiteSensible, StatutSiteSensible, SuiviSiteSensible

        site = SiteSensible.objects.create(
            commune_code="42207", commune_nom="Saint-Chamond", source=SourceSiteSensible.values[0], source_id=nom,
            categorie=CategorieSiteSensible.ENSEIGNEMENT, nom=nom, adresse="1 rue du Test", est_enjeu=True,
            location=Point(longitude, latitude, srid=4326) if longitude is not None else None)
        SuiviSiteSensible.objects.create(site=site, institution=mairie, statut=StatutSiteSensible.RETENU)
        return site

    def test_chaque_enjeu_dit_a_partir_de_quel_niveau_leau_latteint(self, client, mairie):
        from django.contrib.gis.geos import Point

        self._simulation()
        self._site(mairie, "École du bas", 4.5005, 45.4005)       # dans le petit carré : dès 1 m
        self._site(mairie, "Collège", 4.502, 45.402)              # dans le grand seulement : dès 2 m
        self._site(mairie, "Crèche du haut", 4.6, 45.5)           # au sec
        self._site(mairie, "Site sans coordonnées")
        plan = Plan.objects.create(institution=mairie, nom="Dispositif inondation")
        type_point = PointType.objects.get_or_create(code="CARE_TEST", defaults={"libelle": "Centre d'accueil"})[0]
        plan.points.add(PointOperationnel.objects.create(nom="Gymnase", type=type_point, capacite_accueil=120,
                                                         location=Point(4.5002, 45.4002, srid=4326)))

        reponse = client.get(URL + "enjeux-exposes/")

        assert reponse.status_code == 200 and reponse.data["simulation_disponible"] is True
        assert reponse.data["niveaux_m"] == [1.0, 2.0] and reponse.data["atteints"] == 3 and reponse.data["non_situes"] == 1
        par_nom = {e["nom"]: e for e in reponse.data["enjeux"]}
        assert par_nom["École du bas"]["seuil_m"] == 1.0 and par_nom["Collège"]["seuil_m"] == 2.0
        assert par_nom["Crèche du haut"]["seuil_m"] is None and par_nom["Crèche du haut"]["situe"] is True
        # Un lieu d'accueil dans l'eau dès 1 m : c'est ce qu'il faut savoir avant d'y envoyer du monde.
        assert par_nom["Gymnase"]["seuil_m"] == 1.0 and par_nom["Gymnase"]["nature"] == "Lieu d'accueil ou point"
        # Du plus exposé au moins exposé, les non situés à la fin.
        assert [e["nom"] for e in reponse.data["enjeux"]][-2:] == ["Crèche du haut", "Site sans coordonnées"]

    def test_le_document_du_plan_reprend_les_enjeux_exposes_et_le_plan_signale_une_simulation_absente(self, client, mairie):
        self._site(mairie, "École du bas", 4.5005, 45.4005)

        sans = client.get(URL).data
        assert "Enjeux exposés" in [m["partie"] for m in sans["manques"]]
        assert next(p for p in sans["paragraphes"] if p["titre"].startswith("Enjeux exposés"))["etat"] == "VIDE"

        self._simulation()
        avec = client.get(URL).data
        assert "Enjeux exposés" not in [m["partie"] for m in avec["manques"]]
        contenu = document_pcs.rassembler(mairie, "PROD")
        assert contenu["exposition"]["enjeux"][0]["seuil_m"] == 1.0
        assert document_pcs.generer_pdf(contenu, edite_par="Agent d'essai").startswith(b"%PDF")

    def test_le_niveau_deau_de_chaque_fiche_du_registre_nest_rendu_quaux_personnes_habilitees(self, mairie, create_user):
        from django.contrib.gis.geos import Point

        from core.models import AdresseSimuleeInondation, HabilitationRegistreVulnerables, QualiteDesignataire, VERSION_ENGAGEMENT_SECRET_REGISTRE

        for libelle, seuil in (("3 Rue du Gier 42400 Saint-Chamond", 1.5), ("8 Rue Haute 42400 Saint-Chamond", None)):
            # Altitude renseignée : l'adresse a été simulée (sans elle, « pas de niveau » voudrait dire « on ne sait pas »).
            AdresseSimuleeInondation.objects.create(commune_code="42207", adresse=libelle, seuil_inondation_metres=seuil, altitude_metres=380.0,
                                                    location=Point(4.5, 45.4, srid=4326))
        fiches = {nom: PersonneVulnerable.objects.create(
            institution_declarante=mairie, commune_code="42207", nom=nom, prenom="Jeanne", adresse=adresse,
            mode_consentement="VOLONTAIRE") for nom, adresse in
            (("Bas", "3, rue du Gier"), ("Haut", "8 rue Haute, 42400 Saint-Chamond"), ("Ailleurs", "12 impasse Introuvable"))}
        teneur = create_user(username="teneur-eau@test.fr", email="teneur-eau@test.fr", type="AUT_LOCALE")
        teneur.institution = mairie
        teneur.engagement_secret_registre_le = timezone.now()
        teneur.engagement_secret_registre_version = VERSION_ENGAGEMENT_SECRET_REGISTRE
        teneur.save()
        HabilitationRegistreVulnerables.objects.create(institution=mairie, utilisateur=teneur, accordee_par=teneur,
                                                       qualite_accordant=QualiteDesignataire.MAIRE, attestation_accordant=True)
        habilite, simple = APIClient(), APIClient()
        habilite.force_authenticate(user=teneur)
        autre = create_user(username="agent-eau@test.fr", email="agent-eau@test.fr", type="AUT_LOCALE")
        autre.institution = mairie
        autre.save()
        simple.force_authenticate(user=autre)

        reponse = habilite.get("/api/personnes-vulnerables/exposition/")

        assert reponse.status_code == 200 and reponse.data["non_situees"] == 1
        assert reponse.data["seuils"] == {str(fiches["Bas"].id): 1.5, str(fiches["Haut"].id): None}
        assert simple.get("/api/personnes-vulnerables/exposition/").status_code == 403
        # … et le registre imprimé le porte, pour savoir chez qui aller en premier.
        assert habilite.get("/api/personnes-vulnerables/pdf/").content.startswith(b"%PDF")
