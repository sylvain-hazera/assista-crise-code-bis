"""Une association existante rejoint le réseau ; son étendue d'intervention (26/11/2026)."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core import adhesion_association as aa
from core.models import Commune, ContactInstitution, DemandeAdhesionAssociation, Institution, InstitutionType


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def communes(db):
    # Floirac et Bordeaux : même métropole ; Libourne : même département ; Pau : même zone (Sud-Ouest),
    # autre région ; Lille : ailleurs.
    for code, nom, epci, dep, reg in [("33167", "Floirac", "243300316", "33", "75"), ("33063", "Bordeaux", "243300316", "33", "75"),
                                      ("33243", "Libourne", "200070092", "33", "75"), ("64445", "Pau", "200067254", "64", "75"),
                                      ("87085", "Limoges", "248719312", "87", "75"), ("59350", "Lille", "200093201", "59", "32")]:
        Commune.objects.update_or_create(code=code, defaults={"nom": nom, "epci_code": epci, "departement_code": dep, "region_code": reg})


@pytest.fixture
def admin(create_user):
    return create_user(username="admin@essai.fr", email="admin@essai.fr", type="ADMIN")


@pytest.mark.django_db
class TestEtendue:
    def _asso(self, echelon):
        itype, _ = InstitutionType.objects.get_or_create(code="association", defaults={"libelle": "Association"})
        return Institution(nom="FCBA", type=itype, commune_code="33167", echelon_intervention=echelon)

    @pytest.mark.parametrize("echelon,dedans,dehors", [
        ("COMMUNE", ["33167"], ["33063"]),
        ("EPCI", ["33063"], ["33243"]),
        ("DEPARTEMENT", ["33243"], ["64445"]),
        ("REGION", ["87085", "64445"], ["59350"]),
        ("NATIONAL", ["59350"], []),
    ])
    def test_echelons_depuis_le_siege(self, communes, echelon, dedans, dehors):
        asso = self._asso(echelon)
        assert all(aa.commune_dans_etendue(asso, c) for c in dedans)
        assert not any(aa.commune_dans_etendue(asso, c) for c in dehors)

    def test_zone_de_defense(self, communes):
        asso = self._asso("ZONE")
        assert aa.commune_dans_etendue(asso, "64445")          # Pau : zone Sud-Ouest
        assert not aa.commune_dans_etendue(asso, "59350")      # Lille : zone Nord

    def test_libelles_vus_depuis_floirac(self, communes):
        r = reverse("association_etendue")
        echelons = {e["code"]: e["territoire"] for e in APIClient().get(r, {"commune": "33167"}).data["echelons"]}
        assert echelons["COMMUNE"] == "Floirac" and echelons["DEPARTEMENT"] == "Gironde"
        assert "Sud-Ouest" in echelons["ZONE"]


@pytest.mark.django_db
class TestAdhesion:
    def _deposer(self, client, **extra):
        corps = {"nom": "Floirac Citizen Band Amitié", "activite": "Signaleurs radio sur les courses cyclistes",
                 "commune_code": "33167", "echelon": "DEPARTEMENT", "fonction": "Président"}
        corps.update(extra)
        return client.post(reverse("adhesion_demandes"), corps, format="json")

    def test_demande_puis_acceptation_le_demandeur_devient_le_bureau(self, communes, create_user, admin):
        president = create_user(username="pres@fcba.fr", email="pres@fcba.fr", type="VOLUNTEER")
        reponse = self._deposer(_client(president))
        assert reponse.status_code == 201, reponse.data
        assert reponse.data["territoire"] == "Gironde"
        # Une seule demande en attente à la fois.
        assert self._deposer(_client(president)).status_code == 400
        accepte = _client(admin).post(reverse("adhesion_demande", args=[reponse.data["id"]]), {"geste": "accepter"}, format="json")
        assert accepte.status_code == 200, accepte.data
        institution = Institution.objects.get(id=accepte.data["institution"])
        assert institution.type.code == "association" and institution.echelon_intervention == "DEPARTEMENT"
        contact = ContactInstitution.objects.get(institution=institution, utilisateur=president)
        assert contact.membre_bureau and contact.contact_principal
        president.refresh_from_db()
        assert president.type == "SECOURS" and president.institution_id == institution.id
        # Le bureau change librement l'étendue.
        url = reverse("association_echelon", args=[institution.id])
        assert _client(president).put(url, {"echelon": "NATIONAL"}, format="json").data["echelon"] == "NATIONAL"
        # Un même nom ensuite : orienté vers la candidature de membre.
        autre = create_user(username="autre@fcba.fr", email="autre@fcba.fr", type="VOLUNTEER")
        refus = self._deposer(_client(autre), nom="floirac citizen band amitie")
        assert refus.status_code == 400 and "membre" in refus.data["detail"]

    def test_agrement_declare_donne_une_aasc(self, communes, create_user, admin):
        president = create_user(username="pres@aasc.fr", email="pres@aasc.fr", type="VOLUNTEER")
        d = self._deposer(_client(president), nom="Secouristes de Floirac", agrement="A, B ; arrêté 2025-12").data
        _client(admin).post(reverse("adhesion_demande", args=[d["id"]]), {"geste": "accepter"}, format="json")
        assert Institution.objects.get(id=DemandeAdhesionAssociation.objects.get().institution_id).type.code.lower() == "aasc"

    def test_refus_motive_et_reserve_a_l_administrateur(self, communes, create_user, admin):
        president = create_user(username="pres2@fcba.fr", email="pres2@fcba.fr", type="VOLUNTEER")
        d = self._deposer(_client(president)).data
        url = reverse("adhesion_demande", args=[d["id"]])
        assert _client(president).post(url, {"geste": "accepter"}, format="json").status_code == 403
        assert _client(admin).post(url, {"geste": "refuser"}, format="json").status_code == 400
        assert _client(admin).post(url, {"geste": "refuser", "motif": "Doublon de l'association X"}, format="json").data["statut"] == "REFUSEE"

    def test_rien_en_clair(self, communes, create_user):
        from django.db import connection
        president = create_user(username="pres3@fcba.fr", email="pres3@fcba.fr", type="VOLUNTEER")
        self._deposer(_client(president), telephone="0601020304")
        with connection.cursor() as c:
            c.execute("SELECT nom, activite, telephone FROM core_demandeadhesionassociation")
            nom, activite, tel = c.fetchone()
        assert "Floirac" not in nom and "cyclistes" not in activite and "0601" not in tel


@pytest.mark.django_db
def test_proposer_son_aide_seulement_dans_son_etendue(communes, create_user):
    from core.models import Besoin, Crisis
    itype, _ = InstitutionType.objects.get_or_create(code="association", defaults={"libelle": "Association"})
    fcba = Institution.objects.create(nom="FCBA essai", type=itype, commune_code="33167", echelon_intervention="DEPARTEMENT")
    pres = create_user(username="pres4@fcba.fr", email="pres4@fcba.fr", type="SECOURS")
    pres.institution = fcba
    pres.save()
    ContactInstitution.objects.create(institution=fcba, utilisateur=pres, actif=True, membre_bureau=True)
    besoin = Besoin.objects.first() or Besoin.objects.create(nom="Signalisation")
    url = lambda c: reverse("crisis-proposer-aide", args=[str(c.id)])
    lille = Crisis.objects.create(name="Crue à Lille", type="INONDATION", location="POINT (3.06 50.63)", zone_communes=["59350"])
    reponse = _client(pres).post(url(lille), {"institution": str(fcba.id), "themes": [besoin.pk]}, format="json")
    assert reponse.status_code == 400 and "en dehors" in reponse.data["error"]
    libourne = Crisis.objects.create(name="Crue à Libourne", type="INONDATION", location="POINT (-0.24 44.92)", zone_communes=["33243"])
    assert _client(pres).post(url(libourne), {"institution": str(fcba.id), "themes": [besoin.pk]}, format="json").status_code in (200, 201)
