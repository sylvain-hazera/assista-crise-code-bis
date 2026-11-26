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
            DepotStock, ArticleStock, MouvementStock,
            ConstatTerrain, Habitation, HabitationCommentaire, HabitationHistorique, TypeBien,
        )

        # L'ordre de cette liste n'a aucune importance : les événements sont rejoués chez le
        # central dans l'ordre de CRÉATION des objets (`order_by("cree_le")`), pas dans celui des
        # signaux.
        for modele in (
            Dossier, DossierCommentaire, DossierHistorique, DeclarationSecurite, Mission,
            MessageMeshLog, CanalMeshCore, CanalMeshtastic, MessageCanalMeshCore,
            MessageMeshtasticLog, MessageCanalMeshtastic, AlerteMeshSOS,
            DepotStock, ArticleStock, MouvementStock,
            TypeBien, Habitation, HabitationHistorique, HabitationCommentaire, ConstatTerrain,
        ):
            post_save.connect(sync_outbox.enregistrer_evenement, sender=modele, dispatch_uid=f"sync_outbox_{modele.__name__}")
        for modele in (Dossier, Mission, Habitation):
            pre_save.connect(sync_outbox.capturer_version_avant_ecriture, sender=modele, dispatch_uid=f"sync_outbox_pre_{modele.__name__}")

        # Salons Matrix d'office (16/11/2026) : une mission reçoit son salon dès qu'une équipe
        # lui est affectée, une institution les siens à son premier rattachement (les équipes
        # ont déjà les leurs à la création, voir matrix.provisionner_salons_equipe). Voir
        # core/salons_matrix.py. Pas sur un satellite : le pont Matrix tourne au central, et la
        # mission y arrive par la synchronisation, où le même signal crée son salon.
        from django.conf import settings

        if not getattr(settings, "INSTANCE_SATELLITE_LOCALE", False):
            from django.db.models.signals import m2m_changed

            # Référentiel d'adresses (20/11/2026, core/referentiel_adresses.py) : une institution
            # communale ou intercommunale, une crise ouverte ou une commune ajoutée à sa zone
            # chargent leurs adresses. Pas sur un satellite : il les reçoit du central.
            from . import referentiel_adresses
            from .models import Crisis

            post_save.connect(referentiel_adresses.institution_enregistree, sender=Institution,
                              dispatch_uid="referentiel_adresses_institution")
            post_save.connect(referentiel_adresses.crise_enregistree, sender=Crisis,
                              dispatch_uid="referentiel_adresses_crise")

            # Indicatif et canal radio par défaut de chaque équipe (25/11/2026,
            # core/radio_equipe.py). Au central seulement : les équipes y naissent.
            from . import radio_equipe
            from .models import Team

            post_save.connect(radio_equipe.equipe_enregistree, sender=Team, dispatch_uid="radio_equipe_defaut")

            # Notifications de l'administration poussées vers les appareils abonnés (poste de
            # pilotage installé sur iPad, DOSSIER-PWA-INTERVENANTS.md).
            from . import notifications_application
            from .models import Notification

            post_save.connect(notifications_application.notification_site_creee, sender=Notification,
                              dispatch_uid="poussee_notification_site")

            # Crise sur la commune d'une manifestation (26/11/2026, core/partage_manifestation.py).
            from . import partage_manifestation
            post_save.connect(partage_manifestation.crise_enregistree, sender=Crisis,
                              dispatch_uid="partage_manifestation_crise")

            from . import salons_matrix
            from .models import ContactInstitution

            m2m_changed.connect(salons_matrix.equipes_de_mission_modifiees, sender=Mission.equipes.through,
                                dispatch_uid="salons_matrix_mission_equipes")
            post_save.connect(salons_matrix.rattachement_enregistre, sender=ContactInstitution,
                              dispatch_uid="salons_matrix_rattachement")
