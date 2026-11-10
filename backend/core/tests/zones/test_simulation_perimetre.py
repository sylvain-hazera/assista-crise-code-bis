"""Périmètre de l'outil « Simulation d'inondation » et motif du refus (29/10/2026).

Constaté en production : une personne dont l'institution couvre Le Porge (33333) a ouvert Arès
(33011) puis Andernos-les-Bains (33005), deux communes d'une autre intercommunalité. Le serveur
a refusé — à juste titre — mais ni le sélecteur ni le message ne lui ont jamais dit sur quoi
portaient ses droits : le sélecteur interroge le référentiel national, et le refus se contentait
de « Vous n'avez pas accès à cette commune pour cet outil ».
"""
import pytest
from rest_framework.test import APIClient

from core.models import Institution, InstitutionType, User, UserRole

URL_PERIMETRE = "/api/simulation-inondation/perimetre/"
LE_PORGE, ARES = "33333", "33011"
EPCI_MEDULLIENNE, EPCI_COBAN = "243301389", "243301504"


def _institution(code_type, niveau, **codes):
    itype, _ = InstitutionType.objects.get_or_create(
        code=code_type, defaults={"libelle": code_type})
    institution = Institution.objects.create(nom=f"Institution {code_type}", type=itype, **codes)
    # Posé après coup : Institution.save() ne recalcule le secteur que depuis commune_code, via
    # un appel réseau qu'un test ne doit pas déclencher.
    Institution.objects.filter(pk=institution.pk).update(
        secteur_niveau_effectif=niveau, secteur_nom=f"Secteur {niveau}")
    institution.refresh_from_db()
    return institution


def _compte(email, institution, type_role=UserRole.LOCAL_AUTHORITY):
    return User.objects.create_user(
        username=email, email=email, password="MotDePasse!2026",
        type=type_role, institution=institution,
    )


def _requete(user):
    """Objet minimal attendu par les helpers : un `user` et de quoi résoudre l'environnement."""
    from django.test import RequestFactory

    requete = RequestFactory().get("/api/simulation-inondation/")
    requete.user = user
    return requete


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestPerimetre:
    def test_une_mairie_est_bornee_a_sa_commune(self):
        institution = _institution("MAIRIE_PERIM_TEST", "commune", commune_code=LE_PORGE)
        reponse = _client(_compte("maire-perim@exemple.fr", institution)).get(URL_PERIMETRE)

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["portee"] == "secteur"
        assert (reponse.data["champ"], reponse.data["valeur"]) == ("code", LE_PORGE)

    def test_un_niveau_epci_borne_sur_l_intercommunalite(self):
        """Le couple (champ, valeur) est repris tel quel par le sélecteur, qui interroge
        geo.api.gouv.fr : pas de liste de communes à transporter, et rien ne dépend de la
        complétude du référentiel local."""
        institution = _institution(
            "EPCI_PERIM_TEST", "epci", commune_code=LE_PORGE, epci_code=EPCI_MEDULLIENNE)
        reponse = _client(_compte("epci-perim@exemple.fr", institution)).get(URL_PERIMETRE)

        assert (reponse.data["champ"], reponse.data["valeur"]) == ("codeEpci", EPCI_MEDULLIENNE)

    def test_un_administrateur_n_est_pas_borne(self):
        reponse = _client(_compte(
            "admin-perim@exemple.fr", None, UserRole.ADMINISTRATOR)).get(URL_PERIMETRE)

        assert reponse.data["portee"] == "nationale"

    def test_un_secteur_sans_code_ne_fait_pas_semblant_d_ouvrir_tout(self):
        """Ne rien restreindre rouvrirait les 35 000 communes alors que l'API les refusera."""
        institution = _institution("SANS_CODE_PERIM_TEST", "epci")
        reponse = _client(_compte("sans-code-perim@exemple.fr", institution)).get(URL_PERIMETRE)

        assert reponse.data["portee"] == "aucune"

    def test_un_compte_sans_institution_n_a_aucun_perimetre(self):
        reponse = _client(_compte("sans-inst-perim@exemple.fr", None)).get(URL_PERIMETRE)

        assert reponse.data["portee"] == "aucune"

    def test_anonyme_refuse(self):
        assert APIClient().get(URL_PERIMETRE).status_code in (401, 403)


