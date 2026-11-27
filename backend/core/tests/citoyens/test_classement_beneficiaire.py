"""Classement « quoi + pour qui » (27/11/2026) : core/classement.py, migration 0400.

Sylvain : « transport d'animaux » revenait à « animaux à évacuer ». Désormais une famille (le
quoi), un « pour qui » (personnes, animaux, biens) et, pour des animaux, une catégorie. Une
équipe spécialisée (« évacuation de chevaux ») est préférée, puis la plus générale.
"""
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core import classement
from core import messages_terrain as mt
from core.models import (
    AffectationCompetence, Besoin, BesoinCompetence, Competence, Crisis, Dossier, ImplicationInstitution,
    InformationType, Institution, InstitutionType, MessageTerrain, Mission, Offer, OfferType, Request, RequestType,
    RequestTypeBesoin, StatutImplication, Team, TypeImplication, User,
)

DEPOSANT = {"first_name_request": "Marie", "last_name_request": "Demandeuse", "email_request": "marie.classement@test.fr",
            "phone_request": "0600000000", "status": "NON_TRAITEE"}


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name="Crise classement", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def evac(db):
    """Une famille EVAC de test, avec sa cascade de compétences. La vraie famille EVAC de la base
    de test perd son code le temps du test : le code doit désigner une seule famille."""
    RequestType.objects.filter(code="EVAC").update(code=None)
    t = RequestType.objects.create(type="Évacuation test", code="EVAC")
    besoin = Besoin.objects.create(nom="Évacuation besoin test")
    RequestTypeBesoin.objects.create(request_type=t, besoin=besoin)
    generale = Competence.objects.create(nom="Transport test")
    animaux = Competence.objects.create(nom="Évacuation d'animaux test")
    equides = Competence.objects.create(nom="Évacuation d'équidés test")
    BesoinCompetence.objects.create(besoin=besoin, competence=generale)
    BesoinCompetence.objects.create(besoin=besoin, competence=animaux, beneficiaire="ANIMAUX")
    BesoinCompetence.objects.create(besoin=besoin, competence=equides, beneficiaire="ANIMAUX", categorie_animaux="EQUIDES")
    return dict(type=t, besoin=besoin, generale=generale, animaux=animaux, equides=equides)


def _demande(t, crise, **kw):
    return Request.objects.create(title="Classement", request_type=t, crisis=crise, location=Point(5.72, 45.18, srid=4326),
                                  first_name_request="A", last_name_request="B", email_request="c@test.fr",
                                  phone_request="0600000000", **kw)


def _equipe(nom, crise, competence):
    e = Team.objects.create(name=nom, description="", color="#000000")
    AffectationCompetence.objects.create(crise=crise, competence=competence, equipe=e, active=True)
    return e


