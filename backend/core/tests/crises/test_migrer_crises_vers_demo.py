"""Déplacer des crises de la production vers la zone de démonstration (18/11/2026)."""
import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.db import connection
from rest_framework.test import APIClient

from core.models import (
    AppelStandard, AuditLog, ContactInstitution, Crisis, Dossier, DossierCommentaire, ImplicationInstitution,
    Institution, InstitutionType, Request, RequestType, TypeImplication,
)


@pytest.fixture
def scene(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie de la migration", type=itype, commune_code="42186")
    maire = create_user(username="maire@migr.fr", email="maire@migr.fr", type="AUT_LOCALE", first_name="Claire", last_name="Fontaine")
    maire.institution = mairie
    maire.demo_role = "AUT_LOCALE"
    maire.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=maire, actif=True)
    crise = Crisis.objects.create(name="Crue réelle", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
    autre = Crisis.objects.create(name="Autre crise", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
    ImplicationInstitution.objects.create(crise=crise, institution=mairie, responsable=maire, type_implication=TypeImplication.ACTEUR, actif=True)
    rtype, _ = RequestType.objects.get_or_create(type="Matériel")
    demande = Request.objects.create(title="Cave inondée", description="Appelez-moi au 06 12 34 56 78 ou jean@courriel.fr",
                                     first_name_request="Jean", last_name_request="Durand", email_request="jean@courriel.fr",
                                     phone_request="0612345678", request_type=rtype, crisis=crise)
    dossier = Dossier.objects.create(numero="DOS-MIGR1", titre="Cave", description="Cave", crise=crise, demande=demande)
    DossierCommentaire.objects.create(dossier=dossier, auteur=maire, commentaire="Rappeler M. Durand au 0612345678")
    AppelStandard.objects.create(institution=mairie, crise=crise, numero=1, nature="DEMANDE_AIDE", objet="Cave",
                                 appelant_nom="Jean Durand", appelant_telephone="0612345678", lieu="3 rue Haute")
    return {"mairie": mairie, "maire": maire, "crise": crise, "autre": autre, "demande": demande, "dossier": dossier}


@pytest.mark.django_db
class TestMigration:

    def test_par_defaut_rien_ne_change(self, scene, mailoutbox):
        call_command("migrer_crises_vers_demo", crises=str(scene["crise"].id))
        scene["crise"].refresh_from_db(); scene["demande"].refresh_from_db()
        assert scene["crise"].environment == "PROD" and scene["demande"].last_name_request == "Durand" and mailoutbox == []

    def test_la_crise_part_en_demo_anonymisee_et_le_responsable_est_prevenu(self, scene, mailoutbox):
        call_command("migrer_crises_vers_demo", crises=str(scene["crise"].id), appliquer=True)
        crise, demande, dossier = (Crisis.objects.get(pk=scene["crise"].pk), Request.objects.get(pk=scene["demande"].pk),
                                   Dossier.objects.get(pk=scene["dossier"].pk))
        assert (crise.environment, demande.environment, dossier.environment) == ("DEMO", "DEMO", "DEMO")
        assert ImplicationInstitution.objects.get(crise=crise).environment == "DEMO"
        # Les personnes : plus rien de réel.
        assert (demande.first_name_request, demande.last_name_request, demande.phone_request) == ("Prénom", demande.last_name_request, "0600000000")
        assert "Durand" not in demande.last_name_request and demande.email_request.endswith("@exemple.invalide")
        assert "06 12 34 56 78" not in demande.description and "jean@courriel.fr" not in demande.description
        commentaire = DossierCommentaire.objects.get(dossier=dossier)
        assert commentaire.environment == "DEMO" and "0612345678" not in commentaire.commentaire
        appel = AppelStandard.objects.get(crise=crise)
        assert "Durand" not in appel.appelant_nom and appel.lieu == "Adresse anonymisée"
        # Et rien en clair en base.
        with connection.cursor() as curseur:
            curseur.execute("SELECT last_name_request FROM core_request WHERE id = %s", [str(demande.id)])
            assert "Personne" not in curseur.fetchone()[0]
        # L'autre crise n'a pas bougé.
        assert Crisis.objects.get(pk=scene["autre"].pk).environment == "PROD"
        # Le responsable est prévenu, une fois.
        (courriel,) = mailoutbox
        assert courriel.to == ["maire@migr.fr"] and "Crue réelle" in courriel.body and "Démo" in courriel.body

    def test_le_responsable_retrouve_sa_crise_en_zone_de_demonstration(self, scene):
        call_command("migrer_crises_vers_demo", crises=str(scene["crise"].id), appliquer=True, sans_courriel=True)
        client = APIClient()
        client.force_authenticate(user=scene["maire"])
        en_demo = client.get("/api/crises/", HTTP_X_ENVIRONMENT="DEMO").data
        en_prod = client.get("/api/crises/").data
        noms = lambda d: {c["name"] for c in (d["results"] if isinstance(d, dict) else d)}
        assert "Crue réelle" in noms(en_demo) and "Crue réelle" not in noms(en_prod)

    def test_une_crise_inconnue_arrete_tout(self, scene):
        from django.core.management.base import CommandError
        with pytest.raises(CommandError):
            call_command("migrer_crises_vers_demo", crises=f"{scene['crise'].id},00000000-0000-0000-0000-000000000000", appliquer=True)
        assert Crisis.objects.get(pk=scene["crise"].pk).environment == "PROD"
