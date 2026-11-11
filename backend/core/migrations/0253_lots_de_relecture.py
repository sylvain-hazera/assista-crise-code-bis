"""Lots de relecture : un texte générique validé une fois pour N destinataires.

Un import de deux cents bénévoles produit deux cents messages qui ne diffèrent que par un nom
et un lien. Faire relire deux cents fois le même texte n'est pas une relecture, c'est une corvée
que personne ne fera — et une relecture que personne ne fait est pire qu'une absence de
relecture, parce qu'elle donne l'illusion d'un contrôle.

`corps` est désormais stocké sous sa forme GÉNÉRIQUE (« Bonjour [PRENOM] [NOM] ») et `valeurs`
porte, chiffrées, les valeurs de son destinataire. Elles y sont réinjectées au seul moment de
l'envoi, exactement comme les liens magiques. C'est ce qui permet de valider UN texte pour tout
un lot : chaque message repart avec ses propres valeurs.

`lot` est partagé par les messages d'une même REQUÊTE ayant le même texte générique. Le
regroupement est volontairement limité à une requête : deux imports lancés à dix minutes
d'intervalle sont deux décisions, et les fondre ferait valider d'un geste des messages qu'on
n'a pas vus partir ensemble.

Les brouillons antérieurs ont `lot` nul et `valeurs` vide : ils sont relus seuls, avec leur
texte tel qu'il avait été capturé. Aucune reprise de données nécessaire.
"""

import core.crypto_fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0252_justificatifs_qualifications'),
    ]

    operations = [
        migrations.AddField(
            model_name='brouillonenvoi',
            name='lot',
            field=models.UUIDField(blank=True, db_index=True, help_text="Partagé par les messages d'une même action ayant le même texte générique. Nul = message unique, relu seul.", null=True),
        ),
        migrations.AddField(
            model_name='brouillonenvoi',
            name='valeurs',
            field=core.crypto_fields.EncryptedJSONField(blank=True, default=dict),
        ),
    ]
