"""Cloisonnement des offres d'aide : `Offer.visibilite` et `Offer.institution`.

Rendu nécessaire par la décision du 11/11/2026 de faire des bénévoles d'association de vraies
ressources : le moteur de disponibilité du projet (`DisponibiliteOffre`, quatre créneaux par
jour) est clé sur `Offer`, donc un bénévole doit avoir une offre pour y entrer.

Or `Offer` était **entièrement public** : `OfferViewSet` est en `AllowAny`, sa liste alimente la
carte publique et la recherche, et le modèle ne portait ni institution ni visibilité. Importer
un fichier d'adhérents aurait publié l'annuaire de l'association — l'inverse exact de la
consigne « seule la réserve résilience a le droit de les voir comme ressource ».

**Le défaut est permissif, et c'est voulu** : toutes les lignes existantes restent `PUBLIQUE`.
Cette migration ne peut donc pas réduire par accident ce qui était déjà visible ; elle ouvre la
possibilité de fermer, elle ne ferme rien.

`visibilite` est indexé : il entre dans le filtre de **toute** lecture d'offres, sur la table la
plus volumineuse du projet (cible 300 à 400 k lignes).
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0254_frequence_engagement'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='visibilite',
            field=models.CharField(
                choices=[('PUBLIQUE', 'Publique'),
                         ('INTERNE', 'Réservée à son institution')],
                db_index=True, default='PUBLIQUE', max_length=10,
                help_text='PUBLIQUE = carte et recherche publiques, comme toute offre '
                          'citoyenne. INTERNE = réservée aux membres de `institution`.',
            ),
        ),
        migrations.AddField(
            model_name='offer',
            name='institution',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='offres_internes', to='core.institution',
                help_text="Renseignée pour une offre INTERNE : l'institution dont les membres "
                          "y ont accès. Nulle pour une offre citoyenne publique.",
            ),
        ),
    ]
