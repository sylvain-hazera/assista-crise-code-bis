"""Organisation (arbre institution → filles → équipes) et revue des droits (23/11/2026)."""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import rcsc
from core.models import (
    AffectationRoleOperationnel, AuditLog, ContactInstitution, HabilitationRegistreVulnerables, Institution,
    InstitutionType, RevueDroits, RoleOperationnel, Team, UserRole,
)


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def porge(db, create_user):
    t, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie du Porge", type=t, commune_code="33333", commune_nom="Le Porge", actif=True)
    Team.objects.create(name="Mairie du Porge", institution=mairie)
    reserve = rcsc.creer_pour(mairie)
    maire = create_user(username="maire-orga@test.fr", email="maire-orga@test.fr", type=UserRole.LOCAL_AUTHORITY,
                        first_name="Camille", last_name="Maire")
    ContactInstitution.objects.create(institution=mairie, utilisateur=maire, actif=True, contact_principal=True)
    maire.institution = mairie
    maire.last_login = timezone.now()
    maire.save()
    reserviste = create_user(username="res-orga@test.fr", email="res-orga@test.fr", type=UserRole.LOCAL_AUTHORITY,
                             first_name="Dominique", last_name="Reserve")
    reserviste.institution = mairie
    reserviste.last_login = timezone.now() - datetime.timedelta(days=200)
    reserviste.save()
    fiche = ContactInstitution.objects.create(institution=reserve, utilisateur=reserviste, actif=True,
                                              fonction="Réserviste", membre_bureau=True)
    Team.objects.get(institution=reserve).members.add(reserviste)
    return {"mairie": mairie, "reserve": reserve, "maire": maire, "reserviste": reserviste, "fiche": fiche}


@pytest.mark.django_db
class TestOrganisation:
    def test_l_arbre_de_la_mairie_montre_sa_reserve_et_son_equipe(self, porge):
        r = _client(porge["maire"]).get(reverse("organisation"))
        assert r.status_code == 200, r.data
        [tete] = r.data["arbres"]
        assert tete["nom"] == "Mairie du Porge" and tete["membres"] == 1
        [fille] = tete["filles"]
        assert fille["rcsc"] and fille["nom"] == "Réserve communale du Porge"
        assert fille["equipes"][0]["rcsc"] and fille["equipes"][0]["membres"] == 1

    def test_un_citoyen_n_a_pas_d_arbre(self, create_user):
        citoyen = create_user(username="cit-orga@test.fr", email="cit-orga@test.fr", type=UserRole.SIMPLE_USER)
        assert _client(citoyen).get(reverse("organisation")).status_code == 403


@pytest.mark.django_db
class TestRevueDroits:
    def test_la_matrice_reunit_les_droits_et_releve_les_anomalies(self, porge):
        role, _ = RoleOperationnel.objects.get_or_create(code="RESPONSABLE", defaults={"libelle": "Responsable"})
        AffectationRoleOperationnel.objects.create(utilisateur=porge["reserviste"], institution=porge["reserve"], role=role, actif=True)
        HabilitationRegistreVulnerables.objects.create(institution=porge["mairie"], utilisateur=porge["reserviste"],
                                                       fonction="Chef de réserve", accordee_par=porge["maire"])
        r = _client(porge["maire"]).get(reverse("revue-droits"))
        assert r.status_code == 200, r.data
        ligne = next(l for l in r.data["lignes"] if l["nom"] == "Dominique Reserve")
        assert ligne["institution_nom"] == "Réserve communale du Porge" and ligne["membre_bureau"]
        assert ligne["institution_travail"] == "Mairie du Porge"
        assert [x["code"] for x in ligne["roles"]] == ["RESPONSABLE"]
        assert ligne["habilite_registre"] and not ligne["engagement_signe"]
        codes = {a["code"] for a in ligne["anomalies"]}
        assert {"INACTIF_AVEC_DROITS", "HABILITATION_SANS_ENGAGEMENT", "JAMAIS_REVU"} <= codes
        assert r.data["resume"]["a_revoir"] == 2

    def test_decisions_tracees_et_appliquees(self, porge):
        client = _client(porge["maire"])
        url = reverse("revue-droits-decision")
        r = client.post(url, {"contact": str(porge["fiche"].id), "decision": "BUREAU_RETIRE", "commentaire": "Fin de mandat"}, format="json")
        assert r.status_code == 201, r.data
        porge["fiche"].refresh_from_db()
        assert not porge["fiche"].membre_bureau
        revue = RevueDroits.objects.get(contact=porge["fiche"])
        assert revue.revu_par == porge["maire"] and revue.commentaire == "Fin de mandat"
        assert AuditLog.objects.filter(objet_type="RevueDroits").exists()
        # Confirmer : plus « jamais revu ».
        client.post(url, {"contact": str(porge["fiche"].id), "decision": "CONFIRME"}, format="json")
        ligne = next(l for l in client.get(reverse("revue-droits")).data["lignes"] if l["nom"] == "Dominique Reserve")
        assert "JAMAIS_REVU" not in {a["code"] for a in ligne["anomalies"]}

    def test_on_ne_retire_pas_ses_propres_droits(self, porge):
        fiche_maire = ContactInstitution.objects.get(utilisateur=porge["maire"])
        r = _client(porge["maire"]).post(reverse("revue-droits-decision"),
                                         {"contact": str(fiche_maire.id), "decision": "CONTACT_DESACTIVE"}, format="json")
        assert r.status_code == 400

    def test_un_simple_membre_ne_fait_pas_la_revue(self, porge, create_user):
        membre = create_user(username="membre-orga@test.fr", email="membre-orga@test.fr", type=UserRole.SIMPLE_USER)
        ContactInstitution.objects.create(institution=porge["reserve"], utilisateur=membre, actif=True)
        membre.institution = porge["mairie"]
        membre.save()
        r = _client(membre).get(reverse("revue-droits"), {"institution": str(porge["mairie"].id)})
        assert r.status_code == 403

    def test_export_csv(self, porge):
        r = _client(porge["maire"]).get(reverse("revue-droits-export"))
        assert r.status_code == 200
        contenu = r.content.decode("utf-8-sig")
        assert "Dominique Reserve" in contenu and "Réserve communale du Porge" in contenu

    def test_le_menu_sait_qui_fait_la_revue(self, porge):
        moi = _client(porge["maire"]).get(reverse("auth_me")).data
        assert moi["acces_revue_droits"] is True
