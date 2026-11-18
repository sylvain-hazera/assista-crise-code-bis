"""Standard de crise (une fiche par appel) et point de situation (les chiffres déjà tenus,
rassemblés) — 17/11/2026."""
from core.tests.outils_chiffre import filtrer_chiffre
import pytest
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    AppelStandard, ContactInstitution, Crisis, Dossier, Institution, InstitutionType,
    PointOperationnel, RegistrePresence,
)


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name="Crue du Gier", type="INONDATION", location="POINT (4.6 45.5)")


def _mairie(create_user, nom, code):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom=nom, type=itype, commune_code=code)
    user = create_user(username=f"{code}@std.fr", email=f"{code}@std.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return mairie, client


@pytest.fixture
def mairie(create_user):
    return _mairie(create_user, "Mairie du standard", "42186")


def _appel(client, crise=None, **corps):
    donnees = {"nature": "DEMANDE_AIDE", "objet": "Cave inondée, personne âgée seule",
               "appelant_nom": "Madame Durand", "appelant_telephone": "0600000000", "lieu": "3 rue Haute", **corps}
    if crise is not None:
        donnees["crise"] = str(crise.id)
    return client.post(reverse("appelstandard-list"), donnees, format="json")


@pytest.mark.django_db
class TestFicheDAppel:

    def test_chaque_appel_laisse_une_fiche_numerotee(self, mairie, crise):
        _, client = mairie
        premiere = _appel(client, crise)
        seconde = _appel(client, crise, nature="SIGNALEMENT", objet="Arbre sur la route")
        assert (premiere.status_code, seconde.status_code) == (201, 201), premiere.data
        assert (premiere.data["numero"], seconde.data["numero"]) == (1, 2)
        assert (premiere.data["suite"], premiere.data["nature_libelle"]) == ("A_TRAITER", "Demande d'aide")

    def test_rien_de_la_personne_n_est_en_clair(self, mairie, crise):
        _appel(mairie[1], crise)
        with connection.cursor() as curseur:
            curseur.execute("SELECT appelant_nom, appelant_telephone, lieu, objet FROM core_appelstandard")
            brut = " ".join(curseur.fetchone())
        assert "Durand" not in brut and "0600000000" not in brut and "Haute" not in brut and "Cave" not in brut

    def test_un_appel_qui_demande_une_intervention_ouvre_un_dossier_sans_y_recopier_la_personne(self, mairie, crise):
        _, client = mairie
        fiche = _appel(client, crise).data

        reponse = client.post(reverse("appelstandard-ouvrir-dossier", args=[fiche["id"]]), {"priorite": "URGENTE"}, format="json")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["suite"] == "TRANSMIS"
        dossier = Dossier.objects.get()
        assert (dossier.crise_id, dossier.priorite, dossier.generique) == (crise.id, "URGENTE", True)
        assert "n° 1" in dossier.titre
        assert "Durand" not in dossier.titre + dossier.description          # ces champs ne sont pas chiffrés
        # Une fiche n'ouvre qu'un dossier.
        client.post(reverse("appelstandard-ouvrir-dossier", args=[fiche["id"]]), {}, format="json")
        assert Dossier.objects.count() == 1

    def test_pas_de_dossier_sans_crise(self, mairie):
        _, client = mairie
        fiche = _appel(client).data
        assert client.post(reverse("appelstandard-ouvrir-dossier", args=[fiche["id"]]), {}, format="json").status_code == 400

    def test_la_suite_donnee_se_note_et_la_fiche_ne_se_supprime_pas(self, mairie, crise):
        _, client = mairie
        fiche = _appel(client, crise, nature="RENSEIGNEMENT").data
        reponse = client.post(reverse("appelstandard-clore", args=[fiche["id"]]),
                              {"suite": "TRAITE", "suite_donnee": "Renvoyée vers le centre d'accueil"}, format="json")
        assert (reponse.data["suite"], reponse.data["suite_donnee"]) == ("TRAITE", "Renvoyée vers le centre d'accueil")
        url = reverse("appelstandard-detail", args=[fiche["id"]])
        assert client.delete(url).status_code == 405
        assert client.patch(url, {"objet": "réécrit"}, format="json").status_code == 405

    def test_une_autre_mairie_ne_voit_pas_nos_appels(self, mairie, crise, create_user):
        _appel(mairie[1], crise)
        _, voisine = _mairie(create_user, "Mairie voisine", "42187")
        assert voisine.get(reverse("appelstandard-list")).data == []

    def test_la_synthese_compte_par_nature_et_ce_qui_attend(self, mairie, crise):
        _, client = mairie
        _appel(client, crise)
        fiche = _appel(client, crise, nature="OFFRE_AIDE", objet="Propose un groupe électrogène").data
        client.post(reverse("appelstandard-clore", args=[fiche["id"]]), {"suite": "TRAITE"}, format="json")
        synthese = client.get(reverse("appelstandard-synthese"), {"crise": str(crise.id)}).data
        assert (synthese["total"], synthese["a_traiter"]) == (2, 1)
        assert {n["code"]: n["nombre"] for n in synthese["par_nature"]}["OFFRE_AIDE"] == 1


@pytest.mark.django_db
class TestPointDeSituation:

    def test_les_chiffres_deja_tenus_sont_rassembles_et_mis_en_texte(self, mairie, crise):
        institution, client = mairie
        from core.models import PointType
        type_centre = PointType.objects.create(code="ACCUEIL_STD", libelle="Centre d'accueil")
        centre = PointOperationnel.objects.create(
            nom="Gymnase Jean-Moulin", crise=crise, location="POINT (4.6 45.5)", type=type_centre)
        RegistrePresence.objects.create(point=centre, type_personne="EVACUE", nombre=12)
        RegistrePresence.objects.create(point=centre, type_personne="EVACUE", nombre=3, date_depart="2026-11-17T10:00:00Z")
        RegistrePresence.objects.create(point=centre, type_personne="POMPIER", nombre=4)
        _appel(client, crise)

        reponse = client.get(reverse("point_de_situation"), {"crise": str(crise.id)})

        assert reponse.status_code == 200, reponse.data
        population = {c["libelle"]: c["valeur"] for c in reponse.data["chiffres"]["population"]}
        assert population["Personnes accueillies en ce moment"] == 12       # ni les partis, ni les pompiers
        assert population["Personnes passées par un centre depuis le début"] == 15
        assert reponse.data["par_centre"] == [{"centre": "Gymnase Jean-Moulin", "personnes": 12}]
        assert {c["libelle"]: c["valeur"] for c in reponse.data["chiffres"]["standard"]}["Appels à traiter"] == 1
        texte = reponse.data["texte"]
        assert texte.startswith("POINT DE SITUATION — Crue du Gier")
        assert "Gymnase Jean-Moulin : 12" in texte and "MOYENS ENGAGÉS" in texte

    def test_sans_crise_on_le_dit(self, mairie):
        assert mairie[1].get(reverse("point_de_situation")).status_code == 400


@pytest.mark.django_db
class TestHeuresDeclarees:
    """« Je pars », « je rentre » : le temps engagé vient de ce que la personne déclare."""

    def _engagement(self, mairie, crise):
        from core.models import EngagementRessource, Offer, OfferType, Team
        institution, client = mairie
        equipe = Team.objects.create(name="Équipe voirie", institution=institution)
        type_offre, _ = OfferType.objects.get_or_create(type="Matériel", defaults={"description": ""})
        offre = Offer.objects.create(
            title="Tractopelle de M. Blanc", first_name_offer="A", last_name_offer="B",
            email_offer="a@std.fr", offer_type=type_offre, crisis=crise)
        return EngagementRessource.objects.create(
            offer=offre, team=equipe, token_confirmation="jeton-" + str(offre.id), statut="CONFIRME")

    def test_la_personne_declare_son_depart_puis_son_retour(self, mairie, crise):
        engagement = self._engagement(mairie, crise)
        public = APIClient()
        url = reverse("engagement_ressource_public", args=[engagement.token_confirmation])

        assert public.post(url, {"action": "transit"}, format="json").data["actions_possibles"] == ["arrivee", "retour"]
        reponse = public.post(url, {"action": "retour"}, format="json")      # sans passer par « arrivé »

        assert reponse.status_code == 200, reponse.data
        assert (reponse.data["statut"], reponse.data["actions_possibles"]) == ("RENTRE", [])
        engagement.refresh_from_db()
        assert engagement.date_retour is not None and engagement.duree_engagee is not None

    def test_le_point_de_situation_compte_les_heures_et_ceux_qui_ne_sont_pas_rentres(self, mairie, crise):
        from datetime import timedelta

        from django.utils import timezone
        rentre = self._engagement(mairie, crise)
        debut = timezone.now() - timedelta(hours=5)
        type(rentre).objects.filter(id=rentre.id).update(
            statut="RENTRE", date_transit=debut, date_retour=debut + timedelta(hours=3, minutes=30))
        dehors = self._engagement(mairie, crise)
        type(dehors).objects.filter(id=dehors.id).update(statut="EN_TRANSIT", date_transit=debut)

        donnees = mairie[1].get(reverse("point_de_situation"), {"crise": str(crise.id)}).data

        moyens = {c["libelle"]: c["valeur"] for c in donnees["chiffres"]["moyens"]}
        assert moyens["Heures déclarées par les ressources proposées"] == 3.5
        assert moyens["Ressources encore sur le terrain"] == 1
        assert [l["heures"] for l in donnees["releve_engagements"]] == [3.5, None]
        assert donnees["releve_engagements"][0]["ressource"] == "Tractopelle de M. Blanc"


@pytest.mark.django_db
class TestJeParsJeRentreDuPersonnel:
    """Les mêmes deux gestes pour un agent de la mairie ou un bénévole d'association."""

    @pytest.fixture
    def agent(self, create_user, mairie, crise):
        from core.models import ImplicationInstitution, Team
        institution, _ = mairie
        ImplicationInstitution.objects.create(crise=crise, institution=institution, type_implication="IMPLIQUE", actif=True)
        equipe = Team.objects.create(name="Services techniques", institution=institution)
        # Un compte ordinaire : c'est l'appartenance à l'équipe qui compte, pas le rôle.
        user = create_user(username="agent@std.fr", email="agent@std.fr", type="UTIL_SIMPLE",
                           first_name="Paul", last_name="Martin")
        equipe.members.add(user)
        client = APIClient()
        client.force_authenticate(user=user)
        return user, client, equipe

    def _geste(self, client, **corps):
        return client.post(reverse("mon_engagement"), corps, format="json")

    def test_l_agent_voit_ou_il_peut_partir_puis_part_et_rentre(self, agent, crise):
        _, client, equipe = agent
        etat = client.get(reverse("mon_engagement")).data
        assert etat["en_cours"] is None
        assert [c["nom"] for c in etat["crises"]] == ["Crue du Gier"]
        assert [e["nom"] for e in etat["equipes"]] == ["Services techniques"]

        parti = self._geste(client, geste="partir", crise=str(crise.id), equipe=str(equipe.id))
        assert parti.status_code == 200, parti.data
        assert parti.data["en_cours"]["equipe_nom"] == "Services techniques"

        rentre = self._geste(client, geste="rentrer")
        assert rentre.data["en_cours"] is None

    def test_on_ne_part_pas_deux_fois_ni_ne_rentre_sans_etre_parti(self, agent, crise):
        from core.models import EngagementPersonnel
        _, client, _ = agent
        assert self._geste(client, geste="rentrer").status_code == 400
        self._geste(client, geste="partir", crise=str(crise.id))
        assert self._geste(client, geste="partir", crise=str(crise.id)).status_code == 200      # rejouable
        assert EngagementPersonnel.objects.count() == 1
        autre = Crisis.objects.create(name="Autre crise", type="AUTRE", location="POINT (4 45)")
        assert self._geste(client, geste="partir", crise=str(autre.id)).status_code == 400

    def test_on_ne_part_pas_sur_une_crise_qui_ne_concerne_pas_son_institution(self, agent):
        _, client, _ = agent
        ailleurs = Crisis.objects.create(name="Crise d'ailleurs", type="AUTRE", location="POINT (2 48)")
        reponse = self._geste(client, geste="partir", crise=str(ailleurs.id))
        assert reponse.status_code == 400
        assert "engagées sur cette crise" in str(reponse.data)

    def test_la_mairie_relit_les_heures_de_son_personnel(self, agent, mairie, crise):
        from datetime import timedelta

        from django.utils import timezone

        from core.models import EngagementPersonnel
        user, client, equipe = agent
        self._geste(client, geste="partir", crise=str(crise.id), equipe=str(equipe.id))
        debut = timezone.now() - timedelta(hours=4)
        EngagementPersonnel.objects.update(parti_le=debut, rentre_le=debut + timedelta(hours=2, minutes=15))
        self._geste(client, geste="partir", crise=str(crise.id), equipe=str(equipe.id))            # reparti

        donnees = mairie[1].get(reverse("point_de_situation"), {"crise": str(crise.id)}).data

        moyens = {c["libelle"]: c["valeur"] for c in donnees["chiffres"]["moyens"]}
        assert moyens["Personnel et bénévoles partis sur la crise"] == 1
        assert moyens["Heures déclarées par le personnel"] == 2.2
        assert moyens["Personnel encore sur le terrain"] == 1
        lignes = donnees["releve_engagements"]
        assert [l["heures"] for l in lignes] == [2.25, None]
        assert "Martin" in lignes[0]["ressource"] and lignes[0]["equipe"] == "Services techniques"

    def test_anonyme_refuse(self):
        assert APIClient().get(reverse("mon_engagement")).status_code in (401, 403)


@pytest.mark.django_db
class TestReleveComplete:
    """Départ du domicile ou de l'hébergement, et oublis complétés à la main (17/11/2026)."""

    @pytest.fixture
    def agent(self, create_user, mairie, crise):
        from core.models import ImplicationInstitution, Team
        institution, _ = mairie
        ImplicationInstitution.objects.create(crise=crise, institution=institution, type_implication="IMPLIQUE", actif=True)
        equipe = Team.objects.create(name="Renfort", institution=institution)
        user = create_user(username="renfort@std.fr", email="renfort@std.fr", type="UTIL_SIMPLE")
        equipe.members.add(user)
        client = APIClient()
        client.force_authenticate(user=user)
        return user, client, equipe

    def _instants(self, heures_avant, duree_h):
        from datetime import timedelta

        from django.utils import timezone
        debut = timezone.now() - timedelta(hours=heures_avant)
        return debut.isoformat(), (debut + timedelta(hours=duree_h)).isoformat()

    def _ajouter(self, client, crise, heures_avant=30, duree_h=6, **extra):
        parti, rentre = self._instants(heures_avant, duree_h)
        return client.post(reverse("mon_releve"), {"crise": str(crise.id), "parti_le": parti, "rentre_le": rentre, **extra}, format="json")

    def test_qui_est_loge_sur_site_part_de_son_hebergement(self, agent, crise):
        from core.models import AffectationLogementIntervenant, PointOperationnel, PointType
        user, client, _ = agent
        gite = PointOperationnel.objects.create(
            nom="Gîte communal", crise=crise, location="POINT (4.6 45.5)",
            type=PointType.objects.create(code="LOGEMENT_STD", libelle="Logement"))
        AffectationLogementIntervenant.objects.create(intervenant=user, crise=crise, point=gite)

        etat = client.get(reverse("mon_engagement")).data
        assert etat["crises"][0]["hebergement"] == "Gîte communal"
        parti = client.post(reverse("mon_engagement"), {"geste": "partir", "crise": str(crise.id)}, format="json").data
        assert (parti["en_cours"]["depart_de"], parti["en_cours"]["hebergement"]) == ("HEBERGEMENT", "Gîte communal")
        client.post(reverse("mon_engagement"), {"geste": "rentrer"}, format="json")
        (ligne,) = client.get(reverse("mon_releve")).data["lignes"]
        assert (ligne["retour_a"], ligne["saisie_manuelle"]) == ("HEBERGEMENT", False)

    def test_sans_logement_on_part_du_domicile(self, agent, crise):
        _, client, _ = agent
        parti = client.post(reverse("mon_engagement"), {"geste": "partir", "crise": str(crise.id)}, format="json").data
        assert parti["en_cours"]["depart_de"] == "DOMICILE"

    def test_une_sortie_oubliee_s_ajoute_a_la_main_et_se_voit_comme_telle(self, agent, crise, mairie):
        _, client, equipe = agent
        reponse = self._ajouter(client, crise, equipe=str(equipe.id), depart_de="HEBERGEMENT")
        assert reponse.status_code == 201, reponse.data
        assert (reponse.data["heures"], reponse.data["saisie_manuelle"], reponse.data["retour_a"]) == (6.0, True, "HEBERGEMENT")
        releve = client.get(reverse("mon_releve")).data
        assert releve["total_heures"] == 6.0
        # Et la mairie le lit dans son point de situation, signalé comme complété à la main.
        ligne = mairie[1].get(reverse("point_de_situation"), {"crise": str(crise.id)}).data["releve_engagements"][0]
        assert (ligne["heures"], ligne["saisie_manuelle"], ligne["equipe"]) == (6.0, True, "Renfort")

    @pytest.mark.parametrize("heures_avant, duree_h, extrait", [
        (2, 5, "heure à venir"),
        (60, 30, "Plus de 24 heures"),
        (30, -1, "doit suivre le départ"),
    ])
    def test_une_ligne_impossible_est_refusee_avec_sa_raison(self, agent, crise, heures_avant, duree_h, extrait):
        reponse = self._ajouter(agent[1], crise, heures_avant=heures_avant, duree_h=duree_h)
        assert reponse.status_code == 400
        assert extrait in str(reponse.data)

    def test_deux_lignes_ne_se_recouvrent_pas(self, agent, crise):
        _, client, _ = agent
        assert self._ajouter(client, crise, heures_avant=30, duree_h=6).status_code == 201
        assert "recouvrent" in str(self._ajouter(client, crise, heures_avant=27, duree_h=6).data)
        assert self._ajouter(client, crise, heures_avant=20, duree_h=3).status_code == 201

    def test_le_retour_oublie_se_corrige_mais_la_declaration_ne_s_efface_pas(self, agent, crise):
        from datetime import timedelta

        from django.utils import timezone

        from core.models import EngagementPersonnel
        _, client, _ = agent
        client.post(reverse("mon_engagement"), {"geste": "partir", "crise": str(crise.id)}, format="json")
        EngagementPersonnel.objects.update(parti_le=timezone.now() - timedelta(hours=10))
        ligne = client.get(reverse("mon_releve")).data["lignes"][0]
        url = reverse("mon_releve_ligne", args=[ligne["id"]])

        assert client.delete(url).status_code == 400                       # déclarée sur le moment
        retour = (timezone.now() - timedelta(hours=3)).isoformat()
        corrigee = client.patch(url, {"rentre_le": retour}, format="json")

        assert corrigee.status_code == 200, corrigee.data
        assert (corrigee.data["heures"], corrigee.data["saisie_manuelle"]) == (7.0, True)
        assert client.get(reverse("mon_engagement")).data["en_cours"] is None

    def test_on_ne_touche_pas_au_releve_d_un_autre(self, agent, crise, create_user):
        ligne = self._ajouter(agent[1], crise).data
        autre = APIClient()
        autre.force_authenticate(user=create_user(username="autre@std.fr", email="autre@std.fr", type="UTIL_SIMPLE"))
        assert autre.patch(reverse("mon_releve_ligne", args=[ligne["id"]]), {}, format="json").status_code == 404
        assert autre.get(reverse("mon_releve")).data["lignes"] == []

    def test_l_activite_de_la_personne_et_de_son_equipe_est_en_regard(self, agent, crise):
        from django.utils import timezone

        from core.models import CreneauEquipe, Dossier, DossierHistorique
        user, client, equipe = agent
        CreneauEquipe.objects.create(equipe=equipe, utilisateur=user, date=timezone.localdate(), creneau="MATIN", crise=crise)
        dossier = Dossier.objects.create(numero="DOS-ESSAI01", crise=crise, equipe=equipe, titre="Pompage", description="x")
        DossierHistorique.objects.create(dossier=dossier, auteur=None, evenement="Pris en charge",
                                         commentaire="chez Madame Durand")

        activite = client.get(reverse("mon_releve")).data["activite"]

        quoi = " | ".join(a["quoi"] for a in activite)
        assert "Planning : créneau matin" in quoi and "Dossier DOS-ESSAI01 : pris en charge" in quoi
        assert "Durand" not in quoi                                          # jamais le détail
        assert {a["source"] for a in activite} == {"moi", "equipe"}


@pytest.mark.django_db
class TestLeChefRelitEtValide:
    """Seule la personne complète son relevé ; le chef d'équipe le voit et le valide."""

    @pytest.fixture
    def equipe(self, create_user, mairie, crise):
        from core.models import ImplicationInstitution, Team
        institution, _ = mairie
        ImplicationInstitution.objects.create(crise=crise, institution=institution, type_implication="IMPLIQUE", actif=True)
        chef = create_user(username="chef@std.fr", email="chef@std.fr", type="UTIL_SIMPLE")
        membre = create_user(username="membre@std.fr", email="membre@std.fr", type="UTIL_SIMPLE",
                             first_name="Léa", last_name="Petit")
        equipe = Team.objects.create(name="Voirie", institution=institution, leader=chef)
        equipe.members.add(chef, membre)
        clients = {}
        for nom, user in (("chef", chef), ("membre", membre)):
            clients[nom] = APIClient()
            clients[nom].force_authenticate(user=user)
        return equipe, clients

    def _sortie(self, client, crise, equipe, heures_avant=30, duree_h=5):
        from datetime import timedelta

        from django.utils import timezone
        debut = timezone.now() - timedelta(hours=heures_avant)
        return client.post(reverse("mon_releve"), {
            "crise": str(crise.id), "equipe": str(equipe.id),
            "parti_le": debut.isoformat(), "rentre_le": (debut + timedelta(hours=duree_h)).isoformat(),
        }, format="json").data

    def _relire(self, client, ligne, geste, **extra):
        return client.post(reverse("releves_equipe"), {"ligne": ligne["id"], "geste": geste, **extra}, format="json")

    def test_le_chef_voit_les_fiches_de_son_equipe_pas_la_sienne(self, equipe, crise):
        team, clients = equipe
        self._sortie(clients["membre"], crise, team)
        self._sortie(clients["chef"], crise, team)

        fiches = clients["chef"].get(reverse("releves_equipe")).data["fiches"]

        (fiche,) = fiches
        assert "Petit" in fiche["personne"]
        assert (fiche["total_heures"], fiche["a_valider"], fiche["heures_validees"]) == (5.0, 1, 0)
        assert clients["membre"].get(reverse("releves_equipe")).data["fiches"] == []
        assert clients["chef"].get(reverse("mon_releve")).data["encadre"] is True
        assert clients["membre"].get(reverse("mon_releve")).data["encadre"] is False

    def test_une_ligne_validee_ne_se_modifie_plus(self, equipe, crise, mairie):
        team, clients = equipe
        ligne = self._sortie(clients["membre"], crise, team)

        assert self._relire(clients["chef"], ligne, "valider").data["validee"] is True

        url = reverse("mon_releve_ligne", args=[ligne["id"]])
        assert clients["membre"].patch(url, {"depart_de": "HEBERGEMENT"}, format="json").status_code == 400
        assert clients["membre"].delete(url).status_code == 400
        moyens = {c["libelle"]: c["valeur"] for c in mairie[1].get(
            reverse("point_de_situation"), {"crise": str(crise.id)}).data["chiffres"]["moyens"]}
        assert moyens["dont validées par l'encadrement"] == 5.0

    def test_le_chef_renvoie_avec_une_remarque_et_la_personne_corrige(self, equipe, crise):
        from datetime import timedelta

        from django.utils import timezone
        team, clients = equipe
        ligne = self._sortie(clients["membre"], crise, team)

        assert self._relire(clients["chef"], ligne, "renvoyer").status_code == 400          # sans dire quoi
        renvoyee = self._relire(clients["chef"], ligne, "renvoyer", remarque="Tu es rentrée à 17 h, pas 18 h")
        assert (renvoyee.data["validee"], renvoyee.data["remarque_chef"]) == (False, "Tu es rentrée à 17 h, pas 18 h")
        assert clients["membre"].get(reverse("mon_releve")).data["lignes"][0]["remarque_chef"].startswith("Tu es rentrée")

        retour = (timezone.now() - timedelta(hours=26)).isoformat()
        corrigee = clients["membre"].patch(reverse("mon_releve_ligne", args=[ligne["id"]]), {"rentre_le": retour}, format="json")
        assert (corrigee.status_code, corrigee.data["remarque_chef"]) == (200, "")

    def test_le_chef_ne_corrige_rien_et_ne_se_valide_pas_lui_meme(self, equipe, crise):
        team, clients = equipe
        du_membre = self._sortie(clients["membre"], crise, team)
        du_chef = self._sortie(clients["chef"], crise, team)
        assert clients["chef"].patch(reverse("mon_releve_ligne", args=[du_membre["id"]]), {}, format="json").status_code == 404
        reponse = self._relire(clients["chef"], du_chef, "valider")
        assert reponse.status_code == 400 and "propre relevé" in str(reponse.data)
        assert self._relire(clients["membre"], du_chef, "valider").status_code == 400      # pas encadrant

    def test_une_sortie_en_cours_ne_se_valide_pas(self, equipe, crise):
        from core.models import EngagementPersonnel
        team, clients = equipe
        clients["membre"].post(reverse("mon_engagement"), {"geste": "partir", "crise": str(crise.id), "equipe": str(team.id)}, format="json")
        ligne = {"id": str(EngagementPersonnel.objects.get().id)}
        assert "pas terminée" in str(self._relire(clients["chef"], ligne, "valider").data)

    def test_les_connexions_figurent_dans_l_activite(self, equipe, crise):
        from core.audit import audit_log
        from core.models import AuditLog, User
        _, clients = equipe
        membre = filtrer_chiffre(User.objects.filter(), username="membre@std.fr").get()
        from django.test import RequestFactory
        requete = RequestFactory().post("/api/token/")
        requete.user = membre
        audit_log(request=requete, action_code="CONNEXION", objet_type="User", objet_id=membre.id, commentaire="x")
        if not AuditLog.objects.filter(utilisateur=membre, action__code="CONNEXION").exists():
            pytest.skip("La trace de connexion ne porte pas l'utilisateur dans cet environnement d'essai.")
        activite = clients["membre"].get(reverse("mon_releve")).data["activite"]
        assert "Connexion à l'application" in [a["quoi"] for a in activite]


@pytest.mark.django_db
class TestLeBureauOuLaMairieValide:
    """Deux trous comblés : la sortie sans équipe, et les heures d'un chef seul encadrant."""

    @pytest.fixture
    def scene(self, create_user, mairie, crise):
        from core.models import ImplicationInstitution, Team
        institution, client_mairie = mairie
        ImplicationInstitution.objects.create(crise=crise, institution=institution, type_implication="IMPLIQUE", actif=True)
        chef = create_user(username="seulchef@std.fr", email="seulchef@std.fr", type="UTIL_SIMPLE")
        equipe = Team.objects.create(name="Espaces verts", institution=institution, leader=chef)
        equipe.members.add(chef)
        isole = create_user(username="isole@std.fr", email="isole@std.fr", type="UTIL_SIMPLE")
        isole.institution = institution
        isole.save()
        clients = {"mairie": client_mairie}
        for nom, user in (("chef", chef), ("isole", isole)):
            clients[nom] = APIClient()
            clients[nom].force_authenticate(user=user)
        return equipe, clients

    def _sortie(self, client, crise, equipe=None, heures_avant=30):
        from datetime import timedelta

        from django.utils import timezone
        debut = timezone.now() - timedelta(hours=heures_avant)
        corps = {"crise": str(crise.id), "parti_le": debut.isoformat(),
                 "rentre_le": (debut + timedelta(hours=4)).isoformat()}
        if equipe is not None:
            corps["equipe"] = str(equipe.id)
        reponse = client.post(reverse("mon_releve"), corps, format="json")
        assert reponse.status_code == 201, reponse.data
        return reponse.data

    def _valider(self, client, ligne):
        return client.post(reverse("releves_equipe"), {"ligne": ligne["id"], "geste": "valider"}, format="json")

    def test_la_mairie_valide_les_heures_du_chef_seul_encadrant(self, scene, crise):
        equipe, clients = scene
        ligne = self._sortie(clients["chef"], crise, equipe)
        assert self._valider(clients["chef"], ligne).status_code == 400          # pas les siennes
        assert self._valider(clients["mairie"], ligne).data["validee"] is True

    def test_la_mairie_valide_une_sortie_sans_equipe(self, scene, crise):
        _, clients = scene
        ligne = self._sortie(clients["isole"], crise)
        fiches = clients["mairie"].get(reverse("releves_equipe")).data["fiches"]
        assert sum(len(f["lignes"]) for f in fiches) == 1
        assert self._valider(clients["mairie"], ligne).data["validee"] is True

    def test_le_bureau_d_une_association_valide_pour_la_sienne(self, create_user, crise):
        from core.models import ImplicationInstitution, Institution, InstitutionType
        itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
        asso = Institution.objects.create(nom="Association du bureau", type=itype)
        ImplicationInstitution.objects.create(crise=crise, institution=asso, type_implication="IMPLIQUE", actif=True)
        clients = {}
        for nom, bureau in (("benevole", False), ("tresoriere", True)):
            user = create_user(username=f"{nom}@std.fr", email=f"{nom}@std.fr", type="UTIL_SIMPLE")
            user.institution = asso
            user.save()
            ContactInstitution.objects.create(institution=asso, utilisateur=user, actif=True, membre_bureau=bureau)
            clients[nom] = APIClient()
            clients[nom].force_authenticate(user=user)
        ligne = self._sortie(clients["benevole"], crise)
        sienne = self._sortie(clients["tresoriere"], crise, heures_avant=20)

        assert clients["tresoriere"].get(reverse("mon_releve")).data["encadre"] is True
        assert self._valider(clients["tresoriere"], ligne).data["validee"] is True
        assert self._valider(clients["benevole"], sienne).status_code == 400      # simple membre

    def test_une_autre_mairie_ne_valide_rien_ici(self, scene, crise, create_user):
        _, clients = scene
        ligne = self._sortie(clients["isole"], crise)
        _, voisine = _mairie(create_user, "Mairie d'à côté", "42199")
        assert self._valider(voisine, ligne).status_code == 400
        assert voisine.get(reverse("releves_equipe")).data["fiches"] == []


@pytest.mark.django_db
class TestSaisiePourAutrui:
    """18/11/2026, correction de Sylvain : « la mairie enregistre la même chose que sur les
    formulaires grand public, sauf qu'elle le fait pour autrui. Là tu m'as fait un doublon. »
    Une demande reçue par téléphone crée donc la VRAIE demande ; la fiche d'appel n'en est que
    la trace."""

    @pytest.fixture
    def crise_conduite(self, crise, mairie, create_user):
        from core.models import ImplicationInstitution, TypeImplication
        responsable = create_user(username="resp@std.fr", email="resp@std.fr", type="AUT_LOCALE")
        ImplicationInstitution.objects.create(crise=crise, institution=mairie[0], responsable=responsable,
                                              type_implication=TypeImplication.ACTEUR, actif=True)
        return crise

    def _demande(self, client, crise, request_type, **corps):
        return client.post("/api/demandes/", {
            "title": "Demande d'aide - Crue du Gier - Matériel", "description": "Cave inondée",
            "first_name_request": "Jeanne", "last_name_request": "Durand", "phone_request": "0600000000",
            "request_type": str(request_type.id), "crisis": str(crise.id), **corps}, format="json")

    def test_le_standard_cree_la_vraie_demande_sans_adresse_electronique(self, mairie, crise_conduite, request_type):
        from core.models import Request
        _, client = mairie
        reponse = self._demande(client, crise_conduite, request_type, via_standard="1",
                                standard_appel="11111111-1111-4111-8111-111111111111")
        assert reponse.status_code == 201, reponse.data
        demande = Request.objects.get()
        assert (demande.first_name_request, demande.email_request or "") == ("Jeanne", "")
        # La fiche dit elle-même qu'elle a été enregistrée par la mairie, pour la personne.
        assert demande.enregistre_pour_autrui_par_id == mairie[0].id

        (fiche,) = client.get(reverse("appelstandard-list")).data
        assert (fiche["nature"], fiche["suite"], fiche["appelant_nom"]) == ("DEMANDE_AIDE", "TRANSMIS", "Jeanne Durand")
        assert fiche["fiches"] == [{"type": "demande", "id": str(demande.id), "titre": demande.title}]

    def test_deux_besoins_dans_un_meme_appel_ne_laissent_qu_une_fiche(self, mairie, crise_conduite, request_type):
        _, client = mairie
        for _ in range(2):
            assert self._demande(client, crise_conduite, request_type, via_standard="1",
                                 standard_appel="22222222-2222-4222-8222-222222222222").status_code == 201
        (fiche,) = client.get(reverse("appelstandard-list")).data
        assert len(fiche["fiches"]) == 2 and AppelStandard.objects.count() == 1

    def test_hors_standard_l_adresse_reste_exigee(self, mairie, crise_conduite, request_type):
        reponse = self._demande(mairie[1], crise_conduite, request_type, enregistre_pour_autrui_par=str(mairie[0].id))
        assert reponse.status_code == 400 and "email_request" in reponse.data
        assert not AppelStandard.objects.exists()

    def test_un_particulier_ne_s_exempte_pas_en_se_disant_standard(self, create_user, crise_conduite, request_type):
        particulier = APIClient()
        particulier.force_authenticate(user=create_user(username="p@std.fr", email="p@std.fr", type="UTIL_SIMPLE"))
        reponse = self._demande(particulier, crise_conduite, request_type, via_standard="1")
        assert reponse.status_code == 400 and "email_request" in reponse.data
        assert not AppelStandard.objects.exists()

    def test_aucun_courriel_ne_part_sans_adresse(self, mairie, crise_conduite, request_type, mailoutbox):
        self._demande(mairie[1], crise_conduite, request_type, via_standard="1")
        assert all(m.to and all(m.to) for m in mailoutbox)      # jamais de destinataire vide

    def test_un_signalement_recu_au_standard_cree_le_vrai_signalement(self, mairie, crise_conduite):
        from core.models import Information, InformationType
        _, client = mairie
        t, _c = InformationType.objects.get_or_create(type="Danger imminent")
        reponse = client.post("/api/informations/", {
            "title": "Arbre sur la route", "first_name_information": "Paul", "last_name_information": "Petit",
            "phone_information": "0600000000", "information_type": str(t.id), "crisis": str(crise_conduite.id),
            "location": "POINT(4.6 45.5)", "via_standard": "1"}, format="json")
        assert reponse.status_code == 201, reponse.data
        (fiche,) = client.get(reverse("appelstandard-list")).data
        assert fiche["nature"] == "SIGNALEMENT" and fiche["fiches"][0]["id"] == str(Information.objects.get().id)

    def test_personne_ne_se_declare_enregistre_par_la_mairie(self, mairie, crise_conduite, request_type):
        from core.models import Request
        reponse = self._demande(mairie[1], crise_conduite, request_type, email_request="j@courriel.exemple",
                                enregistre_pour_autrui_par=str(mairie[0].id))
        assert reponse.status_code == 201, reponse.data
        assert Request.objects.get().enregistre_pour_autrui_par_id is None
