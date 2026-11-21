"""Failles d'accès corrigées le 21/11/2026 (lot 0 de la délégation de gestion).

Trouvées en préparant la délégation de gestion mairie → AASC :
1. DelegationCompetence : seul le rôle était vérifié. Tout compte d'institution pouvait créer
   une délégation au nom de n'importe quelle mairie vers sa propre institution, sans crise ni
   secteur ; avec la compétence « Recensement personnes vulnérables », il lisait le registre de
   toutes les communes. La liste était lisible par tous, et toute délégation modifiable.
2. Plans et zones : `?institution=` court-circuitait le filtre de périmètre.
3. Institution du payload non vérifiée : annuaire PCS et création d'équipe.
4. Crise : tout acteur institutionnel pouvait modifier n'importe quelle crise.
"""
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    AuditLog, Competence, ContactInstitution, Crisis, DelegationCompetence, ImplicationInstitution,
    Institution, InstitutionType, PersonneVulnerable, Plan,
)
from core.vulnerabilites import (
    NOM_COMPETENCE_VULNERABILITES, VERSION_ENGAGEMENT_SECRET_REGISTRE,
    filter_personnes_vulnerables_queryset,
)


def _type(code):
    t, _ = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})
    return t


@pytest.fixture
def mairie(db):
    return Institution.objects.create(nom="Mairie de Saint-Exemple test", type=_type("mairie"),
                                      commune_code="42186", departement_code="42")


@pytest.fixture
def autre_mairie(db):
    return Institution.objects.create(nom="Mairie voisine test", type=_type("mairie"),
                                      commune_code="42207", departement_code="42")


@pytest.fixture
def aasc(db):
    return Institution.objects.create(nom="AASC test", type=_type("aasc"))


def _membre(create_user, institution, email, type_compte):
    user = create_user(username=email, email=email, type=type_compte)
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    user.institution = institution
    user.save(update_fields=["institution"])
    return user


@pytest.fixture
def maire(create_user, mairie):
    return _membre(create_user, mairie, "maire-faille@test.fr", "AUT_LOCALE")


@pytest.fixture
def benevole_aasc(create_user, aasc):
    return _membre(create_user, aasc, "aasc-faille@test.fr", "SECOURS")


@pytest.fixture
def admin(create_user):
    return create_user(username="admin-faille@test.fr", email="admin-faille@test.fr", type="ADMIN")


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def registre(db):
    return Competence.objects.get_or_create(nom=NOM_COMPETENCE_VULNERABILITES)[0]


@pytest.fixture
def competence(db):
    return Competence.objects.create(nom="Logistique faille test")


URL = "delegationcompetence-list"


@pytest.mark.django_db
class TestDelegationCompetence:

    def test_un_tiers_ne_delegue_pas_au_nom_d_une_mairie(self, benevole_aasc, mairie, aasc, registre):
        r = _client(benevole_aasc).post(reverse(URL), {
            "institution_source": str(mairie.id), "institution_cible": str(aasc.id),
            "competence": str(registre.id), "communes": ["42186"]}, format="json")
        assert r.status_code == 403
        assert not DelegationCompetence.objects.exists()

    def test_un_tiers_ne_delegue_pas_une_autre_competence_non_plus(self, benevole_aasc, mairie, aasc, competence):
        r = _client(benevole_aasc).post(reverse(URL), {
            "institution_source": str(mairie.id), "institution_cible": str(aasc.id),
            "competence": str(competence.id), "communes": ["42186"]}, format="json")
        assert r.status_code == 403

    def test_le_maire_delegue_son_registre_sur_sa_commune(self, maire, mairie, aasc, registre):
        r = _client(maire).post(reverse(URL), {
            "institution_source": str(mairie.id), "institution_cible": str(aasc.id),
            "competence": str(registre.id), "communes": ["42186"]}, format="json")
        assert r.status_code == 201, r.data

    def test_on_ne_delegue_pas_la_commune_voisine(self, maire, mairie, aasc, competence):
        r = _client(maire).post(reverse(URL), {
            "institution_source": str(mairie.id), "institution_cible": str(aasc.id),
            "competence": str(competence.id), "communes": ["42207"]}, format="json")
        assert r.status_code == 400
        assert "42207" in str(r.data)

    def test_hors_crise_un_secteur_est_obligatoire(self, maire, mairie, aasc, competence):
        r = _client(maire).post(reverse(URL), {
            "institution_source": str(mairie.id), "institution_cible": str(aasc.id),
            "competence": str(competence.id)}, format="json")
        assert r.status_code == 400

    def test_l_administrateur_ne_delegue_pas_un_registre(self, admin, mairie, aasc, registre):
        r = _client(admin).post(reverse(URL), {
            "institution_source": str(mairie.id), "institution_cible": str(aasc.id),
            "competence": str(registre.id), "communes": ["42186"]}, format="json")
        assert r.status_code == 403

    def test_la_liste_ne_montre_que_ses_delegations(self, benevole_aasc, mairie, autre_mairie, aasc, competence):
        DelegationCompetence.objects.create(institution_source=mairie, institution_cible=autre_mairie,
                                            competence=competence, communes=["42186"])
        mienne = DelegationCompetence.objects.create(institution_source=mairie, institution_cible=aasc,
                                                     competence=competence, communes=["42186"])
        r = _client(benevole_aasc).get(reverse(URL))
        ids = {d["id"] for d in (r.data["results"] if isinstance(r.data, dict) else r.data)}
        assert ids == {str(mienne.id)}

    def test_la_cible_ne_modifie_ni_ne_supprime_la_delegation(self, benevole_aasc, mairie, aasc, competence):
        d = DelegationCompetence.objects.create(institution_source=mairie, institution_cible=aasc,
                                                competence=competence, communes=["42186"])
        url = reverse("delegationcompetence-detail", args=[d.id])
        c = _client(benevole_aasc)
        assert c.patch(url, {"communes": ["42186", "42207"]}, format="json").status_code == 403
        assert c.delete(url).status_code == 403
        assert DelegationCompetence.objects.filter(pk=d.pk).exists()

    def test_la_suppression_est_journalisee(self, maire, mairie, aasc, competence):
        d = DelegationCompetence.objects.create(institution_source=mairie, institution_cible=aasc,
                                                competence=competence, communes=["42186"])
        r = _client(maire).delete(reverse("delegationcompetence-detail", args=[d.id]))
        assert r.status_code == 204
        # commentaire chiffré : jamais de filtre SQL dessus, on relit en Python.
        lignes = AuditLog.objects.filter(objet_id=d.id, objet_type="DelegationCompetence")
        assert any((l.commentaire or "").startswith("Suppression") for l in lignes)


