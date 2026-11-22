"""Délégation de gestion mairie → AASC (21/11/2026).

« Nous, Réserve Résilience, proposons la solution aux mairies, solution que nous exploitons pour
eux » ; « c'est la Réserve qui crée aussi la collectivité » ; « les conventions sont signées à
l'avance » ; « si la mairie rompt la convention, elle ne peut plus qu'exporter ses données ».
Qui agit : le bureau de l'AASC et l'encadrement des coordinations qui couvrent la commune.
"""
import io
import zipfile

import pytest
from django.urls import reverse
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.delegation_gestion import en_mode_export_seul, est_delegue
from core.models import (
    AuditLog, Commune, ContactInstitution, Crisis, DelegationGestion, Institution, InstitutionType,
    Plan, Team, User,
)


def _type(code):
    t, _ = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})
    return t


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _compte(email, type_compte, institution, bureau=False):
    u = User.objects.create_user(username=email, email=email, password="x", type=type_compte, institution=institution)
    ContactInstitution.objects.create(institution=institution, utilisateur=u, actif=True, membre_bureau=bureau)
    return u


@pytest.fixture
def monde(db):
    Commune.objects.get_or_create(code="42186", defaults={"nom": "Rive-de-Gier", "departement_code": "42"})
    aasc = Institution.objects.create(nom="Réserve essai", type=_type("aasc"))
    bureau = _compte("bureau@reserve.test", "SECOURS", aasc, bureau=True)
    cadre = _compte("cadre42@reserve.test", "SECOURS", aasc)
    simple = _compte("simple@reserve.test", "SECOURS", aasc)
    cadre_ailleurs = _compte("cadre69@reserve.test", "SECOURS", aasc)
    loire = Team.objects.create(name="Coordination Loire", institution=aasc, echelon="DEPARTEMENTAL",
                                territoire_code="42", environment="PROD")
    loire.membres_encadrement.add(cadre)
    rhone = Team.objects.create(name="Coordination Rhône", institution=aasc, echelon="DEPARTEMENTAL",
                                territoire_code="69", environment="PROD")
    rhone.leader = cadre_ailleurs
    rhone.save()
    return dict(aasc=aasc, bureau=bureau, cadre=cadre, simple=simple, cadre_ailleurs=cadre_ailleurs)


def _deleguer(monde, auteur="bureau"):
    return _client(monde[auteur]).post(reverse("delegationgestion-list"), {
        "aasc": str(monde["aasc"].id), "commune_code": "42186",
        "convention_reference": "CONV-2026-12", "convention_signee_le": "2026-11-15",
        "convention_signataire": "Claire Fontaine", "convention_signataire_qualite": "Maire",
    }, format="json")


@pytest.mark.django_db
class TestCreation:

    def test_le_bureau_cree_la_mairie_et_la_delegation(self, monde):
        r = _deleguer(monde)
        assert r.status_code == 201, r.data
        mairie = Institution.objects.get(commune_code="42186", type__code="mairie")
        assert mairie.nom == "Mairie de Rive-de-Gier"
        assert mairie.acces_fourni_par == monde["aasc"]
        assert DelegationGestion.objects.get().statut == "ACTIVE"

    def test_un_cadre_qui_couvre_la_commune_peut_engager(self, monde):
        assert _deleguer(monde, "cadre").status_code == 201

    def test_un_cadre_d_un_autre_departement_ou_un_simple_membre_ne_peut_pas(self, monde):
        assert _deleguer(monde, "cadre_ailleurs").status_code == 403
        assert _deleguer(monde, "simple").status_code == 403
        assert not Institution.objects.filter(commune_code="42186").exists()

    def test_la_convention_est_obligatoire(self, monde):
        r = _client(monde["bureau"]).post(reverse("delegationgestion-list"), {
            "aasc": str(monde["aasc"].id), "commune_code": "42186"}, format="json")
        assert r.status_code == 400

    def test_jamais_de_mairie_en_double(self, monde):
        existante = Institution.objects.create(nom="Mairie - Rive-de-Gier", type=_type("mairie"), commune_code="42186")
        assert _deleguer(monde).status_code == 201
        assert Institution.objects.filter(commune_code="42186").count() == 1
        assert DelegationGestion.objects.get().collectivite == existante


