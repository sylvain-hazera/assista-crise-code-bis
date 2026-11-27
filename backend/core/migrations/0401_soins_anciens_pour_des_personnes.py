"""Correctif de la 0400 (27/11/2026) : les demandes « Soins médicaux » d'août 2026 étaient des
soins pour des personnes. La 0400 a renommé le type en « Soins » (désormais pour des animaux
seulement) et leur a donné le seul « pour qui » de la famille : animaux. Elles redeviennent
« personnes ». Toutes datent d'avant le retrait de la demande de soins (01/09/2026)."""
import datetime

from django.db import migrations

RETRAIT = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)


def corriger(apps, schema_editor):
    Request = apps.get_model("core", "Request")
    Request.objects.filter(request_type__code="SOIN", beneficiaire="ANIMAUX", created_at__lt=RETRAIT).update(
        beneficiaire="PERSONNES", categorie_animaux=None, nombre_animaux=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0400_reclassement_quoi_pour_qui"),
    ]

    operations = [
        migrations.RunPython(corriger, migrations.RunPython.noop),
    ]
