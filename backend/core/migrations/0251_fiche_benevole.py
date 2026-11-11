"""Fiche d'un bénévole d'association : adresse géocodée et déclarations d'adhésion.

**Alignée sur le modèle des RESSOURCES** (`Offer`, `Habitation`) et non inventée : adresse
texte, point géocodé, `ban_id`, et le secteur dénormalisé (commune, EPCI, département, région).
Un bénévole se cherche et se filtre donc comme une offre d'aide, sans mécanisme nouveau —
« une ressource particulière, qui se trouve être membre de l'association ».

Conséquence voulue : le département d'affectation vient du GÉOCODAGE et non d'un préfixe de code
postal. Un code postal n'est pas un code commune (Corse 2A/2B, outre-mer à trois chiffres, zéro
initial mangé par un tableur) ; `commune_code` tranche exactement.

Rattachée à l'UTILISATEUR et non au rattachement associatif, pour la raison déjà écrite sur
`QualificationMembre` : une adresse appartient à la personne, pas à l'association.

`diplome_premier_secours` est DÉCLARATIF et reste distinct de `QualificationMembre`, qui porte
les qualifications vérifiées avec leurs dates et leur justificatif. Les confondre ferait passer
une case cochée à l'inscription pour un diplôme contrôlé par le bureau.

Table vide à la création ; aucune reprise de données.
"""

import core.crypto_fields
import django.contrib.gis.db.models.fields
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0250_matrix_hostname_institution'),
    ]

    operations = [
        migrations.CreateModel(
            name='FicheBenevole',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('adresse', core.crypto_fields.EncryptedTextField(blank=True)),
                ('code_postal', core.crypto_fields.EncryptedTextField(blank=True)),
                ('ville', models.CharField(blank=True, max_length=255)),
                ('location', django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326)),
                ('ban_id', models.CharField(blank=True, help_text="Identifiant BAN de l'adresse, pour rafraîchissement et déduplication ultérieurs (même usage que Habitation.ban_id).", max_length=50)),
                ('commune_code', models.CharField(blank=True, db_index=True, max_length=10, null=True)),
                ('epci_code', models.CharField(blank=True, db_index=True, max_length=10, null=True)),
                ('departement_code', models.CharField(blank=True, db_index=True, max_length=3, null=True)),
                ('region_code', models.CharField(blank=True, db_index=True, max_length=3, null=True)),
                ('date_naissance', models.DateField(blank=True, help_text="Déclarée à l'adhésion. Sert à vérifier la majorité et à instruire une candidature ; jamais affichée dans les listes.", null=True)),
                ('metier', core.crypto_fields.EncryptedTextField(blank=True, help_text="Métier ou formation déclarés. C'est ce qui permet de chercher un électricien ou une infirmière parmi les membres.")),
                ('situation', models.CharField(blank=True, choices=[('SALARIE', 'Salarié(e)'), ('RETRAITE', 'Retraité(e)'), ('INDEPENDANT', "Chef(fe) d'entreprise, artisan, profession libérale"), ('FONCTIONNAIRE', 'Fonctionnaire'), ('ETUDIANT', 'Étudiant(e)'), ('RECHERCHE_EMPLOI', "En recherche d'emploi"), ('AUTRE', 'Autre')], max_length=20)),
                ('disponibilite', models.CharField(blank=True, choices=[('OCCASIONNELLE', 'Occasionnelle (moins de 5 jours par an)'), ('REGULIERE', 'Régulière (environ 10 jours par an)'), ('FREQUENTE', 'Fréquente (plus de 10 jours par an)')], max_length=20)),
                ('message', core.crypto_fields.EncryptedTextField(blank=True)),
                ('diplome_premier_secours', models.BooleanField(default=False, help_text="Déclaré par la personne à l'adhésion. Une qualification VÉRIFIÉE se saisit dans QualificationMembre, avec ses dates et son justificatif.")),
                ('date_adhesion', models.DateField(blank=True, help_text="Date d'adhésion déclarée par le fichier d'origine, quand elle est connue.", null=True)),
                ('completee_le', models.DateTimeField(blank=True, null=True)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_modification', models.DateTimeField(auto_now=True)),
                ('utilisateur', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='fiche_benevole', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