@pytest.mark.django_db
class TestAgirPourLaMairie:

    def test_le_cadre_bascule_sur_la_mairie_et_agit_avec_ses_droits(self, monde):
        _deleguer(monde)
        mairie = Institution.objects.get(commune_code="42186")
        cadre = monde["cadre"]
        c = _client(cadre)
        etat = c.get(reverse("institution_active")).data
        ligne = next(i for i in etat["institutions"] if i["id"] == str(mairie.id))
        assert ligne["par_delegation"] == {"aasc": "Réserve essai"}
        assert c.post(reverse("institution_active"), {"institution": str(mairie.id)}, format="json").status_code == 200
        cadre.refresh_from_db()
        assert c.get(reverse("institution_active")).data["delegation_en_cours"]["collectivite"] == mairie.nom

        r = c.post(reverse("plan-list"), {"nom": "Plan inondation"}, format="json")
        assert r.status_code == 201, r.data
        plan = Plan.objects.get(nom="Plan inondation")
        assert plan.institution == mairie
        lignes = AuditLog.objects.filter(objet_type="Plan", objet_id=plan.id)
        assert any("par délégation — Réserve essai" in (l.commentaire or "") for l in lignes)

    def test_un_simple_membre_ne_bascule_pas(self, monde):
        _deleguer(monde)
        mairie = Institution.objects.get(commune_code="42186")
        r = _client(monde["simple"]).post(reverse("institution_active"), {"institution": str(mairie.id)}, format="json")
        assert r.status_code == 400

    def test_le_registre_reste_hors_de_la_delegation(self, monde):
        _deleguer(monde)
        mairie = Institution.objects.get(commune_code="42186")
        cadre = monde["cadre"]
        c = _client(cadre)
        c.post(reverse("institution_active"), {"institution": str(mairie.id)}, format="json")
        r = c.post(reverse("habilitationregistrevulnerables-list"), {
            "utilisateur": str(cadre.id), "qualite_accordant": "MAIRE", "attestation_accordant": True}, format="json")
        assert r.status_code == 403


@pytest.mark.django_db
class TestRupture:

    def test_retrait_coupe_l_aasc_et_laisse_l_export_a_la_mairie(self, monde):
        _deleguer(monde)
        mairie = Institution.objects.get(commune_code="42186")
        agent = _compte("agent@mairie.test", "AUT_LOCALE", mairie)
        delegation = DelegationGestion.objects.get()
        r = _client(agent).post(reverse("delegationgestion-retirer", args=[delegation.id]), {"motif": "Fin"}, format="json")
        assert r.status_code == 200, r.data
        assert not est_delegue(User.objects.get(pk=monde["cadre"].pk), mairie)
        assert en_mode_export_seul(mairie)

        c = _client(agent)
        assert c.get(reverse("institution_active")).data["export_seul"] is True
        assert c.post(reverse("plan-list"), {"nom": "Interdit"}, format="json").status_code == 403
        r = c.get(reverse("export_donnees_institution", args=[mairie.id]))
        assert r.status_code == 200
        noms = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        assert "institution.json" in noms and "LISEZMOI.txt" in noms

    def test_pendant_une_crise_ouverte_le_retrait_se_confirme_et_se_motive(self, monde):
        """« On traite au cas par cas, dans l'intérêt de la population » : pas de blocage
        d'office, mais une confirmation explicite et un motif."""
        _deleguer(monde)
        Crisis.objects.create(name="Crue en cours", location=Point(4.6, 45.5, srid=4326), zone_communes=["42186"])
        delegation = DelegationGestion.objects.get()
        url = reverse("delegationgestion-retirer", args=[delegation.id])
        c = _client(monde["bureau"])
        r = c.post(url, {}, format="json")
        assert r.status_code == 400 and r.data["confirmation_requise"] is True
        assert "Crue en cours" in r.data["error"]
        assert c.post(url, {"forcer": True}, format="json").status_code == 400  # motif obligatoire
        r = c.post(url, {"forcer": True, "motif": "Reprise par la mairie, décidée avec le préfet"}, format="json")
        assert r.status_code == 200, r.data
        assert DelegationGestion.objects.get().statut == "RETIREE"

    def test_un_etranger_n_exporte_pas(self, monde, create_user):
        _deleguer(monde)
        mairie = Institution.objects.get(commune_code="42186")
        intrus = create_user(username="intrus@test.fr", email="intrus@test.fr", type="AUT_LOCALE")
        assert _client(intrus).get(reverse("export_donnees_institution", args=[mairie.id])).status_code == 403


