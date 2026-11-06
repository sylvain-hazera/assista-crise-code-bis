from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from . import metrics
        metrics.register()
        
        # Connectés inconditionnellement : chaque fonction se désactive elle-même si
        # settings.INSTANCE_SATELLITE_LOCALE est faux (voir core/sync_outbox.py) — pas de coût
        # au-delà d'un dispatch de signal côté central.
        from django.db.models.signals import post_save, pre_save

        from . import notifications_admin, sync_outbox
        from .models import Institution

        post_save.connect(notifications_admin.institution_creee, sender=Institution, dispatch_uid="notif_admin_institution_creee")
        from .models import (
            AlerteMeshSOS, CanalMeshCore, CanalMeshtastic, DeclarationSecurite, Dossier,
            DossierCommentaire, DossierHistorique, MessageCanalMeshCore, MessageCanalMeshtastic,
            MessageMeshLog, MessageMeshtasticLog, Mission,
        )

        # L'ordre de cette liste n'a aucune importance : les événements sont rejoués chez le
        # central dans l'ordre de CRÉATION des objets (`order_by("cree_le")`), pas dans celui des
        # signaux.
        for modele in (
            Dossier, DossierCommentaire, DossierHistorique, DeclarationSecurite, Mission,
            MessageMeshLog, CanalMeshCore, CanalMeshtastic, MessageCanalMeshCore,
            MessageMeshtasticLog, MessageCanalMeshtastic, AlerteMeshSOS,
        ):
            post_save.connect(sync_outbox.enregistrer_evenement, sender=modele, dispatch_uid=f"sync_outbox_{modele.__name__}")
        for modele in (Dossier, Mission):
            pre_save.connect(sync_outbox.capturer_version_avant_ecriture, sender=modele, dispatch_uid=f"sync_outbox_pre_{modele.__name__}")
