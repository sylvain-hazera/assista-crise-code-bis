"""Métriques d'état du réseau radio (core/metrics.py:MeshStateCollector).

Le test qui compte est `test_aucune_etiquette_ne_nomme_un_noeud` : une étiquette Prometheus finit
dans un fichier de métriques non chiffré, lisible par quiconque accède à la supervision, alors
que `ContactMeshCore.nom` est un champ chiffré en base. Une métrique compte, elle ne nomme pas.
"""
import datetime

import pytest
from django.utils import timezone

from core.metrics import MeshStateCollector
from core.models import CompagnonMeshCore, ContactMeshCore, TypeContactMeshCore


def familles(collecteur=None):
    """Métriques indexées par nom, pour lire sans dépendre de l'ordre de collecte."""
    return {f.name: f for f in (collecteur or MeshStateCollector()).collect()}


@pytest.mark.django_db
class TestCompagnons:

    def test_compte_les_companions_actifs_par_zone(self):
        CompagnonMeshCore.objects.create(nom="A", actif=True)
        CompagnonMeshCore.objects.create(nom="B", actif=True)
        CompagnonMeshCore.objects.create(nom="C", actif=False)
        famille = familles()["assista_mesh_compagnons_actifs"]
        valeurs = {e.labels["environment"]: e.value for e in famille.samples}
        assert valeurs["PROD"] == 2

    def test_le_silence_maximal_est_celui_du_plus_ancien(self):
        """C'est l'equivalent de leur alerte « passerelle hors ligne » : on veut le pire cas, pas
        une moyenne qui le masquerait."""
        CompagnonMeshCore.objects.create(
            nom="recent", actif=True, derniere_connexion=timezone.now(),
        )
        CompagnonMeshCore.objects.create(
            nom="muet", actif=True,
            derniere_connexion=timezone.now() - datetime.timedelta(hours=3),
        )
        famille = familles()["assista_mesh_compagnon_silence_max_secondes"]
        valeur = [e.value for e in famille.samples if e.labels["environment"] == "PROD"][0]
        assert valeur == pytest.approx(3 * 3600, abs=120)

    def test_zero_plutot_que_rien_quand_aucune_connexion_connue(self):
        """Sans valeur, l'alerte ne se declencherait jamais -- un companion jamais connecte
        passerait inapercu. On expose 0, pas l'absence de serie."""
        CompagnonMeshCore.objects.create(nom="jamais vu", actif=True, derniere_connexion=None)
        famille = familles()["assista_mesh_compagnon_silence_max_secondes"]
        assert [e.value for e in famille.samples] == [0]


@pytest.mark.django_db
class TestInfrastructure:

    def _contact(self, cle, type_contact, batterie=None):
        compagnon = CompagnonMeshCore.objects.create(nom=f"c-{cle}")
        return ContactMeshCore.objects.create(
            compagnon=compagnon, pubkey_hex=cle * 32, type_contact=type_contact,
            nom="Nom confidentiel du relais", niveau_batterie_pct=batterie,
            dernier_advert=timezone.now(),
        )

    def test_compte_les_repeteurs_et_salons_entendus(self):
        self._contact("aa", TypeContactMeshCore.REPEATER)
        self._contact("bb", TypeContactMeshCore.ROOM)
        # Ni un companion ni un capteur ne sont de l'infrastructure relayante.
        self._contact("cc", TypeContactMeshCore.COMPANION)
        self._contact("dd", TypeContactMeshCore.SENSOR)

        famille = familles()["assista_mesh_infrastructure_entendue"]
        valeurs = {e.labels["type"]: e.value for e in famille.samples}
        assert valeurs == {"REPEATER": 1, "ROOM": 1}

    def test_compte_les_batteries_sous_le_seuil(self):
        self._contact("aa", TypeContactMeshCore.REPEATER, batterie=12)
        self._contact("bb", TypeContactMeshCore.REPEATER, batterie=80)
        self._contact("cc", TypeContactMeshCore.REPEATER, batterie=None)
        famille = familles()["assista_mesh_infrastructure_batterie_faible"]
        assert [e.value for e in famille.samples] == [1]

    def test_aucune_etiquette_ne_nomme_un_noeud(self):
        """Le test central. `nom` est chiffré en base ; une étiquette Prometheus ne l'est pas, et
        une clé publique identifie un équipement de façon durable."""
        self._contact("aa", TypeContactMeshCore.REPEATER, batterie=5)
        CompagnonMeshCore.objects.create(nom="Passerelle du PC", actif=True)

        etiquettes = set()
        for famille in familles().values():
            for echantillon in famille.samples:
                etiquettes.update(str(v) for v in echantillon.labels.values())

        assert "Nom confidentiel du relais" not in etiquettes
        assert "Passerelle du PC" not in etiquettes
        assert not any("aa" * 32 == e for e in etiquettes)
        # Seules des valeurs bornées : zone, type de contact, statut de tâche d'administration.
        # Chacune vient d'une énumération -- jamais un numéro de nœud, qui ferait exploser la
        # cardinalité ET désignerait un appareil précis.
        from core.models import StatutTacheAdminMeshtastic
        assert etiquettes <= (
            {"PROD", "DEMO", "REPEATER", "ROOM"} | set(StatutTacheAdminMeshtastic.values)
        )


