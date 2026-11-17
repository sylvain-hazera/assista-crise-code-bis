"""Sur une crise à plusieurs communes, chaque mairie accepte chez elle (17/11/2026).

Avant : la déclaration d'une association n'avait qu'UN statut. La première mairie qui répondait
la faisait passer à « validée » et les autres ne pouvaient plus rien décider ; pire, un
« Valider » sans commune nommée lui ouvrait toute la crise, communes voisines comprises.

Même circuit pour la réserve communale d'une AUTRE commune venue en renfort (`renfort`).
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    Besoin, Commune, ContactInstitution, Crisis, ImplicationInstitution, Institution,
    InstitutionType,
)
from core.zone_scoping import viewer_perimetre

A, B, C = "42001", "42002", "42003"


@pytest.fixture
def type_mairie(db):
    return InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})[0]


@pytest.fixture
def crise(db):
    for code in (A, B, C):
        Commune.objects.update_or_create(code=code, defaults={"nom": f"Commune {code}"})
    return Crisis.objects.create(
        name="Crue à trois communes", type="INONDATION", location="POINT (4.2 45.5)",
        zone_communes=[A, B, C],
    )


def _mairie(create_user, type_mairie, crise, code, impliquee=True):
    """Une mairie, son régulateur, et (par défaut) sa présence sur la crise."""
    mairie = Institution.objects.create(nom=f"Mairie {code}", type=type_mairie, commune_code=code)
    user = create_user(username=f"maire-{code}@accord.fr", email=f"maire-{code}@accord.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    if impliquee:
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie, type_implication="IMPLIQUE", utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return mairie, user, client


@pytest.fixture
def mairie_a(create_user, type_mairie, crise):
    return _mairie(create_user, type_mairie, crise, A)


@pytest.fixture
def mairie_b(create_user, type_mairie, crise):
    return _mairie(create_user, type_mairie, crise, B)


@pytest.fixture
def association(create_user, db):
    itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    asso = Institution.objects.create(nom="Casques d'essai", type=itype)
    user = create_user(username="asso@accord.fr", email="asso@accord.fr", type="SECOURS")
    user.institution = asso
    user.save()
    ContactInstitution.objects.create(institution=asso, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return asso, user, client


@pytest.fixture
def declaration(association, crise):
    asso, user, _ = association
    return ImplicationInstitution.objects.create(
        crise=crise, institution=asso, type_implication="ACTEUR", utilisateur=user,
        actif=True, statut="EN_ATTENTE",
    )


def _url(nom, implication):
    return reverse(f'implicationinstitution-{nom}', args=[implication.id])


def _requete(user):
    from django.test import RequestFactory
    request = RequestFactory().get("/")
    request.user = user
    return request


@pytest.mark.django_db
class TestChaqueMairieChezElle:

    def test_valider_sans_nommer_de_commune_n_accorde_que_la_sienne(self, mairie_a, declaration):
        """LE trou : ce même appel ouvrait toute la crise, B et C comprises."""
        reponse = mairie_a[2].post(_url('valider', declaration))

        assert reponse.status_code == 200, reponse.data
        declaration.refresh_from_db()
        assert declaration.statut == "VALIDEE"
        assert declaration.communes == [A]

    def test_la_seconde_mairie_accepte_a_son_tour(self, mairie_a, mairie_b, declaration, association):
        mairie_a[2].post(_url('valider', declaration))

        reponse = mairie_b[2].post(_url('valider', declaration))

        assert reponse.status_code == 200, reponse.data
        declaration.refresh_from_db()
        assert declaration.communes == [A, B]
        # Et c'est bien ce que l'association voit : A et B, pas C.
        assert viewer_perimetre(_requete(association[1])) == [("commune", A), ("commune", B)]

    def test_le_refus_d_une_mairie_ne_ferme_rien_chez_sa_voisine(self, mairie_a, mairie_b, declaration):
        assert mairie_a[2].post(_url('refuser', declaration)).status_code == 200
        declaration.refresh_from_db()
        assert declaration.statut == "EN_ATTENTE"            # B et C n'ont pas répondu
        assert declaration.communes_refusees == [A]

        assert mairie_b[2].post(_url('valider', declaration)).status_code == 200
        declaration.refresh_from_db()
        assert (declaration.statut, declaration.communes, declaration.communes_refusees) == ("VALIDEE", [B], [A])

    def test_refusee_seulement_quand_toutes_ont_refuse(self, create_user, type_mairie, crise, mairie_a, mairie_b, declaration):
        mairie_c = _mairie(create_user, type_mairie, crise, C)
        for mairie in (mairie_a, mairie_b):
            mairie[2].post(_url('refuser', declaration))
        declaration.refresh_from_db()
        assert declaration.statut == "EN_ATTENTE"
        mairie_c[2].post(_url('refuser', declaration))
        declaration.refresh_from_db()
        assert declaration.statut == "REFUSEE"

    def test_une_mairie_retire_son_accord_sans_toucher_a_celui_de_l_autre(self, mairie_a, mairie_b, declaration):
        mairie_a[2].post(_url('valider', declaration))
        mairie_b[2].post(_url('valider', declaration))

        assert mairie_a[2].post(_url('refuser', declaration)).status_code == 200

        declaration.refresh_from_db()
        assert (declaration.statut, declaration.communes, declaration.communes_refusees) == ("VALIDEE", [B], [A])

    def test_on_ne_decide_pas_pour_la_commune_d_a_cote(self, mairie_a, declaration):
        reponse = mairie_a[2].post(_url('valider', declaration), {"communes": [B]}, format="json")
        assert reponse.status_code == 403
        reponse = mairie_a[2].post(_url('decider', declaration), {"refusees": [B]}, format="json")
        assert reponse.status_code == 403
        declaration.refresh_from_db()
        assert (declaration.statut, declaration.communes, declaration.communes_refusees) == ("EN_ATTENTE", [], [])

    def test_une_mairie_touchee_decide_meme_sans_s_etre_declaree(self, create_user, type_mairie, crise, declaration):
        """Sa commune est dans la zone : elle n'a pas à s'inscrire pour dire qui vient chez elle."""
        _, _, client = _mairie(create_user, type_mairie, crise, B, impliquee=False)
        assert client.post(_url('valider', declaration)).status_code == 200
        declaration.refresh_from_db()
        assert declaration.communes == [B]

    def test_une_mairie_etrangere_a_la_crise_ne_decide_rien(self, create_user, type_mairie, crise, declaration):
        _, _, client = _mairie(create_user, type_mairie, crise, "42999", impliquee=False)
        assert client.post(_url('valider', declaration)).status_code == 403

    def test_repondre_deux_fois_la_meme_chose_est_refuse(self, mairie_a, declaration):
        mairie_a[2].post(_url('valider', declaration))
        assert mairie_a[2].post(_url('valider', declaration)).status_code == 400

    def test_l_association_acceptee_chez_a_ne_s_accorde_pas_le_reste(self, mairie_a, declaration, association):
        """`communes` était modifiable par le déclarant : un PATCH ouvrait toute la crise."""
        mairie_a[2].post(_url('valider', declaration))
        declaration.themes.add(Besoin.objects.create(nom="Logistique accord"))

        reponse = association[2].patch(
            reverse('implicationinstitution-detail', args=[declaration.id]),
            {"communes": [], "commentaire": "merci"}, format="json",
        )

        assert reponse.status_code == 200, reponse.data
        declaration.refresh_from_db()
        assert declaration.communes == [A]

    def test_une_mairie_accueillie_chez_sa_voisine_n_y_accepte_personne(self, mairie_a, mairie_b, crise, declaration):
        """A, déclarée acteur, voit toute la crise ; ce n'est pas pour autant elle qui dit qui
        entre chez B."""
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie_a[0], type_implication="ACTEUR", actif=True, statut="VALIDEE")
        reponse = mairie_a[2].get(_url('zone-delegable', declaration))
        assert [c["code"] for c in reponse.data["communes"]] == [A]

    def test_chacun_voit_ce_qui_l_attend_lui(self, mairie_a, mairie_b, declaration):
        mairie_a[2].post(_url('valider', declaration))

        vue_a = mairie_a[2].get(reverse('implicationinstitution-detail', args=[declaration.id])).data
        vue_b = mairie_b[2].get(reverse('implicationinstitution-detail', args=[declaration.id])).data

        assert (vue_a["peut_valider"], vue_a["accord"]["a_moi_acceptees"]) == (False, [A])
        assert (vue_b["peut_valider"], vue_b["accord"]["a_moi_en_attente"]) == (True, [B])
        assert (vue_b["accord"]["acceptees"], vue_b["accord"]["en_attente"]) == (1, 2)

    def test_la_fenetre_envoie_accords_et_retraits_ensemble(self, create_user, type_mairie, crise, declaration):
        """Une collectivité qui tient deux communes de la crise par convention."""
        from core.models import Competence, DelegationCompetence
        epci, user, client = _mairie(create_user, type_mairie, crise, A)
        DelegationCompetence.objects.create(
            institution_source=epci, institution_cible=epci, active=True, communes=[B],
            competence=Competence.objects.get_or_create(nom="Appui accord")[0],
        )
        client.post(_url('valider', declaration), {"communes": [A, B]}, format="json")

        reponse = client.post(_url('decider', declaration), {"acceptees": [A], "refusees": [B]}, format="json")

        assert reponse.status_code == 200, reponse.data
        declaration.refresh_from_db()
        assert (declaration.communes, declaration.communes_refusees) == ([A], [B])


@pytest.mark.django_db
class TestCeQuiNeChangePas:

    def test_une_institution_publique_reste_acceptee_d_office_et_irrecusable(self, mairie_a, mairie_b, crise):
        declaration = ImplicationInstitution.objects.create(
            crise=crise, institution=mairie_b[0], type_implication="ACTEUR", actif=True, statut="VALIDEE")
        assert mairie_a[2].post(_url('refuser', declaration)).status_code == 400
        declaration.refresh_from_db()
        assert declaration.statut == "VALIDEE"

    def test_qui_couvre_toute_la_crise_l_accorde_en_bloc(self, create_user, type_mairie, declaration):
        """Mono-commune : la mairie couvre la crise, l'accord reste « toute la zone » et suit
        donc la crise si elle s'étend."""
        crise = declaration.crise
        crise.zone_communes = [A]
        crise.save(update_fields=["zone_communes"])
        _, _, client = _mairie(create_user, type_mairie, crise, A)
        assert client.post(_url('valider', declaration)).status_code == 200
        declaration.refresh_from_db()
        assert (declaration.statut, declaration.communes) == ("VALIDEE", [])


