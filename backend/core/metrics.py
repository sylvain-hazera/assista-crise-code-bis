"""
Métriques métier exposées sur /metrics (Prometheus). Voir DOCUMENTATION.md, « Monitoring ».

- Compteurs incrémentés par les signaux post_save (remis à zéro au redémarrage : rate()/increase()
  le gèrent côté PromQL).
- Jauges calculées depuis la base au moment du scrape (BusinessStateCollector).

Les labels doivent rester bornés (types, statuts) : jamais d'id, d'email ni de position.
"""
import logging
import os

from django.db.models import Count
from django.db.models.signals import post_save
from django.http import HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, Counter, generate_latest, multiprocess
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from .models import Crisis, Offer, Request

logger = logging.getLogger(__name__)

HELP_REQUESTS = Counter("assista_help_requests_total",
                        "Help requests created", ["request_type"])

OFFERS = Counter("assista_offers_total",
                 "Help offers created", ["offer_type"])

EMAILS_FAILED = Counter("assista_emails_failed_total",
                        "Emails that could not be sent", ["kind"])


def _type_label(type_obj):
    return (type_obj.type if type_obj else None) or "unknown"


def count_created_request(sender, instance, created, **kwargs):
    if created:
        HELP_REQUESTS.labels(request_type=_type_label(instance.request_type)).inc()


def count_created_offer(sender, instance, created, **kwargs):
    if created:
        OFFERS.labels(offer_type=_type_label(instance.offer_type)).inc()


class BusinessStateCollector(Collector):
    """Nombre actuel de demandes, d'offres et de crises actives, lu en base."""

    def describe(self):
        # liste vide : évite un collect() (donc une requête SQL) au démarrage de Django
        return []

    def collect(self):
        try:
            yield self._by_status(Request, "assista_requests_by_status", "Help requests by status")
            yield self._by_status(Offer, "assista_offers_by_status", "Help offers by status")
            yield self._active_crises()
        except Exception:
            # une panne de base ne doit pas faire tomber /metrics (le backend paraîtrait down)
            logger.exception("Could not collect business metrics")

    @staticmethod
    def _by_status(model, name, documentation):
        family = GaugeMetricFamily(name, documentation, labels=["status"])
        for row in model.objects.values("status").annotate(n=Count("pk")):
            family.add_metric([row["status"]], row["n"])
        return family

    @staticmethod
    def _active_crises():
        family = GaugeMetricFamily("assista_active_crises",
                                   "Crises without an end date, by type", labels=["type"])
        rows = Crisis.objects.filter(end_date__isnull=True).values("type").annotate(n=Count("pk"))
        for row in rows:
            family.add_metric([row["type"]], row["n"])
        return family


def register():
    """Appelé une fois depuis CoreConfig.ready()."""
    post_save.connect(count_created_request, sender=Request,
                      dispatch_uid="metrics_count_created_request")
    post_save.connect(count_created_offer, sender=Offer,
                      dispatch_uid="metrics_count_created_offer")
    REGISTRY.register(BusinessStateCollector())


def metrics_view(request):
    """/metrics. Avec plusieurs workers gunicorn (PROMETHEUS_MULTIPROC_DIR), agrège les valeurs de
    tous les processus ; remplace la vue de django_prometheus, qui perdrait les jauges métier."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        registry.register(BusinessStateCollector())
    else:
        registry = REGISTRY
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
