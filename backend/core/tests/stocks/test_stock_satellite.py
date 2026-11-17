"""Le stock tenu hors connexion sur un satellite : ce qu'il inscrit remonte au central tel quel,
et le stock de son institution redescend — sans conflit, puisque le journal ne fait qu'ajouter."""
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point

from core import stocks, stocks_points, sync_stock
from core.models import (
    ArticleStock, Crisis, DepotStock, EvenementSynchronisation, MaterielCatalogue, MaterielPoint, MouvementStock, PointOperationnel,
    PointType, Satellite, Team,
)
from core.tests.stocks.test_stocks import asso  # noqa: F401
from core.tests.stocks.test_stocks_echanges import _institution
from core.views import _appliquer_evenement_synchronisation


def _evenements(modele=None):
    file = EvenementSynchronisation.objects.order_by("cree_le")
    return list(file.filter(modele=modele) if modele else file)


def _comme_un_lot(evenements):
    return [{"id": str(e.id), "modele": e.modele, "objet_id": str(e.objet_id), "payload": e.payload, "auteur_local_email": "magasinier@test.fr"}
            for e in evenements]


@pytest.fixture
def satellite(asso):
    return Satellite.objects.create(institution=asso["institution"], nom="Satellite des essais", profil="FULL")


@pytest.mark.django_db
class TestMontant:
    def test_le_central_ninscrit_rien_dans_la_file_mais_le_satellite_oui(self, asso, settings):
        stocks.enregistrer(article=asso["couvertures"], depot=asso["local"], type_mouvement="ENTREE", quantite=10)
        assert _evenements() == []                                    # nous sommes le central

        settings.INSTANCE_SATELLITE_LOCALE = True
        stocks.enregistrer(article=asso["couvertures"], depot=asso["local"], type_mouvement="SORTIE", quantite=4, tiers="Mme Durand")
        stocks.transferer(article=asso["couvertures"], source=asso["local"], destination=asso["camion"], quantite=2)

        file = _evenements("MouvementStock")
        assert [e.payload["type"] for e in file] == ["SORTIE", "TRANSFERT", "TRANSFERT"]     # juste du premier coup
        assert Decimal(file[0].payload["quantite"]) == Decimal("-4") and file[0].payload["tiers"] == "Mme Durand"
        assert file[1].payload["transfert"] == file[2].payload["transfert"] is not None

    def test_ce_qui_est_cree_sur_place_remonte_et_met_a_jour_le_point(self, asso, satellite, settings):
        crise = Crisis.objects.create(name="Crue des essais", type="INONDATION", location=Point(4.51, 45.47, srid=4326))
        equipe = Team.objects.create(name="Accueil", description="", color="#3b82f6", institution=asso["institution"])
        ptype = PointType.objects.first() or PointType.objects.create(nom="Centre d'accueil")
        point = PointOperationnel.objects.create(nom="Gymnase", type=ptype, crise=crise, equipe=equipe, location=Point(4.51, 45.47, srid=4326))
        lits = MaterielCatalogue.objects.create(nom="Lit de camp")
        settings.INSTANCE_SATELLITE_LOCALE = True
        # Le satellite, coupé du réseau, reçoit un don au point puis en distribue.
        stocks_points.recevoir(point=point, item=lits, quantite=12, institution=asso["institution"], environment="PROD", tiers="Voisin")
        stocks_points.distribuer(point=point, item=lits, quantite=5, environment="PROD")
        lot = _comme_un_lot(_evenements())
        # Le dépôt du point et l'article du don sont créés sur place : ils précèdent leurs mouvements.
        assert sorted(e["modele"] for e in lot[:2]) == ["ArticleStock", "DepotStock"] and [e["modele"] for e in lot[2:]] == ["MouvementStock"] * 2
        article = next(e for e in lot if e["modele"] == "ArticleStock")
        assert article["payload"]["catalogue_cle"] == "Lit de camp" and "catalogue_id" not in article["payload"]

        # Le « central » : mêmes tables, vidées de ce que le satellite a créé. Le catalogue y porte un AUTRE identifiant.
        settings.INSTANCE_SATELLITE_LOCALE = False
        MouvementStock.objects.all().delete()
        ArticleStock.objects.filter(catalogue=lits).delete()
        DepotStock.objects.filter(point=point).delete()
        MaterielPoint.objects.all().delete()
        lits.delete()
        ailleurs = MaterielCatalogue.objects.create(nom="Lit de camp")

        resultats = [_appliquer_evenement_synchronisation(satellite, evenement, None) for evenement in lot]

        assert [r["resultat"] for r in resultats] == ["applique"] * 4, resultats
        assert stocks_points.quantites(point)[ailleurs.id] == Decimal("7")
        assert MaterielPoint.objects.get(point=point, item=ailleurs).quantite == 7      # la ligne du point suit
        assert ArticleStock.objects.get(catalogue=ailleurs).institution == asso["institution"]
        # Rejouer le même lot ne double rien.
        assert {r["resultat"] for r in (_appliquer_evenement_synchronisation(satellite, e, None) for e in lot)} == {"deja_applique"}
        assert stocks_points.quantites(point)[ailleurs.id] == Decimal("7")

    def test_un_satellite_ne_remonte_pas_le_stock_dune_autre_institution(self, asso, satellite, create_user, settings):
        autre, _compte, _client = _institution(create_user, "Mairie voisine", "mairie-satellite")
        depot = DepotStock.objects.create(institution=autre, nom="Dépôt de la mairie")
        article = ArticleStock.objects.create(institution=autre, reference="X", designation="Chose")
        settings.INSTANCE_SATELLITE_LOCALE = True
        stocks.enregistrer(article=article, depot=depot, type_mouvement="ENTREE", quantite=3)
        lot = _comme_un_lot(_evenements("MouvementStock"))
        settings.INSTANCE_SATELLITE_LOCALE = False
        MouvementStock.objects.all().delete()

        resultat = _appliquer_evenement_synchronisation(satellite, lot[0], None)

        assert resultat["resultat"] == "erreur" and "institution du satellite" in resultat["detail"] and MouvementStock.objects.count() == 0