@pytest.mark.django_db
class TestCascade:

    def test_du_plus_precis_au_plus_general(self, crise, evac):
        d = _demande(evac["type"], crise, beneficiaire="ANIMAUX", categorie_animaux="EQUIDES")
        assert classement.competences_pour_demande(d) == [evac["equides"], evac["animaux"], evac["generale"]]
        d2 = _demande(evac["type"], crise, beneficiaire="PERSONNES")
        assert classement.competences_pour_demande(d2) == [evac["generale"]]

    def test_l_equipe_chevaux_recoit_les_chevaux_et_sinon_l_equipe_animaux(self, crise, evac):
        animaux = _equipe("Équipe animaux", crise, evac["animaux"])
        _equipe("Équipe transport", crise, evac["generale"])
        chevaux = _demande(evac["type"], crise, beneficiaire="ANIMAUX", categorie_animaux="EQUIDES")
        assert classement.choisir(crise, classement.competences_pour_demande(chevaux), chevaux) == (evac["animaux"], animaux)
        equides = _equipe("Équipe chevaux", crise, evac["equides"])
        assert classement.choisir(crise, classement.competences_pour_demande(chevaux), chevaux) == (evac["equides"], equides)
        chiens = _demande(evac["type"], crise, beneficiaire="ANIMAUX", categorie_animaux="COMPAGNIE")
        assert classement.choisir(crise, classement.competences_pour_demande(chiens), chiens) == (evac["animaux"], animaux)

    def test_nourrir_et_evacuer_des_animaux_vont_a_deux_equipes_differentes(self, crise, evac):
        nour = RequestType.objects.create(type="Nourriture test", code="NOUR")
        b = Besoin.objects.create(nom="Nourriture besoin test")
        RequestTypeBesoin.objects.create(request_type=nour, besoin=b)
        nourrissage = Competence.objects.create(nom="Nourrissage test")
        BesoinCompetence.objects.create(besoin=b, competence=nourrissage, beneficiaire="ANIMAUX")
        e_nour = _equipe("Équipe nourrissage", crise, nourrissage)
        e_evac = _equipe("Équipe évacuation animaux", crise, evac["animaux"])
        a_nourrir = _demande(nour, crise, beneficiaire="ANIMAUX")
        a_evacuer = _demande(evac["type"], crise, beneficiaire="ANIMAUX")
        assert classement.choisir(crise, classement.competences_pour_demande(a_nourrir), a_nourrir)[1] == e_nour
        assert classement.choisir(crise, classement.competences_pour_demande(a_evacuer), a_evacuer)[1] == e_evac

    def test_sans_equipe_le_dossier_garde_la_competence_generale(self, crise, evac):
        d = _demande(evac["type"], crise, beneficiaire="ANIMAUX", categorie_animaux="EQUIDES")
        assert classement.choisir(crise, classement.competences_pour_demande(d), d) == (evac["generale"], None)

    def test_le_depot_public_cree_le_dossier_de_l_equipe_specialisee(self, crise, evac):
        chevaux = _equipe("Équipe chevaux API", crise, evac["equides"])
        payload = dict(DEPOSANT, title="Trois chevaux à sortir", location="POINT (5.72 45.18)",
                       request_type=str(evac["type"].id), crisis=str(crise.id), beneficiaire="ANIMAUX",
                       categorie_animaux="EQUIDES", nombre_animaux=3)
        with mock.patch("core.serializers.validate_crisis_open_and_monitored"):
            r = APIClient().post(reverse("request-list"), payload, format="json")
        assert r.status_code == 201, r.data
        dossier = Dossier.objects.get(demande_id=r.data["id"])
        assert (dossier.competence, dossier.equipe) == (evac["equides"], chevaux)

    def test_une_equipe_specialisee_affectee_ensuite_recupere_le_dossier(self, crise, evac):
        from core.views import resuggerer_dossiers

        d = _demande(evac["type"], crise, beneficiaire="ANIMAUX", categorie_animaux="EQUIDES")
        dossier = Dossier.objects.create(numero="DOS-CASC0001", crise=crise, competence=evac["generale"], demande=d,
                                         titre="x", statut=Dossier.Statut.EN_ATTENTE_AFFECTATION)
        chevaux = _equipe("Équipe chevaux tardive", crise, evac["equides"])
        assert resuggerer_dossiers(crise.id, evac["equides"].id) == 1
        dossier.refresh_from_db()
        assert (dossier.competence, dossier.equipe) == (evac["equides"], chevaux)


@pytest.mark.django_db
class TestPourQui:

    def test_admis_par_famille_et_par_axe(self, evac):
        soin = RequestType(type="Soins test", code="SOIN")
        assert classement.beneficiaires_admis(soin, "demande") == ["ANIMAUX"]
        assert classement.beneficiaires_admis(OfferType(type="Soins offre test", code="SOIN"), "offre") == ["PERSONNES", "ANIMAUX"]
        precision = RequestType(type="Groupe test", parent=RequestType(type="Matériel test", code="MAT"))
        assert classement.beneficiaires_admis(precision, "demande") == []

    def test_un_ancien_client_recoit_un_pour_qui_deduit(self, evac):
        attrs = {"request_type": evac["type"]}
        assert classement.normaliser(attrs, "demande") == {} and attrs["beneficiaire"] == "PERSONNES"
        offre = {"offer_type": OfferType(type="Transport offre test", code="EVAC"), "transport_type": "ANIMAUX"}
        assert classement.normaliser(offre, "offre") == {} and offre["beneficiaire"] == "ANIMAUX"

    def test_un_pour_qui_hors_famille_est_refuse(self):
        attrs = {"request_type": RequestType(type="Nettoyage test", code="NETT"), "beneficiaire": "ANIMAUX"}
        assert "beneficiaire" in classement.normaliser(attrs, "demande")

    def test_la_categorie_n_existe_que_pour_des_animaux(self, evac):
        attrs = {"request_type": evac["type"], "beneficiaire": "PERSONNES", "categorie_animaux": "EQUIDES", "nombre_animaux": 4}
        classement.normaliser(attrs, "demande")
        assert (attrs["categorie_animaux"], attrs["nombre_animaux"]) == (None, None)

    def test_libelle_radio_court(self, evac):
        assert classement.libelle_radio(evac["type"], "ANIMAUX") == "Évacuation test · animaux"
        assert classement.libelle_radio(RequestType(type="Matériel test", code="MAT"), None) == "Matériel test"


