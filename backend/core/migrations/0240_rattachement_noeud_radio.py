"""« Ce nœud est à nous », pour le matériel que personne ne porte (voir
RattachementNoeudRadio).

Aucune donnée à reprendre : avant cette table, un répéteur n'était rattaché à personne et seul
un administrateur de la plateforme pouvait le régler."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0239_acces_radio'),
    ]

    operations = [
        migrations.CreateModel(
            name='RattachementNoeudRadio',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('node_num', models.PositiveBigIntegerField(help_text="Nœud visé. Unique : deux responsables pour un même appareil ne veut rien dire, et c'est ce qui rend les conflits visibles plutôt que silencieux.", unique=True)),
                ('libelle', models.CharField(blank=True, help_text="Comment on l'appelle sur le terrain, ex. « répéteur du château d'eau » — le nom annoncé par le firmware ne dit pas toujours où il est.", max_length=100)),
                ('note', models.TextField(blank=True)),
                ('date_rattachement', models.DateTimeField(auto_now_add=True)),
                ('institution', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='noeuds_radio_rattaches', to='core.institution')),
                ('rattache_par', models.ForeignKey(blank=True, help_text="Qui l'a rattaché — un rattachement ouvre un droit d'écriture, il doit être imputable.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='rattachements_noeuds_radio_poses', to=settings.AUTH_USER_MODEL)),
                ('utilisateur', models.ForeignKey(blank=True, help_text='Pour un répéteur qui appartient à une personne (un radioamateur qui en a posé un chez lui) et non à une collectivité.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='noeuds_radio_rattaches', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['institution'], name='core_rattac_institu_e3b444_idx'), models.Index(fields=['utilisateur'], name='core_rattac_utilisa_8ed0f7_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('institution__isnull', False), ('utilisateur__isnull', False), _connector='OR'), name='ck_rattachement_noeud_radio_une_cible')],
            },
        ),
    ]
