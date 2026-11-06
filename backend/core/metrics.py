"""
Métriques métier exposées sur /metrics (Prometheus). Voir DOCUMENTATION.md, « Monitoring ».

- Compteurs incrémentés par les signaux post_save (remis à zéro au redémarrage : rate()/increase()
  le gèrent côté PromQL).
- Jauges calculées depuis la base au moment du scrape (BusinessStateCollector).
- Label `environment` (PROD/DEMO) sur tout ce qui est métier : la DEMO contient des milliers de
  lignes synthétiques qui, mélangées, rendraient les alertes métier permanentes.

Les labels doivent rester bornés (types, statuts) : jamais d'id, d'email ni de position.
"""
import logging
import os

from django.db.models import Count, Min
from django.db.models.signals import post_save
from django.http import HttpResponse
from django.utils import timezone
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, Counter, generate_latest, multiprocess
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from .models import Crisis, Institution, Offer, Request, User
from .notifications_admin import filtre_comptes_en_attente

logger = logging.getLogger(__name__)

HELP_REQUESTS = Counter("assista_help_requests_total",
                        "Help requests created", ["request_type", "environment"])

OFFERS = Counter("assista_offers_total",
                 "Help offers created", ["offer_type", "environment"])

EMAILS_FAILED = Counter("assista_emails_failed_total",
                        "Emails that could not be sent", ["kind"])

INSTITUTIONS = Counter("assista_institutions_created_total",
                       "Institutions created, automatically or by hand", ["environment"])


def _type_label(type_obj):
    return (type_obj.type if type_obj else None) or "unknown"


def count_created_request(sender, instance, created, **kwargs):
    if created:
        HELP_REQUESTS.labels(request_type=_type_label(instance.request_type), environment=instance.environment).inc()


def count_created_offer(sender, instance, created, **kwargs):
    if created:
        OFFERS.labels(offer_type=_type_label(instance.offer_type), environment=instance.environment).inc()