@pytest.mark.django_db
class TestAdministrationDistante:
    """File d'administration et instrumentation réelle du réseau."""

    def _passerelle(self):
        from core.models import CompagnonMeshtastic, MeshtasticConnexionType
        return CompagnonMeshtastic.objects.create(
            nom="Passerelle", node_num=0x1000, connexion_type=MeshtasticConnexionType.SERIE,
        )

    def test_tous_les_statuts_sont_emis_meme_a_zero(self):
        """Sinon une alerte « des tâches échouent » ne pourrait pas se déclencher au PREMIER
        échec : il n'y aurait aucune série ECHEC à évaluer avant qu'il arrive."""
        from core.models import StatutTacheAdminMeshtastic, TacheAdminMeshtastic
        TacheAdminMeshtastic.objects.create(
            compagnon=self._passerelle(), type_tache="LIRE_METADATA", environment="PROD",
        )
        famille = familles()["assista_mesh_taches_admin"]
        valeurs = {e.labels["statut"]: e.value for e in famille.samples}
        assert set(valeurs) == set(StatutTacheAdminMeshtastic.values)
        assert valeurs["EN_ATTENTE"] == 1
        assert valeurs["ECHEC"] == 0

    def test_la_serie_existe_meme_sans_aucune_tache(self):
        famille = familles()["assista_mesh_taches_admin"]
        assert {e.labels["statut"] for e in famille.samples}
        assert all(e.value == 0 for e in famille.samples)

    def test_compte_les_noeuds_dont_la_puissance_est_vraiment_connue(self):
        """Métrique qui dit si le réseau est instrumenté : tant qu'elle est basse, l'analyse
        d'asymétrie ne peut pas corriger l'écart de puissance. `0 dBm` n'est PAS une puissance
        connue -- le firmware applique alors le maximum de la région."""
        from core.models import ConfigurationNoeudMeshtastic
        for num, puissance in ((1, 22), (2, 14), (3, 0), (4, None)):
            ConfigurationNoeudMeshtastic.objects.create(
                node_num=num, environment="PROD", puissance_emission_dbm=puissance,
                date_releve=timezone.now(),
            )
        famille = familles()["assista_mesh_noeuds_puissance_connue"]
        assert {e.labels["environment"]: e.value for e in famille.samples}["PROD"] == 2


@pytest.mark.django_db
def test_une_panne_de_base_ne_fait_pas_tomber_les_metriques(monkeypatch):
    """Même garde que BusinessStateCollector : si /metrics levait, Prometheus verrait le backend
    comme indisponible — on perdrait TOUTE la supervision pour une requête ratée."""
    def explose(*args, **kwargs):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(MeshStateCollector, "_compagnons", staticmethod(explose))
    assert list(MeshStateCollector().collect()) == []


@pytest.mark.django_db
class TestExpositionEnMultiProcessus:
    """Le bug du 06/11/2026, et le test qui manquait.

    En production, gunicorn tourne avec plusieurs workers et `PROMETHEUS_MULTIPROC_DIR` : la vue
    /metrics construit alors un registre NEUF. Un collecteur oublié dans cette branche disparaît
    donc silencieusement des métriques en production tout en restant visible en dev — c'est
    arrivé à MeshStateCollector, et les alertes du groupe « mesh » n'auraient jamais pu se
    déclencher. D'où `COLLECTEURS`, lu par les deux chemins."""

    def test_tous_les_collecteurs_sont_exposes_dans_les_deux_chemins(self):
        from core import metrics

        # Le registre global : ce que register() installe.
        noms_globaux = {c.__name__ for c in metrics.COLLECTEURS}
        assert "MeshStateCollector" in noms_globaux
        assert "BusinessStateCollector" in noms_globaux

    def test_la_vue_multiprocessus_expose_les_metriques_mesh(self, tmp_path, monkeypatch):
        """Vérification par le contenu réel de /metrics, pas par introspection : c'est ce que
        Prometheus lit."""
        from django.test import RequestFactory

        from core import metrics

        CompagnonMeshCore.objects.create(nom="Passerelle", actif=True)
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

        reponse = metrics.metrics_view(RequestFactory().get("/metrics"))
        corps = reponse.content.decode()

        assert "assista_mesh_compagnons_actifs" in corps
        assert "assista_mesh_infrastructure_entendue" in corps
        # Le témoin : les métriques métier doivent toujours être là aussi.
        assert "assista_active_crises" in corps
