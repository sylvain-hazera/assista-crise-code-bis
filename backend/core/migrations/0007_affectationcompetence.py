# imports nécessaires
import django.db.models.deletion
import uuid
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_competence_team_competences'),
    ]

    operations = [
        migrations.CreateModel(
            name='AffectationCompetence',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('active', models.BooleanField(default=True)),
                ('date_debut', models.DateTimeField(auto_now_add=True)),
                ('date_fin', models.DateTimeField(blank=True, null=True)),
                ('commentaire', models.TextField(blank=True, null=True)),
                ('competence', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='affectations', to='core.competence')),
                ('crise', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='affectations_competences', to='core.crisis')),
                ('equipe', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='affectations', to='core.team')),
            ],
        ),
    ]
