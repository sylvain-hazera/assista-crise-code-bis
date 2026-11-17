from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.utils import timezone

from core.models import Crisis, Information, Offer, Request


@pytest.mark.django_db
class TestCleanupCrises:
    """cleanup_crises référençait des noms de modèles/champs français (Crise, Demande, Offre,
    statut, nom...) qui n'existent plus dans le schéma actuel (Crisis, Request, Offer, status,
    name...) : la commande plantait à l'import dès qu'elle était invoquée, jamais exercée par
    la suite de tests — aucune purge de crise ancienne ne s'est donc jamais réellement
    produite. Corrigé + couvert ici."""

    def test_purges_crisis_closed_more_than_30_days_ago(self, request_type, offer_type, information_type):
        old_crisis = Crisis.objects.create(
            name="Crise ancienne", type="INCENDIE", location=Point(5.72, 45.18, srid=4326),
            end_date=timezone.now() - timedelta(days=45),
        )
        Request.objects.create(
            title="Demande ancienne", location=Point(5.72, 45.18, srid=4326),
            first_name_request="A", last_name_request="B", email_request="a@t.fr",
            phone_request="0600000000", request_type=request_type, crisis=old_crisis,
        )
        Offer.objects.create(
            title="Offre ancienne", first_name_offer="C", last_name_offer="D",
            email_offer="c@t.fr", offer_type=offer_type, crisis=old_crisis,
        )
        Information.objects.create(
            title="Signalement ancien", location=Point(5.72, 45.18, srid=4326),
            first_name_information="E", last_name_information="F", email_information="e@t.fr",
            phone_information="0600000000", information_type=information_type, crisis=old_crisis,
        )

        recent_crisis = Crisis.objects.create(
            name="Crise récente", type="INCENDIE", location=Point(5.72, 45.18, srid=4326),
            end_date=timezone.now() - timedelta(days=5),
        )
        ongoing_crisis = Crisis.objects.create(
            name="Crise en cours", type="INCENDIE", location=Point(5.72, 45.18, srid=4326),
        )

        call_command('cleanup_crises')

        # La crise reste : la supprimer emporterait main courante, rapports, biens sinistrés et
        # relogements (17/11/2026). Seules les données des habitants partent.
        old_crisis.refresh_from_db()
        assert old_crisis.donnees_habitants_purgees_le is not None
        assert not Request.objects.filter(crisis_id=old_crisis.id).exists()
        assert not Offer.objects.filter(crisis_id=old_crisis.id).exists()
        assert not Information.objects.filter(crisis_id=old_crisis.id).exists()
        assert Crisis.objects.filter(id=recent_crisis.id).exists()
        assert Crisis.objects.filter(id=ongoing_crisis.id).exists()

    def test_dry_run_deletes_nothing(self):
        old_crisis = Crisis.objects.create(
            name="Crise ancienne dry-run", type="INCENDIE", location=Point(5.72, 45.18, srid=4326),
            end_date=timezone.now() - timedelta(days=45),
        )

        call_command('cleanup_crises', '--dry-run')

        old_crisis.refresh_from_db()
        assert old_crisis.donnees_habitants_purgees_le is None

    def test_la_main_courante_survit_et_la_purge_ne_repasse_pas(self, capsys):
        from core.models import JournalCollectivite
        crise = Crisis.objects.create(
            name="Crise à mémoire", type="INCENDIE", location=Point(5.72, 45.18, srid=4326),
            end_date=timezone.now() - timedelta(days=45),
        )
        from core.models import Institution, InstitutionType
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie purge", type=itype)
        JournalCollectivite.objects.create(crise=crise, institution=mairie, contenu="Fin d'intervention")

        call_command('cleanup_crises')
        call_command('cleanup_crises')

        assert JournalCollectivite.objects.filter(crise=crise).exists()
        assert "Aucune crise close à purger" in capsys.readouterr().out

    def test_no_expired_crisis_is_a_noop(self):
        call_command('cleanup_crises')  # ne doit pas lever d'exception