@pytest.mark.django_db
class TestEcoute:

    def test_une_association_equestre_n_ouvre_que_les_animaux(self, crise, evac):
        itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
        asso = Institution.objects.create(nom="Écurie solidaire", type=itype)
        implication = ImplicationInstitution.objects.create(
            crise=crise, institution=asso, actif=True, type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE, beneficiaires_ecoutes=["ANIMAUX"], categories_animaux_ecoutees=["EQUIDES"])
        implication.themes.set([evac["besoin"]])
        r = APIClient().get(reverse("types_a_lecoute"), {"crise": str(crise.id), "axe": "offer"})
        assert r.status_code == 200, r.data
        tid = str(evac["type"].id)
        # Le type de demande n'est pas une offre : on vérifie côté demande, sans restriction géographique simulée.
        from core.besoins_ecoute import restrictions_par_besoin
        assert restrictions_par_besoin(crise)[evac["besoin"].id] == ({"ANIMAUX"}, {"EQUIDES"})
        assert tid not in r.data["beneficiaires_par_type"]

    def test_une_mairie_sans_restriction_elargit(self, crise, evac):
        from core.besoins_ecoute import restrictions_par_besoin

        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "MAIRIE"})
        for nom, bens in (("Asso", ["ANIMAUX"]), ("Mairie", [])):
            inst = Institution.objects.create(nom=f"{nom} élargit", type=itype)
            i = ImplicationInstitution.objects.create(crise=crise, institution=inst, actif=True,
                                                      type_implication=TypeImplication.ACTEUR,
                                                      statut=StatutImplication.VALIDEE, beneficiaires_ecoutes=bens)
            i.themes.set([evac["besoin"]])
        assert restrictions_par_besoin(crise)[evac["besoin"].id] == (None, None)


