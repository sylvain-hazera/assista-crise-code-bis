from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Connectés inconditionnellement : chaque fonction se désactive elle-même si
        # settings.INSTANCE_SATELLITE_LOCALE est faux (voir core/sync_outbox.py) — pas de coût
        # au-delà d'un dispatch de signal côté central.
        from django.db.models.signals import post_save, pre_save

        from . import sync_outbox
        from .models import (
            DeclarationSecurite, Dossier, DossierCommentaire, DossierHistorique, MessageMeshLog,
            Mission,
        )

        for modele in (Dossier, DossierCommentaire, DossierHistorique, DeclarationSecurite, Mission, MessageMeshLog):
            post_save.connect(sync_outbox.enregistrer_evenement, sender=modele, dispatch_uid=f"sync_outbox_{modele.__name__}")
        for modele in (Dossier, Mission):
            pre_save.connect(sync_outbox.capturer_version_avant_ecriture, sender=modele, dispatch_uid=f"sync_outbox_pre_{modele.__name__}")
