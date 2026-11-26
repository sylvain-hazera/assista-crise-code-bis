"""Ce que la commune partage avec l'association pour une manifestation (26/11/2026)."""
import datetime

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import partage_manifestation as pm
from core.models import (
    ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType, LignePartage, Notification,
    PartageManifestation,
)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def scene(db, create_user):
    t_asso, _ = InstitutionType.objects.get_or_create(code="association", defaults={"libelle": "Association"})
    t_mairie, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    asso = Institution.objects.create(nom="Radio-club essai", type=t_asso, commune_code="33167")
    mairie = Institution.objects.create(nom="Mairie de Floirac (essai)", type=t_mairie, commune_code="33167")
    sans_compte = Institution.objects.create(nom="Mairie de Cenon (essai)", type=t_mairie, commune_code="33119",
                                             email="mairie@cenon.exemple")
    bureau = create_user(username="b@asso.fr", email="b@asso.fr", type="SECOURS")
    lea = create_user(username="lea@asso.fr", email="lea@asso.fr", type="VOLUNTEER")
    agent = create_user(username="agent@floirac.fr", email="agent@floirac.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=asso, utilisateur=bureau, actif=True, membre_bureau=True)
    ContactInstitution.objects.create(institution=asso, utilisateur=lea, actif=True)
    ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
    return {"asso": asso, "mairie": mairie, "sans_compte": sans_compte, "bureau": _client(bureau), "lea": _client(lea),
            "agent": _client(agent), "lea_user": lea}


def _publier(scene, communes=("33167",), demandes=None, debut=None):
    debut = debut or timezone.now() + datetime.timedelta(hours=2)
    corps = {"institution": str(scene["asso"].id), "type": "SIGNALISATION_RADIO", "titre": "Course de Floirac",
             "debut": debut.isoformat(), "fin": (debut + datetime.timedelta(hours=4)).isoformat(),
             "communes": list(communes), "postes": [{"intitule": "Carrefour", "places": 3}]}
    if demandes is not None:
        corps["demandes"] = demandes
    m = scene["bureau"].post(reverse("manifestations"), corps, format="json").data
    scene["bureau"].post(reverse("manifestation_geste", args=[m["id"]]), {"geste": "publier"}, format="json")
    return m


@pytest.mark.django_db
class TestPartage:
    def test_publication_invite_les_communes_selon_qu_elles_ont_un_compte(self, scene):
        _publier(scene, communes=("33167", "33119", "33999"))
        etats = dict(PartageManifestation.objects.values_list("commune_code", "invitation"))
        assert etats == {"33167": "PREVENUE", "33119": "INVITEE", "33999": "INJOIGNABLE"}
        assert any("Manifestation sur votre commune" in n.titre for n in Notification.objects.all())
        # Les quatre demandes par défaut.
        assert LignePartage.objects.filter(partage__commune_code="33167").count() == 4

    def test_la_mairie_accepte_et_l_association_voit_le_contact(self, scene):
        m = _publier(scene)
        partage = PartageManifestation.objects.get()
        url = reverse("partage_commune", args=[partage.id])
        # L'association ne décide pas pour la mairie.
        assert scene["bureau"].post(url, {"geste": "accepter", "element": "CONTACT_JOUR_J"}, format="json").status_code == 403
        scene["agent"].post(url, {"geste": "accepter", "element": "CONTACT_JOUR_J"}, format="json")
        scene["agent"].patch(url, {"referent_nom": "Agent d'astreinte", "referent_telephone": "0556000000"}, format="json")
        fiche = scene["lea"].get(reverse("manifestation", args=[m["id"]])).data
        assert fiche["partages"][0]["ouvert"]["contact"]["telephone"] == "0556000000"
        # La liste de la mairie.
        liste = scene["agent"].get(reverse("manifestations_commune")).data["partages"]
        assert liste[0]["manifestation"]["titre"] == "Course de Floirac" and len(liste[0]["lignes"]) == 7

    def test_l_association_ne_peut_pas_s_offrir_le_pcs_mais_la_mairie_si(self, scene):
        m = _publier(scene, demandes=["PCS_LECTURE", "CONTACT_JOUR_J"])
        partage = PartageManifestation.objects.get()
        assert not partage.lignes.filter(element="PCS_LECTURE").exists()      # demande ignorée
        url_pcs = reverse("partage_pcs", args=[partage.id])
        assert scene["bureau"].get(url_pcs).status_code == 403
        scene["agent"].post(reverse("partage_commune", args=[partage.id]), {"geste": "offrir", "element": "PCS_LECTURE"}, format="json")
        assert scene["bureau"].get(url_pcs).status_code == 200
        assert scene["lea"].get(url_pcs).status_code == 403                  # pas du bureau
        # Une demande ne s'offre pas.
        refus = scene["agent"].post(reverse("partage_commune", args=[partage.id]), {"geste": "offrir", "element": "CONTACT_JOUR_J"}, format="json")
        assert refus.status_code == 400

    def test_fenetre_de_validite_et_annulation(self, scene):
        m = _publier(scene, debut=timezone.now() + datetime.timedelta(days=5))
        partage = PartageManifestation.objects.get()
        pm.decider(partage.lignes.get(element="CONTACT_JOUR_J"), partage.mairie.contacts.first().utilisateur, "accepter")
        assert not pm.accorde(partage, "CONTACT_JOUR_J")                     # pas encore la veille
        assert pm.accorde(partage, "CONTACT_JOUR_J", maintenant=timezone.now() + datetime.timedelta(days=4, hours=12))
        scene["bureau"].post(reverse("manifestation_geste", args=[m["id"]]), {"geste": "annuler"}, format="json")
        assert set(partage.lignes.values_list("statut", flat=True)) == {"RETIRE"}

    def test_alertes_de_la_commune_et_crise_sur_la_commune(self, scene):
        m = _publier(scene)
        partage = PartageManifestation.objects.get()
        scene["lea"].post(reverse("manifestation_poste", args=[m["postes"][0]["id"]]), {"geste": "inscrire"}, format="json")
        agent = partage.mairie.contacts.first().utilisateur
        for e in ("ALERTES_COMMUNE", "CRISE_COMMUNE"):
            pm.decider(partage.lignes.get(element=e), agent, "accepter")
        assert scene["lea_user"] in pm.personnes_alertees(partage.mairie)
        crise = Crisis.objects.create(name="Orage sur Floirac", type="AUTRE", location="POINT (-0.52 44.83)", zone_communes=["33167"])
        crise.save()                                                            # deuxième enregistrement : pas de doublon
        assert sum("Orage sur Floirac" in n.titre for n in Notification.objects.filter(utilisateur=scene["lea_user"])) == 1

    def test_intervenir_sur_une_crise_engage_l_association(self, scene):
        _publier(scene)
        partage = PartageManifestation.objects.get()
        crise = Crisis.objects.create(name="Crue", type="INONDATION", location="POINT (-0.52 44.83)", zone_communes=["33167"])
        r = scene["agent"].post(reverse("partage_commune", args=[partage.id]),
                                {"geste": "offrir", "element": "INTERVENTION_CRISE", "crise": str(crise.id)}, format="json")
        assert r.status_code == 200, r.data
        implication = ImplicationInstitution.objects.get(crise=crise, institution=scene["asso"])
        assert implication.statut == "VALIDEE" and implication.communes == ["33167"]

    def test_rien_en_clair(self, scene):
        _publier(scene)
        partage = PartageManifestation.objects.get()
        scene["agent"].patch(reverse("partage_commune", args=[partage.id]),
                             {"referent_nom": "Jeanne Astreinte", "consignes": "Parking interdit rue Pasteur"}, format="json")
        with connection.cursor() as c:
            c.execute("SELECT referent_nom, consignes FROM core_partagemanifestation")
            nom, consignes = c.fetchone()
        assert "Jeanne" not in nom and "Pasteur" not in consignes


@pytest.mark.django_db
def test_menu_signale_un_compte_d_association(scene, create_user):
    u = create_user(username="menu@asso.fr", email="menu@asso.fr", type="SECOURS")
    u.institution = scene["asso"]
    u.save()
    assert _client(u).get(reverse("compteurs-menu")).data["association"] is True


@pytest.mark.django_db
def test_le_bureau_place_un_point_et_la_mairie_le_voit(scene):
    m = _publier(scene)
    poste = m["postes"][0]
    assert poste["latitude"] is None
    # Placer seulement : l'intitulé et les horaires ne bougent pas.
    r = scene["bureau"].patch(reverse("manifestation_poste", args=[poste["id"]]),
                              {"latitude": 44.83, "longitude": -0.52, "type_point": "SIGNALISATION"}, format="json")
    assert r.status_code == 200, r.data
    apres = r.data["postes"][0]
    assert apres["intitule"] == "Carrefour" and apres["type_point"] == "SIGNALISATION"
    # Un simple inscrit ne déplace rien.
    assert scene["lea"].patch(reverse("manifestation_poste", args=[poste["id"]]), {"latitude": 1, "longitude": 1},
                              format="json").status_code == 403
    points = scene["agent"].get(reverse("manifestations_commune")).data["partages"][0]["points"]
    assert points == [{"intitule": "Carrefour", "type_point_libelle": "Point de signalisation", "type_point": "SIGNALISATION",
                       "latitude": pytest.approx(44.83), "longitude": pytest.approx(-0.52)}]