@pytest.mark.django_db
class TestRenfortDUneReserveCommunale:

    def _declarer(self, client, mairie, crise, **extra):
        theme = Besoin.objects.create(nom="Hébergement accord")
        return client.post(reverse('implicationinstitution-list'), {
            "crise": str(crise.id), "institution": str(mairie.id), "type_implication": "ACTEUR",
            "themes": [str(theme.id)], **extra,
        }, format="json")

    def test_une_mairie_en_renfort_attend_l_accord_et_n_etend_pas_la_zone(self, create_user, type_mairie, crise, mairie_a):
        voisine, user, client = _mairie(create_user, type_mairie, crise, "42777", impliquee=False)

        reponse = self._declarer(client, voisine, crise, renfort=True)

        assert reponse.status_code == 201, reponse.data
        assert reponse.data["statut"] == "EN_ATTENTE"
        crise.refresh_from_db()
        assert "42777" not in crise.zone_communes              # elle n'est pas sinistrée
        assert viewer_perimetre(_requete(user)) == [("commune", "42777")]

        declaration = ImplicationInstitution.objects.get(id=reponse.data["id"])
        assert mairie_a[2].post(_url('valider', declaration)).status_code == 200
        assert ("commune", A) in viewer_perimetre(_requete(user))
        crise.refresh_from_db()
        assert "42777" not in crise.zone_communes

    def test_sans_renfort_rien_ne_change_pour_une_mairie(self, create_user, type_mairie, crise):
        voisine, _, client = _mairie(create_user, type_mairie, crise, "42778", impliquee=False)
        reponse = self._declarer(client, voisine, crise)
        assert reponse.data["statut"] == "VALIDEE"
        crise.refresh_from_db()
        assert "42778" in crise.zone_communes

    def test_le_renfort_ne_se_retire_pas_apres_coup(self, create_user, type_mairie, crise):
        voisine, _, client = _mairie(create_user, type_mairie, crise, "42779", impliquee=False)
        identifiant = self._declarer(client, voisine, crise, renfort=True).data["id"]
        client.patch(reverse('implicationinstitution-detail', args=[identifiant]), {"renfort": False}, format="json")
        assert ImplicationInstitution.objects.get(id=identifiant).renfort is True