@pytest.fixture
def terrain(db, evac):
    itype, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie BES", type=itype, commune_code="42186")
    benevole = User.objects.create_user(username="bes@test.fr", email="bes@test.fr", password="x", type="UTIL_SIMPLE",
                                        first_name="Léa", last_name="Martin")
    equipe = Team.objects.create(name="Équipe BES", institution=mairie, environment="PROD")
    equipe.members.add(benevole)
    crise = Crisis.objects.create(name="Crue BES", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
    mission = Mission.objects.create(titre="Évacuation", crise=crise, institution=mairie, statut="EN_COURS", environment="PROD")
    mission.equipes.add(equipe)
    return dict(benevole=benevole, equipe=equipe, mission=mission, crise=crise)


@pytest.mark.django_db
class TestBesoinParRadio:

    def test_ecrire_et_lire(self):
        texte = mt.ecrire_besoin("EVAC", "ANIMAUX", "EQUIDES", 45.5, 4.6, "3 chevaux dans un pré inondé, accès par le nord")
        assert texte == "EVAC·A·EQ 45.50000,4.60000 3 chevaux dans un pré inondé,"
        lu = mt.lire_besoin("Besoin relevé sur le terrain : " + texte)
        assert (lu["code"], lu["beneficiaire"], lu["categorie"], lu["latitude"], lu["longitude"]) == ("EVAC", "ANIMAUX", "EQUIDES", 45.5, 4.6)
        assert mt.lire_besoin("NETT") == {"code": "NETT", "beneficiaire": None, "categorie": None,
                                          "latitude": None, "longitude": None, "note": ""}

    def test_un_besoin_releve_par_radio_devient_une_demande_sans_donnee_d_habitant(self, terrain, evac):
        chevaux = _equipe("Équipe chevaux radio", terrain["crise"], evac["equides"])
        b = terrain["benevole"]
        texte = (f"Léa: ⚑BES {terrain['mission'].id.hex[:6]}.{b.id.hex[:6]}.c0ffee "
                 f"Besoin relevé sur le terrain : EVAC·A·EQ 45.50010,4.60010 3 chevaux")
        with mock.patch("core.notifications_application.prevenir"):
            message = mt.depuis_radio(texte, "MESHCORE")
        assert message is not None and message.type == "BESOIN"
        demande = Request.objects.get(crisis=terrain["crise"])
        assert (demande.request_type, demande.beneficiaire, demande.categorie_animaux, demande.nombre_animaux) == (
            evac["type"], "ANIMAUX", "EQUIDES", 3)
        assert demande.author == b and demande.first_name_request == "Léa"
        assert abs(demande.location.y - 45.5001) < 1e-6
        dossier = Dossier.objects.get(demande=demande)
        assert (dossier.competence, dossier.equipe) == (evac["equides"], chevaux)
        # Une seconde réception (l'autre radio) ne crée pas de seconde demande.
        with mock.patch("core.notifications_application.prevenir"):
            mt.depuis_radio(texte, "MESHTASTIC")
        assert Request.objects.filter(crisis=terrain["crise"]).count() == 1
        assert MessageTerrain.objects.get().canaux_recus == ["MESHCORE", "MESHTASTIC"]


def _migration_0400():
    import importlib

    return importlib.import_module("core.migrations.0400_reclassement_quoi_pour_qui")


@pytest.mark.django_db
class TestMigration:
    """La 0400 rejouée sur des données préparées comme celles de la production : les types
    « animaux » rejoignent leur famille, avec le bon pour qui ; rien n'est semé sur base vide."""

    def test_reclassement(self, crise):
        from django.apps import apps

        RequestType.objects.filter(type__in=["Transport", "Nourriture et eau", "Soins médicaux", "Soins",
                                             "Soutien aux animaux", "Assistance à évacuation"]).delete()
        transport = RequestType.objects.create(type="Transport")
        nourriture = RequestType.objects.create(type="Nourriture et eau")
        soutien = RequestType.objects.create(type="Soutien aux animaux")
        evac = RequestType.objects.create(type="Assistance à évacuation")
        RequestType.objects.create(type="Soins médicaux", actif=False)
        d1, d2, d3 = _demande(soutien, crise), _demande(evac, crise), _demande(transport, crise)
        Competence.objects.get_or_create(nom="Soutien aux animaux")
        Besoin.objects.get_or_create(nom="Transport")

        _migration_0400().reclasser(apps, None)

        for d in (d1, d2, d3):
            d.refresh_from_db()
        assert (d1.request_type, d1.beneficiaire) == (nourriture, "ANIMAUX")
        assert (d2.request_type, d2.beneficiaire) == (transport, "PERSONNES")
        assert d3.beneficiaire == "PERSONNES"
        soutien.refresh_from_db()
        evac.refresh_from_db()
        assert not soutien.actif and not evac.actif
        transport.refresh_from_db()
        assert transport.code == "EVAC"
        soins = RequestType.objects.get(type="Soins")
        assert soins.actif and soins.code == "SOIN"
        groupe = Competence.objects.get(nom="Soutien aux animaux")
        assert {"Évacuation d'équidés", "Nourrissage d'animaux"} <= set(groupe.sous_competences.values_list("nom", flat=True))
        assert BesoinCompetence.objects.filter(besoin__nom="Transport", beneficiaire="ANIMAUX", categorie_animaux="EQUIDES",
                                               competence__nom="Évacuation d'équidés").exists()

    def test_une_institution_qui_n_ecoutait_que_les_animaux_le_reste(self, crise):
        from django.apps import apps

        ancien, _ = Besoin.objects.get_or_create(nom="Soutien aux animaux")
        famille, _ = Besoin.objects.get_or_create(nom="Nourriture et eau")
        itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
        i = ImplicationInstitution.objects.create(crise=crise, institution=Institution.objects.create(nom="SPA", type=itype),
                                                  actif=True, type_implication=TypeImplication.ACTEUR,
                                                  statut=StatutImplication.VALIDEE)
        i.themes.set([ancien])

        _migration_0400().reclasser(apps, None)

        i.refresh_from_db()
        assert famille in i.themes.all() and ancien not in i.themes.all()
        assert i.beneficiaires_ecoutes == ["ANIMAUX"]
        ancien.refresh_from_db()
        assert not ancien.actif


@pytest.mark.django_db
class TestRequalifier:

    def test_le_pilotage_requalifie_et_le_dossier_va_a_l_equipe_specialisee(self, crise, evac, create_user):
        agent = create_user(username="requalif@test.fr", email="requalif@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=agent)
        chevaux = _equipe("Équipe chevaux requalif", crise, evac["equides"])
        d = _demande(evac["type"], crise, beneficiaire="PERSONNES")
        dossier = Dossier.objects.create(numero="DOS-REQ00001", crise=crise, competence=evac["generale"], demande=d,
                                         titre="x", statut=Dossier.Statut.EN_ATTENTE_AFFECTATION)
        r = client.post(reverse("dossier-requalifier", args=[dossier.id]),
                        {"beneficiaire": "ANIMAUX", "categorie_animaux": "EQUIDES"}, format="json")
        assert r.status_code == 200, r.data
        assert (r.data["demande_beneficiaire"], r.data["demande_categorie_animaux"]) == ("ANIMAUX", "EQUIDES")
        dossier.refresh_from_db()
        assert (dossier.competence, dossier.equipe) == (evac["equides"], chevaux)
        assert dossier.historique.filter(evenement__startswith="Requalifié").exists()

    def test_un_pour_qui_hors_famille_est_refuse(self, crise, create_user):
        agent = create_user(username="requalif2@test.fr", email="requalif2@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=agent)
        nett = RequestType.objects.create(type="Nettoyage requalif", code="NETT")
        d = _demande(nett, crise, beneficiaire="BIENS")
        dossier = Dossier.objects.create(numero="DOS-REQ00002", crise=crise, demande=d, titre="x",
                                         statut=Dossier.Statut.EN_ATTENTE_AFFECTATION)
        r = client.post(reverse("dossier-requalifier", args=[dossier.id]), {"beneficiaire": "ANIMAUX"}, format="json")
        assert r.status_code == 400 and "beneficiaire" in r.data


@pytest.mark.django_db
class TestSoinsAnciens:
    """Les demandes de soins d'août 2026 étaient pour des personnes (correctif 0401)."""

    def test_la_0401_les_remet_pour_des_personnes(self, crise):
        import datetime
        import importlib

        from django.apps import apps

        soins = RequestType.objects.filter(code="SOIN").first() or RequestType.objects.create(type="Soins test 0401", code="SOIN")
        ancienne = _demande(soins, crise, beneficiaire="ANIMAUX")
        Request.objects.filter(pk=ancienne.pk).update(created_at=datetime.datetime(2026, 8, 25, tzinfo=datetime.timezone.utc))
        recente = _demande(soins, crise, beneficiaire="ANIMAUX", categorie_animaux="EQUIDES")

        importlib.import_module("core.migrations.0401_soins_anciens_pour_des_personnes").corriger(apps, None)

        ancienne.refresh_from_db()
        recente.refresh_from_db()
        assert ancienne.beneficiaire == "PERSONNES"
        assert (recente.beneficiaire, recente.categorie_animaux) == ("ANIMAUX", "EQUIDES")

    def test_une_demande_ancienne_reste_modifiable(self, crise):
        soins = RequestType(type="Soins modif", code="SOIN")
        ancienne = Request(request_type=soins, beneficiaire="PERSONNES")
        assert classement.normaliser({"description": "précision"}, "demande", ancienne) == {}
        assert classement.normaliser({"beneficiaire": "PERSONNES"}, "demande", ancienne) == {}
        # Mais on ne crée pas, ni ne bascule, une demande de soins pour une personne.
        assert "beneficiaire" in classement.normaliser({"request_type": soins, "beneficiaire": "PERSONNES"}, "demande")