@pytest.mark.django_db
def test_une_delegation_sans_secteur_n_ouvre_plus_tout_le_registre(rf, benevole_aasc, mairie, aasc, registre):
    """Créée directement en base (comme avant le correctif) : elle n'ouvre que la commune de la
    mairie qui délègue, plus celle des voisines."""
    DelegationCompetence.objects.create(institution_source=mairie, institution_cible=aasc, competence=registre)
    for code in ("42186", "42207"):
        PersonneVulnerable.objects.create(nom=f"Nom {code}", prenom="P", commune_code=code,
                                          institution_declarante=mairie, cree_par=benevole_aasc)
    benevole_aasc.engagement_secret_registre_le = timezone.now()
    benevole_aasc.engagement_secret_registre_version = VERSION_ENGAGEMENT_SECRET_REGISTRE
    benevole_aasc.save()
    requete = rf.get("/")
    requete.user = benevole_aasc
    visibles = filter_personnes_vulnerables_queryset(requete, PersonneVulnerable.objects.all())
    assert set(visibles.values_list("commune_code", flat=True)) == {"42186"}


@pytest.mark.django_db
class TestPlansEtZones:

    def test_institution_en_parametre_n_elargit_plus(self, benevole_aasc, mairie):
        plan = Plan.objects.create(nom="Plan inondation", institution=mairie)
        c = _client(benevole_aasc)
        r = c.get(reverse("plan-list"), {"institution": str(mairie.id)})
        lignes = r.data["results"] if isinstance(r.data, dict) else r.data
        assert lignes == []
        url = reverse("plan-detail", args=[plan.id]) + f"?institution={mairie.id}"
        assert c.patch(url, {"nom": "Pirate"}, format="json").status_code == 404
        assert c.delete(url).status_code == 404

    def test_le_membre_voit_toujours_son_plan(self, maire, mairie):
        Plan.objects.create(nom="Plan inondation", institution=mairie)
        r = _client(maire).get(reverse("plan-list"), {"institution": str(mairie.id)})
        lignes = r.data["results"] if isinstance(r.data, dict) else r.data
        assert len(lignes) == 1


@pytest.mark.django_db
class TestInstitutionDuPayload:

    def test_annuaire_d_une_autre_collectivite_refuse(self, create_user, autre_mairie, mairie):
        agent = _membre(create_user, autre_mairie, "agent-voisin@test.fr", "AUT_LOCALE")
        r = _client(agent).post(reverse("interlocuteuralertepcs-list"), {
            "institution": str(mairie.id), "nom": "Faux SIDPC", "organisme": "Préfecture"}, format="json")
        assert r.status_code == 403

    def test_equipe_chez_une_autre_institution_refusee(self, benevole_aasc, mairie):
        r = _client(benevole_aasc).post(reverse("team-list"), {
            "name": "Équipe pirate", "institution": str(mairie.id)}, format="json")
        assert r.status_code == 403


@pytest.mark.django_db
class TestModificationDeCrise:

    @pytest.fixture
    def crise(self, db):
        return Crisis.objects.create(name="Crue test faille", type="INONDATION", location="POINT (4.6 45.5)")

    def test_une_institution_etrangere_ne_modifie_pas_la_crise(self, benevole_aasc, crise):
        r = _client(benevole_aasc).patch(reverse("crisis-detail", args=[crise.id]),
                                         {"name": "Renommée"}, format="json")
        assert r.status_code == 403
        crise.refresh_from_db()
        assert crise.name == "Crue test faille"

    def test_une_institution_impliquee_la_modifie(self, maire, mairie, crise):
        ImplicationInstitution.objects.create(crise=crise, institution=mairie, type_implication="ACTEUR",
                                              statut="VALIDEE", actif=True)
        r = _client(maire).patch(reverse("crisis-detail", args=[crise.id]),
                                 {"name": "Crue du Gier — 22 novembre"}, format="json")
        assert r.status_code == 200, r.data
