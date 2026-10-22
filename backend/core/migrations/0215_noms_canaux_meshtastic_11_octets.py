import unicodedata

from django.db import migrations


def _valide(nom):
    ascii_ = unicodedata.normalize('NFKD', nom).encode('ascii', 'ignore').decode()
    return ''.join(ch for ch in ascii_ if ch.isalnum() or ch in '-_')[:11]


def raccourcir(apps, schema_editor):
    """Canaux d'équipe dont le nom dépasse la limite du firmware (11 octets) : même règle que
    core.views._nom_canal_meshtastic_equipe (« EquipeCAI », « LesCuvesPom »). Les membres
    devront reconfigurer ce canal : il ne pouvait de toute façon pas être saisi tel quel."""
    CanalMeshtastic = apps.get_model('core', 'CanalMeshtastic')
    for canal in CanalMeshtastic.objects.filter(equipe__isnull=False).select_related('equipe'):
        if len(canal.nom.encode('utf-8')) <= 11:
            continue
        nom = _valide(canal.equipe.name.strip())
        if not nom.lower().startswith('equipe') and len(f"Equipe{nom}") <= 11:
            nom = f"Equipe{nom}"
        canal.nom = nom
        canal.save(update_fields=['nom'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0214_provisioncanalmeshcore'),
    ]

    operations = [
        migrations.RunPython(raccourcir, migrations.RunPython.noop),
    ]
