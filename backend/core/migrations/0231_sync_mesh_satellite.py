"""Élargit le périmètre de la synchronisation satellite -> central au domaine mesh.

Jusqu'ici, seul `MessageMeshLog` (les DM MeshCore) remontait : un satellite observait du trafic
radio que le central ne voyait jamais. S'ajoutent les deux modèles de canal, les trois autres
modèles de message et les alertes SOS (voir `ModeleSynchronisable` et `core/sync_outbox.py`).

Les canaux en font partie parce qu'un satellite en crée localement -- le canal « Public » est
auto-provisionné dès qu'un companion voit son trafic -- et que sans eux leurs messages
arriveraient au central avec une clé étrangère introuvable. La file étant rejouée dans l'ordre de
création (`order_by("cree_le")`), un canal précède toujours ses messages.

Changement de `choices` uniquement : aucune colonne modifiée, aucune donnée touchée. Les valeurs
existantes restent valides, la liste n'est qu'élargie.

Le sens inverse (ordres d'envoi central -> radio d'un satellite) ne passe PAS par ce mécanisme :
la file montante ne suit que les créations, donc un accusé d'envoi n'y remonterait jamais. Il a
son propre canal, avec accusé explicite -- `SatelliteViewSet.mesh_a_emettre` / `mesh_emis`.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0230_chiffrer_secrets_mesh'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conflitsynchronisation',
            name='modele',
            field=models.CharField(choices=[('Dossier', 'Dossier'), ('DossierCommentaire', 'Commentaire de dossier'), ('DossierHistorique', 'Historique de dossier'), ('DeclarationSecurite', 'Déclaration de sécurité'), ('Mission', 'Mission'), ('MessageMeshLog', 'Message direct MeshCore'), ('CanalMeshCore', 'Canal MeshCore'), ('CanalMeshtastic', 'Canal Meshtastic'), ('MessageCanalMeshCore', 'Message de canal MeshCore'), ('MessageMeshtasticLog', 'Message direct Meshtastic'), ('MessageCanalMeshtastic', 'Message de canal Meshtastic'), ('AlerteMeshSOS', 'Alerte SOS mesh')], max_length=30),
        ),
        migrations.AlterField(
            model_name='evenementsynchronisation',
            name='modele',
            field=models.CharField(choices=[('Dossier', 'Dossier'), ('DossierCommentaire', 'Commentaire de dossier'), ('DossierHistorique', 'Historique de dossier'), ('DeclarationSecurite', 'Déclaration de sécurité'), ('Mission', 'Mission'), ('MessageMeshLog', 'Message direct MeshCore'), ('CanalMeshCore', 'Canal MeshCore'), ('CanalMeshtastic', 'Canal Meshtastic'), ('MessageCanalMeshCore', 'Message de canal MeshCore'), ('MessageMeshtasticLog', 'Message direct Meshtastic'), ('MessageCanalMeshtastic', 'Message de canal Meshtastic'), ('AlerteMeshSOS', 'Alerte SOS mesh')], max_length=30),
        ),
    ]