@pytest.mark.django_db
class TestDescendant:
    def test_le_satellite_recoit_le_stock_de_son_institution_sans_le_refaire_remonter(self, asso, create_user, settings):
        stocks.enregistrer(article=asso["couvertures"], depot=asso["local"], type_mouvement="ENTREE", quantite=25, prix_unitaire=2)
        autre, _compte, _client = _institution(create_user, "Mairie voisine", "mairie-descente")
        DepotStock.objects.create(institution=autre, nom="Pas pour le satellite")

        donnees = sync_stock.pour_satellite(asso["institution"], "PROD")

        assert [d["nom"] for d in donnees["depots"]] == ["Camion", "Local"] or sorted(d["nom"] for d in donnees["depots"]) == ["Camion", "Local"]
        assert len(donnees["articles"]) == 1 and len(donnees["mouvements"]) == 1
        # Le satellite, vide : il inscrit tout, puis une seconde descente ne change rien.
        MouvementStock.objects.all().delete()
        ArticleStock.objects.all().delete()
        DepotStock.objects.filter(institution=asso["institution"]).delete()
        settings.INSTANCE_SATELLITE_LOCALE = True

        assert sync_stock.appliquer(donnees) == {"applique": 4, "ignore": 0, "erreur": 0}
        assert sync_stock.appliquer(donnees) == {"applique": 0, "ignore": 4, "erreur": 0}
        article = ArticleStock.objects.get(reference="COUV")
        assert stocks.quantite_en_stock(article) == Decimal("25") and article.seuil_alerte == Decimal("20")
        assert _evenements() == []                                    # ce qui descend ne remonte pas
        # Une sortie faite ensuite sur le satellite, elle, remontera.
        stocks.enregistrer(article=article, depot=DepotStock.objects.get(nom="Local"), type_mouvement="SORTIE", quantite=5)
        assert len(_evenements("MouvementStock")) == 1 and stocks.quantite_en_stock(article) == Decimal("20")
