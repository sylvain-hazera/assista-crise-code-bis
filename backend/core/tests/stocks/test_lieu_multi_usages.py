"""Un lieu de la commune, plusieurs usages (18/11/2026).

Demande de Sylvain : « je fais mon stock au dépôt "gymnase" et quand je fais mon "centre
d'accueil gymnase" je récupère son stock (tatamis, lits, tables, chaises…). Ce n'est pas
seulement dépôt multiple au même lieu, c'est aussi même lieu, plusieurs usages : dépôt, mais
aussi centre de regroupement avec le stock du dépôt. »"""
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point

from core import stocks, stocks_points
from core.models import (
    ArticleStock, Crisis, DepotStock, MaterielPoint, MouvementStock, PointOperationnel, PointType, TypeMouvementStock,
)
from core.tests.stocks.test_stocks import asso  # noqa: F401


@pytest.fixture
def gymnase(asso):
    institution = asso["institution"]
    lieu = DepotStock.objects.create(institution=institution, nom="Gymnase municipal")
    tatamis = ArticleStock.objects.create(institution=institution, reference="TATAMI", designation="Tatami")
    lits = ArticleStock.objects.create(institution=institution, reference="LIT", designation="Lit de camp")
    stocks.enregistrer(article=tatamis, depot=lieu, type_mouvement=TypeMouvementStock.ENTREE, quantite=40)
    stocks.enregistrer(article=lits, depot=lieu, type_mouvement=TypeMouvementStock.ENTREE, quantite=25)
    return {"lieu": lieu, "tatamis": tatamis, "lits": lits, **asso}


def _point(nom, lieu=None):
    crise = Crisis.objects.filter(name="Crue").first() or Crisis.objects.create(name="Crue", location=Point(4.5, 45.4, srid=4326))
    ptype = PointType.objects.first() or PointType.objects.create(code="ACCUEIL", libelle="Centre d'accueil")
    return PointOperationnel.objects.create(nom=nom, type=ptype, crise=crise, lieu_de_stock=lieu)


def _stock(point):
    return {l.item.nom: l.quantite for l in MaterielPoint.objects.filter(point=point).select_related("item")}


@pytest.mark.django_db
class TestLeCentreRecupereLeStockDuLieu:

    def test_le_centre_ouvert_au_gymnase_voit_le_stock_du_gymnase_sans_transfert(self, gymnase):
        avant = MouvementStock.objects.count()
        centre = _point("Centre d'accueil du gymnase", gymnase["lieu"])
        assert stocks_points.adopter_le_lieu(centre, centre.environment) == 2
        assert _stock(centre) == {"Tatami": 40, "Lit de camp": 25}
        assert MouvementStock.objects.count() == avant            # rien n'a bougé : même stock

    def test_un_meme_lieu_sert_a_deux_usages_sur_le_meme_stock(self, gymnase):
        accueil = _point("Centre d'accueil", gymnase["lieu"])
        regroupement = _point("Regroupement des moyens", gymnase["lieu"])
        for point in (accueil, regroupement):
            stocks_points.adopter_le_lieu(point, point.environment)

        item = stocks_points.item_de(gymnase["lits"])
        stocks_points.distribuer(point=accueil, item=item, quantite=5, environment=accueil.environment, motif="Familles évacuées")
        stocks_points.synchroniser_les_points(gymnase["lieu"], item, accueil.environment)

        assert _stock(accueil)["Lit de camp"] == 20
        assert _stock(regroupement)["Lit de camp"] == 20          # l'autre usage voit la même chose
        # ... et le dépôt « gymnase » aussi : c'est son stock qui a baissé.
        reste = MouvementStock.objects.filter(depot=gymnase["lieu"], article=gymnase["lits"])
        assert sum(m.quantite for m in reste) == Decimal("20")

    def test_ce_qui_entre_au_depot_apparait_au_centre(self, gymnase):
        centre = _point("Centre d'accueil", gymnase["lieu"])
        stocks_points.adopter_le_lieu(centre, centre.environment)
        stocks.enregistrer(article=gymnase["tatamis"], depot=gymnase["lieu"], type_mouvement=TypeMouvementStock.ENTREE, quantite=10)
        stocks_points.synchroniser_les_points(gymnase["lieu"], stocks_points.item_de(gymnase["tatamis"]), centre.environment)
        assert _stock(centre)["Tatami"] == 50

    def test_a_la_fermeture_rien_n_est_a_rapatrier_le_stock_reste_au_lieu(self, gymnase):
        centre = _point("Centre d'accueil", gymnase["lieu"])
        stocks_points.adopter_le_lieu(centre, centre.environment)
        local = DepotStock.objects.create(institution=gymnase["institution"], nom="Local")
        assert stocks_points.rapatrier(point=centre, institution=gymnase["institution"], destination=local,
                                       environment=centre.environment) == 0
        assert sum(m.quantite for m in MouvementStock.objects.filter(depot=gymnase["lieu"], article=gymnase["tatamis"])) == 40

    def test_un_point_sans_lieu_garde_son_stock_de_crise(self, gymnase):
        centre = _point("Salle des fêtes")
        assert stocks_points.adopter_le_lieu(centre, centre.environment) == 0 and _stock(centre) == {}


@pytest.mark.django_db
class TestChoisirLeLieuParLApi:

    def test_la_mairie_installe_son_point_dans_son_gymnase(self, gymnase):
        centre = _point("Centre d'accueil")
        reponse = gymnase["client"].patch(f"/api/points-operationnels/{centre.id}/", {"lieu_de_stock": str(gymnase["lieu"].id)}, format="json")
        assert reponse.status_code == 200, reponse.data
        assert reponse.data["lieu_de_stock_nom"] == "Gymnase municipal"
        assert _stock(centre) == {"Tatami": 40, "Lit de camp": 25}

    def test_on_ne_s_installe_pas_dans_le_stock_de_crise_d_un_autre_point(self, gymnase):
        autre = _point("Autre point")
        depot_de_crise = stocks_points.depot_du_point(autre, gymnase["institution"], autre.environment)
        centre = _point("Centre d'accueil")
        reponse = gymnase["client"].patch(f"/api/points-operationnels/{centre.id}/", {"lieu_de_stock": str(depot_de_crise.id)}, format="json")
        assert reponse.status_code == 400 and "lieu_de_stock" in reponse.data