@pytest.mark.django_db
class TestMotifDuRefus:
    def test_le_refus_nomme_le_secteur_et_la_commune_demandee(self):
        """« Vous n'avez pas accès à cette commune » ne disait ni sur quoi portaient ses
        droits, ni à qui s'adresser : la seule conduite possible était de réessayer."""
        institution = _institution("MAIRIE_MOTIF_TEST", "epci",
                                   commune_code=LE_PORGE, epci_code=EPCI_MEDULLIENNE)
        client = _client(_compte("motif@exemple.fr", institution))

        reponse = client.get(f"/api/simulation-inondation/{ARES}/")

        assert reponse.status_code == 403
        message = reponse.data["error"]
        assert "intercommunalité" in message
        assert "Secteur epci" in message
        assert ARES in message

    def test_une_commune_du_secteur_est_acceptee(self):
        """Vérifié sur la porte elle-même plutôt que par HTTP : passé le contrôle, la vue
        déclenche une tâche Celery, absente du conteneur de test."""
        from core.habitations import peut_simuler_commune

        institution = _institution("MAIRIE_OK_TEST", "commune", commune_code=LE_PORGE)
        requete = _requete(_compte("accepte@exemple.fr", institution))

        assert peut_simuler_commune(requete, LE_PORGE) is True
        assert peut_simuler_commune(requete, ARES) is False

    def test_un_compte_sans_secteur_recoit_un_motif_different(self):
        client = _client(_compte("sans-secteur@exemple.fr", None))

        reponse = client.get(f"/api/simulation-inondation/{ARES}/")

        assert reponse.status_code == 403
        assert "rattachés à une collectivité" in reponse.data["error"]


@pytest.mark.django_db
class TestDenormalisationDuSecteur:
    """`Institution.save()` dénormalise epci/département/région depuis la commune.

    Ce test existe parce que ce fichier échouait par intermittence (10/11/2026) : la
    dénormalisation **écrasait** un `epci_code` fourni explicitement, y compris quand elle
    n'avait rien à mettre à la place. `commune_secteur_codes` passe par `_resolve_commune`, qui
    interroge `geo.api.gouv.fr` avec un budget d'appels et une temporisation ; budget épuisé ou
    service lent, elle rend des codes vides. Le test posait un EPCI, `save()` le jetait, et le
    périmètre tombait à « aucune » — donc `KeyError: 'champ'`, à des centaines de tests de la
    cause.

    La perte dépassait le test : une institution dont on connaissait le rattachement le perdait
    silencieusement au premier enregistrement fait pendant une indisponibilité du service.
    """

    def _institution_brute(self, **codes):
        itype, _ = InstitutionType.objects.get_or_create(
            code="MAIRIE_DENORM", defaults={"libelle": "Mairie"})
        return Institution(nom="Mairie denormalisation", type=itype, **codes)

    def test_une_resolution_qui_echoue_ne_perd_pas_le_rattachement_connu(self, monkeypatch):
        # `Institution.save()` importe `commune_secteur_codes` à l'appel, pas au chargement du
        # module : remplacer l'attribut du module suffit, et c'est ce qui rend ce test possible
        # sans toucher au réseau.
        from core import geo_lookup

        # Résolution indisponible : c'est exactement ce que rend `commune_secteur_codes` quand
        # le budget d'appels est épuisé.
        monkeypatch.setattr(
            geo_lookup, "commune_secteur_codes",
            lambda code: {"epci_code": None, "departement_code": None, "region_code": None},
        )

        institution = self._institution_brute(
            commune_code=LE_PORGE, epci_code=EPCI_MEDULLIENNE,
            departement_code="33", region_code="75",
        )
        institution.save()
        institution.refresh_from_db()

        assert institution.epci_code == EPCI_MEDULLIENNE
        assert institution.departement_code == "33"
        assert institution.region_code == "75"

    def test_une_resolution_qui_aboutit_fait_foi(self, monkeypatch):
        """La commune reste la source de vérité : un code calculé non vide gagne, même contre
        une valeur posée à la main. Sinon une institution rattachée au mauvais EPCI y resterait."""
        from core import geo_lookup

        monkeypatch.setattr(
            geo_lookup, "commune_secteur_codes",
            lambda code: {"epci_code": EPCI_COBAN, "departement_code": "33",
                          "region_code": "75"},
        )

        institution = self._institution_brute(
            commune_code=LE_PORGE, epci_code=EPCI_MEDULLIENNE,
        )
        institution.save()
        institution.refresh_from_db()

        assert institution.epci_code == EPCI_COBAN

    def test_un_premier_enregistrement_remplit_depuis_la_commune(self, monkeypatch):
        from core import geo_lookup

        monkeypatch.setattr(
            geo_lookup, "commune_secteur_codes",
            lambda code: {"epci_code": EPCI_COBAN, "departement_code": "33",
                          "region_code": "75"},
        )

        institution = self._institution_brute(commune_code=LE_PORGE)
        institution.save()
        institution.refresh_from_db()

        assert institution.epci_code == EPCI_COBAN
        assert institution.departement_code == "33"
