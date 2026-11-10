"""Réclamer un répéteur MeshCore : l'identité, le moyen d'administration, et la preuve.

Rien à reprendre : les rattachements existants sont tous Meshtastic (node_num renseigné,
moyen_admin AUCUN), ce qui est exactement le défaut des nouveaux champs. La contrainte
« une identité et une seule » est donc satisfaite par les lignes déjà en base."""

import core.crypto_fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0240_rattachement_noeud_radio'),
    ]

    operations = [
        migrations.AddField(
            model_name='rattachementnoeudradio',
            name='compagnon_meshcore',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='noeuds_administres', to='core.compagnonmeshcore'),
        ),
        migrations.AddField(
            model_name='rattachementnoeudradio',
            name='date_verification',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rattachementnoeudradio',
            name='erreur_verification',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='rattachementnoeudradio',
            name='mot_de_passe',
            field=core.crypto_fields.EncryptedTextField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='rattachementnoeudradio',
            name='moyen_admin',
            field=models.CharField(choices=[('AUCUN', "Aucun (Meshtastic : clé d'administration posée sur l'appareil)"), ('MOT_DE_PASSE', "Mot de passe d'administration du répéteur"), ('ACL', "Clé publique de notre companion inscrite dans l'ACL du répéteur")], default='AUCUN', max_length=14),
        ),
        migrations.AddField(
            model_name='rattachementnoeudradio',
            name='pubkey_hex',
            field=models.CharField(blank=True, help_text='Clé publique du nœud MeshCore visé (Ed25519, 64 caractères hexadécimaux).', max_length=64),
        ),
        migrations.AddField(
            model_name='rattachementnoeudradio',
            name='statut_preuve',
            field=models.CharField(choices=[('NON_VERIFIE', 'Pas encore vérifiée'), ('EN_ATTENTE', 'Vérification en file'), ('VERIFIEE', 'Contrôle démontré'), ('ECHEC', 'Vérification refusée par le nœud')], default='NON_VERIFIE', max_length=12),
        ),
        migrations.AlterField(
            model_name='rattachementnoeudradio',
            name='node_num',
            field=models.PositiveBigIntegerField(blank=True, help_text="Nœud Meshtastic visé. Unique : deux responsables pour un même appareil ne veut rien dire, et c'est ce qui rend les conflits visibles plutôt que silencieux.", null=True),
        ),
        migrations.AddIndex(
            model_name='rattachementnoeudradio',
            index=models.Index(fields=['pubkey_hex'], name='core_rattac_pubkey__a3d2a1_idx'),
        ),
        migrations.AddConstraint(
            model_name='rattachementnoeudradio',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('node_num__isnull', False), ('pubkey_hex', '')), models.Q(('node_num__isnull', True), models.Q(('pubkey_hex', ''), _negated=True)), _connector='OR'), name='ck_rattachement_noeud_radio_une_identite'),
        ),
        migrations.AddConstraint(
            model_name='rattachementnoeudradio',
            constraint=models.UniqueConstraint(condition=models.Q(('node_num__isnull', False)), fields=('node_num',), name='uq_rattachement_noeud_radio_node_num'),
        ),
        migrations.AddConstraint(
            model_name='rattachementnoeudradio',
            constraint=models.UniqueConstraint(condition=models.Q(('pubkey_hex', ''), _negated=True), fields=('pubkey_hex',), name='uq_rattachement_noeud_radio_pubkey'),
        ),
    ]
