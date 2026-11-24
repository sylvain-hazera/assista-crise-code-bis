"""Handler de logging qui relaie les erreurs (niveau ERROR et au-dessus, voir LOGGING dans
config/settings.py) aux administrateurs -- même esprit que AdminEmailHandler de Django
(mail_admins), pour qu'une erreur serveur ou un échec d'envoi d'email ne reste jamais
invisible. Ajouté après l'incident du 07/10 : un compte "Autorité locale" créé sans que
l'email d'activation ne parte jamais, sans aucune trace exploitable.

Jusqu'au 24/11/2026, dans un salon Matrix d'exploitation ; Matrix arrêté, l'erreur part en
notification (site et application) aux administrateurs, par une tâche Celery : le gestionnaire
de journaux ne touche jamais la base lui-même (il peut être appelé au milieu d'une transaction
cassée). Garde-fous, une rafale d'erreurs ne doit pas faire sonner un téléphone cent fois :
le même message au plus une fois par heure, six alertes par heure au plus."""
import hashlib
import logging
import threading
import time

#: Au plus une alerte par message et par heure, et six par heure en tout.
FENETRE_S = 3600
PLAFOND_PAR_FENETRE = 6
#: Les journaux qui ne déclenchent jamais d'alerte : la base (une panne en produirait une par
#: requête) et la chaîne de notification elle-même (boucle).
IGNORES = ("django.db", "core.notifications_application", "core.logging_handlers", "celery", "kombu")

_MAX_BODY_LEN = 2000
_local = threading.local()


def _autorise(cle_message) -> bool:
    """Vrai si cette alerte peut partir (cache partagé entre processus)."""
    from django.core.cache import cache

    if not cache.add(f"alerte-erreur:{cle_message}", 1, FENETRE_S):
        return False
    cle = f"alerte-erreur-compte:{int(time.time() // FENETRE_S)}"
    cache.add(cle, 0, FENETRE_S)
    return cache.incr(cle) <= PLAFOND_PAR_FENETRE


class AlerteAdministrateursHandler(logging.Handler):
    """Chaque erreur, une notification aux administrateurs (voir le module). Ne lève JAMAIS vers
    l'appelant (contrat de logging.Handler) : toute erreur ici passe par self.handleError."""

    def emit(self, record):
        if record.levelno < logging.ERROR or record.name.startswith(IGNORES) or getattr(_local, "actif", False):
            return
        _local.actif = True
        try:
            texte = self.format(record)
            if len(texte) > _MAX_BODY_LEN:
                texte = texte[:_MAX_BODY_LEN] + "\n… (tronqué)"
            empreinte = hashlib.sha256(
                f"{record.name}|{record.getMessage()[:300]}".encode("utf-8", "replace")).hexdigest()[:32]
            if not _autorise(empreinte):
                return
            from .tasks import alerter_administrateurs_erreur_task

            alerter_administrateurs_erreur_task.apply_async(
                args=[f"Erreur serveur : {record.name}", texte], retry=False,
            )
        except Exception:
            self.handleError(record)
        finally:
            _local.actif = False


#: Ancien nom, encore cité par la configuration des journaux.
MatrixAlertHandler = AlerteAdministrateursHandler