def count_created_institution(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        INSTITUTIONS.labels(environment=instance.environment).inc()


class BusinessStateCollector(Collector):
    """Nombre actuel de demandes, d'offres, de crises actives et de comptes en attente de
    validation, lu en base."""

    def describe(self):
        # liste vide : évite un collect() (donc une requête SQL) au démarrage de Django
        return []

    def collect(self):
        try:
            yield self._by_status(Request, "assista_requests_by_status", "Help requests by status")
            yield self._by_status(Offer, "assista_offers_by_status", "Help offers by status")
            yield self._active_crises()
            yield from self._pending_accounts()
        except Exception:
            # une panne de base ne doit pas faire tomber /metrics (le backend paraîtrait down)
            logger.exception("Could not collect business metrics")

    @staticmethod
    def _by_status(model, name, documentation):
        family = GaugeMetricFamily(name, documentation, labels=["status", "environment"])
        for row in model.objects.values("status", "environment").annotate(n=Count("pk")):
            family.add_metric([row["status"], row["environment"]], row["n"])
        return family

    @staticmethod
    def _active_crises():
        # Crises d'essai exclues (Crisis.essai) : ouvertes pour des tests, jamais une vraie crise.
        family = GaugeMetricFamily("assista_active_crises",
                                   "Crises without an end date, by type (test crises excluded)", labels=["type", "environment"])
        rows = (Crisis.objects.filter(end_date__isnull=True, essai=False)
                .values("type", "environment").annotate(n=Count("pk")))
        for row in rows:
            family.add_metric([row["type"], row["environment"]], row["n"])
        return family

    @staticmethod
    def _pending_accounts():
        """Pas de label environment : un compte utilisateur n'appartient à aucun des deux."""
        stats = User.objects.filter(filtre_comptes_en_attente()).aggregate(n=Count("pk"), oldest=Min("date_joined"))
        count = GaugeMetricFamily("assista_accounts_pending_validation",
                                  "Accounts waiting for an administrator's validation")
        count.add_metric([], stats["n"])
        yield count
        age = GaugeMetricFamily("assista_oldest_pending_account_age_seconds",
                                "Waiting time of the oldest account pending validation (0 if none)")
        age.add_metric([], (timezone.now() - stats["oldest"]).total_seconds() if stats["oldest"] else 0)
        yield age


class MeshStateCollector(Collector):
    """État du réseau radio, lu en base (06/11/2026).

    Transposition des alertes de `carte-live-meshtastic` (relais muet, batterie faible,
    passerelle hors ligne) : elles y sont calculées et affichées par leur propre serveur, ici
    elles passent par Prometheus et Grafana — « un seul Grafana ».

    Les séries portent le minimum : jamais de clé publique ni de nom de nœud en étiquette. Une
    étiquette Prometheus finit dans un fichier de métriques non chiffré, lisible par quiconque
    accède à la supervision, alors que `ContactMeshCore.nom` est un champ chiffré en base. On
    compte donc, sans nommer."""

    def describe(self):
        return []

    def collect(self):
        try:
            yield from self._compagnons()
            yield from self._infrastructure()
            yield from self._administration()
        except Exception:
            logger.exception("Could not collect mesh metrics")

    @staticmethod
    def _compagnons():
        """Passerelles : combien sont actives, et depuis combien de temps la plus ancienne n'a
        pas donné signe de vie. C'est l'équivalent de leur alerte « passerelle hors ligne »."""
        from .models import CompagnonMeshCore

        actifs = CompagnonMeshCore.objects.filter(actif=True)
        total = GaugeMetricFamily("assista_mesh_compagnons_actifs",
                                  "Companions MeshCore marked active", labels=["environment"])
        for row in actifs.values("environment").annotate(n=Count("pk")):
            total.add_metric([row["environment"]], row["n"])
        yield total

        silence = GaugeMetricFamily(
            "assista_mesh_compagnon_silence_max_secondes",
            "Time since the least recently seen active companion reported (0 if none)",
            labels=["environment"],
        )
        for row in actifs.values("environment").annotate(plus_ancien=Min("derniere_connexion")):
            ecoule = ((timezone.now() - row["plus_ancien"]).total_seconds()
                      if row["plus_ancien"] else 0)
            silence.add_metric([row["environment"]], ecoule)
        yield silence

    @staticmethod
    def _administration():
        """Administration à distance des nœuds Meshtastic : où en est la file, et combien de
        nœuds ont une puissance d'émission connue.

        Le second compte n'est pas de la curiosité : tant qu'il est bas, l'analyse d'asymétrie
        ne peut pas corriger l'écart de puissance et sa détection de relais sourds reste
        bruyante (core/analyse_liaisons.py). C'est la métrique qui dit si le réseau est
        réellement instrumenté.

        Étiquetage borné aux valeurs d'énumération (statut, environnement) : aucun numéro de
        nœud, qui ferait exploser la cardinalité ET désignerait un appareil précis."""
        from .models import (
            ConfigurationNoeudMeshtastic, StatutTacheAdminMeshtastic, TacheAdminMeshtastic,
        )

        file = GaugeMetricFamily("assista_mesh_taches_admin",
                                 "Remote administration tasks by status",
                                 labels=["statut", "environment"])
        comptes = {
            (row["statut"], row["environment"]): row["n"]
            for row in TacheAdminMeshtastic.objects.values("statut", "environment").annotate(n=Count("pk"))
        }
        # Tous les statuts sont émis, même à zéro : une alerte « des tâches échouent » ne peut
        # pas se déclencher sur une série qui n'apparaît qu'au premier échec.
        environnements = {cle[1] for cle in comptes} or {"PROD"}
        for environment in sorted(environnements):
            for statut in StatutTacheAdminMeshtastic.values:
                file.add_metric([statut, environment], comptes.get((statut, environment), 0))
        yield file

        connues = GaugeMetricFamily(
            "assista_mesh_noeuds_puissance_connue",
            "Nodes whose transmit power has been read (0 excluded: firmware uses region maximum)",
            labels=["environment"],
        )
        for row in (ConfigurationNoeudMeshtastic.objects
                    .filter(puissance_emission_dbm__isnull=False)
                    .exclude(puissance_emission_dbm=0)
                    .values("environment").annotate(n=Count("pk"))):
            connues.add_metric([row["environment"]], row["n"])
        yield connues

    @staticmethod
    def _infrastructure():
        """Répéteurs et room servers entendus, et combien ont une batterie basse. Jamais
        lesquels : la page /admin/meshcore-companions le dit, une métrique n'a pas à le faire."""
        from .models import ContactMeshCore, TypeContactMeshCore

        infra = ContactMeshCore.objects.filter(
            type_contact__in=[TypeContactMeshCore.REPEATER, TypeContactMeshCore.ROOM],
        )
        vus = GaugeMetricFamily("assista_mesh_infrastructure_entendue",
                                "Repeaters and room servers heard on the air",
                                labels=["type", "environment"])
        for row in infra.values("type_contact", "environment").annotate(n=Count("pk")):
            vus.add_metric([row["type_contact"], row["environment"]], row["n"])
        yield vus

        # Seuil aligné sur le leur (SEUIL_BATTERIE_POURCENT, 20 %) : un répéteur sous 20 %
        # tiendra quelques jours au mieux, et il est souvent sur un point haut difficile d'accès.
        faible = GaugeMetricFamily("assista_mesh_infrastructure_batterie_faible",
                                   "Heard repeaters reporting less than 20% battery",
                                   labels=["environment"])
        for row in (infra.filter(niveau_batterie_pct__lt=20)
                    .values("environment").annotate(n=Count("pk"))):
            faible.add_metric([row["environment"]], row["n"])
        yield faible


# Source unique des collecteurs personnalisés : `register()` les met dans le registre global, et
# `metrics_view` dans le registre neuf du mode multi-processus. Les deux DOIVENT lire la même
# liste — voir le commentaire de metrics_view.
COLLECTEURS = (BusinessStateCollector, MeshStateCollector)


def register():
    """Appelé une fois depuis CoreConfig.ready()."""
    post_save.connect(count_created_request, sender=Request,
                      dispatch_uid="metrics_count_created_request")
    post_save.connect(count_created_offer, sender=Offer,
                      dispatch_uid="metrics_count_created_offer")
    post_save.connect(count_created_institution, sender=Institution,
                      dispatch_uid="metrics_count_created_institution")
    for collecteur in COLLECTEURS:
        REGISTRY.register(collecteur())


def metrics_view(request):
    """/metrics. Avec plusieurs workers gunicorn (PROMETHEUS_MULTIPROC_DIR), agrège les valeurs de
    tous les processus ; remplace la vue de django_prometheus, qui perdrait les jauges métier."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        # COLLECTEURS et pas une liste écrite ici : ce registre est neuf, donc tout collecteur
        # oublié disparaît SILENCIEUSEMENT de /metrics en production (gunicorn multi-workers)
        # tout en restant visible en dev. C'est arrivé le 06/11/2026 avec MeshStateCollector —
        # les alertes du groupe « mesh » n'auraient jamais pu se déclencher.
        for collecteur in COLLECTEURS:
            registry.register(collecteur())
    else:
        registry = REGISTRY
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
