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
