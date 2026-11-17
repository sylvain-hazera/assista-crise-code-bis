"""Standard de crise (une fiche par appel) et point de situation (les chiffres déjà tenus,
rassemblés) — 17/11/2026."""
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