@pytest.mark.django_db
class TestConventionDepartementale:
    """« La Réserve signe convention par défaut avec le département. Chaque division
    départementale doit avoir la vue sur le département, en incluant les répertoires des EPCI. »"""

    @pytest.fixture
    def departement(self, monde):
        Commune.objects.update_or_create(code="42218", defaults={"nom": "Saint-Étienne", "departement_code": "42", "population": 170000})
        Commune.objects.update_or_create(code="42186", defaults={"nom": "Rive-de-Gier", "departement_code": "42", "population": 15000})
        epci = Institution.objects.create(nom="Saint-Étienne Métropole", type=_type("epci"), departement_code="42",
                                          commune_code="42218")
        Institution.objects.filter(pk=epci.pk).update(departement_code="42")
        agent = _compte("dgs@metropole.test", "AUT_LOCALE", epci)
        agent.first_name, agent.last_name = "Paul", "Durand"
        agent.save()
        return monde

    def _deleguer_departement(self, monde, auteur="bureau"):
        return _client(monde[auteur]).post(reverse("delegationgestion-list"), {
            "aasc": str(monde["aasc"].id), "departement_code": "42",
            "convention_reference": "CONV-CD42", "convention_signee_le": "2026-10-01"}, format="json")

    def test_le_conseil_departemental_est_cree_et_la_coordination_agit(self, departement):
        r = self._deleguer_departement(departement)
        assert r.status_code == 201, r.data
        cg = Institution.objects.get(type__code="cg", departement_code="42")
        assert cg.secteur_niveau_effectif == "departement"
        assert cg.commune_code == "42218"  # la plus peuplée
        assert est_delegue(departement["cadre"], cg)
        assert not est_delegue(departement["cadre_ailleurs"], cg)

    def test_l_amorcage_part_aussitot(self, departement):
        from core.models import AmorcageDepartement
        self._deleguer_departement(departement)
        amorcage = AmorcageDepartement.objects.get()
        assert set(amorcage.etapes) == {"referentiel", "annuaire", "adresses", "risques", "sites", "entreprises", "simulations"}

    def test_l_arborescence_du_departement(self, departement):
        Commune.objects.filter(code__in=["42218", "42186"]).update(epci_code="244200770")
        Institution.objects.filter(type__code="epci").update(epci_code="244200770")
        mairie = Institution.objects.create(nom="Mairie - Rive-de-Gier", type=_type("mairie"), commune_code="42186",
                                            telephone="04 77 83 07 80")
        self._deleguer_departement(departement)
        d = DelegationGestion.objects.get()
        r = _client(departement["cadre"]).get(reverse("delegationgestion-arborescence", args=[d.id]))
        assert r.status_code == 200, r.data
        assert r.data["departement"]["code"] == "42"
        branche = r.data["epcis"][0]
        assert branche["nom"] == "Saint-Étienne Métropole"
        communes = {c["code"]: c for c in branche["communes"]}
        assert communes["42186"]["mairie"]["telephone"] == "04 77 83 07 80"
        assert communes["42218"]["mairie"] is None
        assert r.data["totaux"]["communes"] == 2
        assert _client(departement["simple"]).get(reverse("delegationgestion-arborescence", args=[d.id])).status_code == 403

    def test_un_cadre_d_un_autre_departement_n_engage_pas_le_42(self, departement):
        assert self._deleguer_departement(departement, "cadre_ailleurs").status_code == 403

    def test_repertoires_des_epci_du_departement(self, departement):
        self._deleguer_departement(departement)
        d = DelegationGestion.objects.get()
        r = _client(departement["cadre"]).get(reverse("delegationgestion-repertoires", args=[d.id]))
        assert r.status_code == 200
        assert r.data[0]["nom"] == "Saint-Étienne Métropole"
        assert r.data[0]["contacts"][0]["nom"] == "Paul Durand"
        assert _client(departement["simple"]).get(reverse("delegationgestion-repertoires", args=[d.id])).status_code == 403


@pytest.mark.django_db
def test_les_cercles_d_une_commune_hors_perimetre_sont_refuses(monde, create_user):
    Institution.objects.create(nom="Mairie lointaine", type=_type("mairie"), commune_code="13055")
    agent = create_user(username="agent-42@test.fr", email="agent-42@test.fr", type="AUT_LOCALE")
    mairie = Institution.objects.create(nom="Mairie de Rive-de-Gier", type=_type("mairie"), commune_code="42186")
    ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
    agent.institution = mairie
    agent.save()
    c = _client(agent)
    from unittest import mock
    with mock.patch("core.tasks.relever_adresses_commune_task.delay"):
        assert c.get("/api/personnes-vulnerables/secteurs/", {"commune_code": "42186"}).status_code == 200
        assert c.get("/api/personnes-vulnerables/secteurs/", {"commune_code": "13055"}).status_code == 403


@pytest.mark.django_db
class TestAssociationDeduite:
    """22/11/2026 : « Précisez l'association… » alors que l'écran n'envoie pas l'AASC."""

    def _sans_aasc(self, client, **entetes):
        return client.post(reverse("delegationgestion-list"), {
            "commune_code": "42186", "convention_signee_le": "2026-11-15"}, format="json", **entetes)

    def test_l_administrateur_qui_regarde_la_reserve(self, monde, create_user):
        admin = create_user(username="admin-deleg@test.fr", email="admin-deleg@test.fr", type="ADMIN")
        r = self._sans_aasc(_client(admin), HTTP_X_PERIMETRE=str(monde["aasc"].id))
        assert r.status_code == 201, r.data
        assert DelegationGestion.objects.get().aasc == monde["aasc"]

    def test_le_membre_d_une_seule_association_meme_si_son_contexte_est_ailleurs(self, monde):
        bureau = monde["bureau"]
        mairie = Institution.objects.create(nom="Mairie voisine", type=_type("mairie"), commune_code="42207")
        ContactInstitution.objects.create(institution=mairie, utilisateur=bureau, actif=True)
        bureau.institution = mairie
        bureau.save()
        r = self._sans_aasc(_client(bureau))
        assert r.status_code == 201, r.data
        assert DelegationGestion.objects.get().aasc == monde["aasc"]
