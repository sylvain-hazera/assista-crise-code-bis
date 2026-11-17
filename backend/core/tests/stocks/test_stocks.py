"""Gestion des stocks : le stock se déduit des mouvements, ne devient jamais négatif, et chaque
institution ne voit que le sien."""
import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core import stocks
from core.models import ArticleStock, DepotStock, Institution, InstitutionType, MouvementStock


@pytest.fixture
def asso(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
    institution = Institution.objects.create(nom="Réserve des essais", type=itype, commune_code="42207")
    magasinier = create_user(username="magasinier@test.fr", email="magasinier@test.fr", type="AUT_LOCALE")
    magasinier.institution = institution
    magasinier.save()
    from core.models import ContactInstitution
    ContactInstitution.objects.create(institution=institution, utilisateur=magasinier, actif=True)
    client = APIClient()
    client.force_authenticate(user=magasinier)
    local = DepotStock.objects.create(institution=institution, nom="Local")
    camion = DepotStock.objects.create(institution=institution, nom="Camion")
    couvertures = ArticleStock.objects.create(institution=institution, reference="COUV", designation="Couverture de survie",
                                              seuil_alerte=Decimal("20"))
    return {"institution": institution, "agent": magasinier, "client": client, "local": local, "camion": camion, "couvertures": couvertures}


def _mouvement(asso, type_mouvement, quantite, depot="local", **extra):
    return asso["client"].post("/api/stocks/mouvements/", {
        "article": str(asso["couvertures"].id), "depot": str(asso[depot].id), "type": type_mouvement, "quantite": quantite, **extra,
    }, format="json")


@pytest.mark.django_db
class TestMouvements:
    def test_le_stock_se_deduit_des_entrees_et_des_sorties(self, asso):
        assert _mouvement(asso, "ENTREE", "100", prix_unitaire="1,50", tiers="Protection civile").status_code == 201
        reponse = _mouvement(asso, "SORTIE", 30, motif="Dotation équipe Nord")

        assert reponse.status_code == 201 and reponse.data["stock"] == "70.000"
        assert stocks.quantite_en_stock(asso["couvertures"], asso["local"]) == Decimal("70")
        assert MouvementStock.objects.get(type="SORTIE").quantite == Decimal("-30")
        asso["couvertures"].refresh_from_db()
        assert asso["couvertures"].prix_unitaire == Decimal("1.5")

    def test_une_sortie_ne_rend_jamais_le_stock_negatif(self, asso):
        _mouvement(asso, "ENTREE", 10)

        reponse = _mouvement(asso, "SORTIE", 11)

        assert reponse.status_code == 400 and "Il n'y a que 10" in reponse.data["detail"] and "inventaire" in reponse.data["detail"]
        assert MouvementStock.objects.count() == 1
        assert _mouvement(asso, "SORTIE", 5, depot="camion").status_code == 400          # rien dans le camion

    def test_un_inventaire_dit_ce_quon_a_compte_et_trace_lecart(self, asso):
        _mouvement(asso, "ENTREE", 50)

        assert _mouvement(asso, "INVENTAIRE", 46, motif="Inventaire annuel").status_code == 201
        assert MouvementStock.objects.get(type="INVENTAIRE").quantite == Decimal("-4")
        sans_ecart = _mouvement(asso, "INVENTAIRE", 46)
        assert sans_ecart.status_code == 200 and sans_ecart.data["mouvements"] == []
        assert stocks.quantite_en_stock(asso["couvertures"]) == Decimal("46")

    def test_un_transfert_deplace_sans_creer_ni_perdre(self, asso):
        _mouvement(asso, "ENTREE", 40)

        reponse = _mouvement(asso, "TRANSFERT", 15, depot_destination=str(asso["camion"].id))

        assert reponse.status_code == 201 and len(reponse.data["mouvements"]) == 2
        assert stocks.quantite_en_stock(asso["couvertures"], asso["local"]) == Decimal("25")
        assert stocks.quantite_en_stock(asso["couvertures"], asso["camion"]) == Decimal("15")
        assert MouvementStock.objects.filter(type="TRANSFERT").values("transfert").distinct().count() == 1
        assert _mouvement(asso, "TRANSFERT", 99, depot_destination=str(asso["camion"].id)).status_code == 400
        assert MouvementStock.objects.count() == 3                                       # le transfert refusé n'a rien laissé

    def test_le_cout_moyen_se_pondere_aux_entrees_valorisees(self, asso):
        _mouvement(asso, "ENTREE", 10, prix_unitaire=2)
        _mouvement(asso, "ENTREE", 30, prix_unitaire=4)

        asso["couvertures"].refresh_from_db()
        assert asso["couvertures"].prix_unitaire == Decimal("3.5")

    def test_le_journal_ne_se_corrige_pas(self, asso):
        mouvement = _mouvement(asso, "ENTREE", 10).data["mouvements"][0]

        assert asso["client"].patch(f"/api/stocks/mouvements/{mouvement['id']}/", {"quantite": 99}, format="json").status_code == 405
        assert asso["client"].delete(f"/api/stocks/mouvements/{mouvement['id']}/").status_code == 405
        assert asso["client"].delete(f"/api/stocks/articles/{asso['couvertures'].id}/").status_code == 400   # il a des mouvements


@pytest.mark.django_db
class TestEtatDuStock:
    def test_signale_le_seuil_et_les_peremptions(self, asso):
        aujourd_hui = datetime.date.today()
        _mouvement(asso, "ENTREE", 12, lot="A1", date_peremption=str(aujourd_hui - datetime.timedelta(days=3)))
        _mouvement(asso, "ENTREE", 6, lot="B2", date_peremption=str(aujourd_hui + datetime.timedelta(days=10)), depot="camion")

        etat = asso["client"].get("/api/stocks/etat/").data

        ligne = etat["articles"][0]
        assert Decimal(ligne["total"]) == 18 and ligne["sous_seuil"] is True
        assert Decimal(ligne["perime"]) == 12 and Decimal(ligne["bientot_perime"]) == 6
        assert ligne["par_depot"] == {str(asso["local"].id): Decimal("12"), str(asso["camion"].id): Decimal("6")}
        assert etat["alertes"] == {"sous_seuil": 1, "perimes": 1, "bientot_perimes": 1, "mal_ranges": 0}
        # Une sortie se fait dans un lot précis quand on le nomme.
        assert _mouvement(asso, "SORTIE", 12, lot="A1", date_peremption=str(aujourd_hui - datetime.timedelta(days=3)), motif="Péremption").status_code == 201
        assert asso["client"].get("/api/stocks/etat/").data["alertes"]["perimes"] == 0

    def test_chaque_institution_ne_voit_que_son_stock(self, asso, create_user):
        _mouvement(asso, "ENTREE", 5)
        itype = asso["institution"].type
        autre = Institution.objects.create(nom="Autre association", type=itype, commune_code="42218")
        voisin = create_user(username="voisin-stock@test.fr", email="voisin-stock@test.fr", type="AUT_LOCALE")
        voisin.institution = autre
        voisin.save()
        from core.models import ContactInstitution
        ContactInstitution.objects.create(institution=autre, utilisateur=voisin, actif=True)
        client = APIClient()
        client.force_authenticate(user=voisin)

        assert client.get("/api/stocks/etat/").data["articles"] == []
        assert client.get("/api/stocks/articles/").data == [] and client.get("/api/stocks/mouvements/").data == []
        refus = client.post("/api/stocks/mouvements/", {"article": str(asso["couvertures"].id), "depot": str(asso["local"].id),
                                                         "type": "SORTIE", "quantite": 1}, format="json")
        assert refus.status_code == 400 and stocks.quantite_en_stock(asso["couvertures"]) == Decimal("5")
        citoyen = create_user(username="citoyen-stock@test.fr", email="citoyen-stock@test.fr", type="UTIL_SIMPLE")
        client.force_authenticate(user=citoyen)
        assert client.get("/api/stocks/etat/").status_code == 403

    def test_articles_et_depots_se_creent_sans_doublon(self, asso):
        cree = asso["client"].post("/api/stocks/articles/", {"reference": "GEL", "designation": "Gel hydroalcoolique", "unite": "litre"}, format="json")
        assert cree.status_code == 201 and cree.data["institution"] == asso["institution"].id
        assert asso["client"].post("/api/stocks/articles/", {"reference": "gel", "designation": "Autre"}, format="json").status_code == 400
        assert asso["client"].post("/api/stocks/depots/", {"nom": "local"}, format="json").status_code == 400
        assert asso["client"].post("/api/stocks/depots/", {"nom": "Armoire PC", "adresse": "Mairie, 1er étage"}, format="json").status_code == 201


@pytest.mark.django_db
class TestRepriseDunFichier:
    EXPORT = ("Réf.;Libellé;Entrepôt;Stock physique;Stock limite pour alerte;PMP;Lot;Date de péremption\n"
              "COUV;Couverture de survie;Local;120;20;1,20;;\n"
              "MASQ;Masque FFP2;Armoire;300;50;0,35;L2026;31/12/2027\n"
              "RAT;Ration 24 h;;abc;;;;\n"
              ";;Local;4;;;;\n").encode("utf-8")

    def _importer(self, asso, **extra):
        return asso["client"].post("/api/stocks/import/", {"fichier": SimpleUploadedFile("export.csv", self.EXPORT, content_type="text/csv"), **extra},
                                   format="multipart")

    def test_la_verification_ne_touche_a_rien(self, asso):
        bilan = self._importer(asso, simuler="1").data

        assert bilan["simulation"] is True and bilan["articles_crees"] == 2 and bilan["depots_crees"] == 1
        assert ArticleStock.objects.count() == 1 and MouvementStock.objects.count() == 0

    def test_reprend_un_export_dolibarr_sans_doubler_au_second_passage(self, asso):
        bilan = self._importer(asso).data

        assert bilan["articles_crees"] == 2 and bilan["articles_existants"] == 1 and bilan["depots_crees"] == 1
        assert bilan["quantites_posees"] == 2 and [e["ligne"] for e in bilan["erreurs"]] == [4, 5]
        masques = ArticleStock.objects.get(reference="MASQ")
        assert masques.seuil_alerte == 50 and masques.prix_unitaire == Decimal("0.35") and masques.perissable is True
        assert stocks.quantite_en_stock(asso["couvertures"]) == Decimal("120")
        lot = MouvementStock.objects.get(article=masques)
        assert lot.lot == "L2026" and lot.date_peremption == datetime.date(2027, 12, 31) and lot.depot.nom == "Armoire"

        self._importer(asso)
        assert stocks.quantite_en_stock(masques) == Decimal("300") and MouvementStock.objects.count() == 2

    def test_exporte_letat_pour_un_tableur(self, asso):
        _mouvement(asso, "ENTREE", "12,5")

        reponse = asso["client"].get("/api/stocks/etat/", {"format_fichier": "csv"})

        assert reponse["Content-Type"].startswith("text/csv")
        assert "COUV;Couverture de survie;Local;12,5;unité;20" in reponse.content.decode("utf-8-sig")


@pytest.mark.django_db
class TestStockDunPointDaccueil:
    """Un point d'accueil est un lieu de stock : on le dote, on y reçoit, on y distribue, on
    rapatrie le reste — et sa ligne de stock suit."""

    @pytest.fixture
    def gymnase(self, asso):
        from django.contrib.gis.geos import Point
        from core.models import Crisis, PointOperationnel, PointType, Team

        crise = Crisis.objects.create(name="Crue des essais", type="INONDATION", location=Point(4.51, 45.47, srid=4326))
        equipe = Team.objects.create(name="Accueil", description="", color="#3b82f6", institution=asso["institution"])
        equipe.members.add(asso["agent"])                    # le magasinier tient aussi le point
        ptype = PointType.objects.first() or PointType.objects.create(nom="Centre d'accueil")
        point = PointOperationnel.objects.create(nom="Gymnase", type=ptype, crise=crise, equipe=equipe, location=Point(4.51, 45.47, srid=4326))
        return {**asso, "point": point, "crise": crise, "equipe": equipe, "url": f"/api/stocks/points/{point.id}/"}

    def test_doter_puis_distribuer_met_a_jour_la_ligne_du_point(self, gymnase):
        from core.models import MaterielPoint

        _mouvement(gymnase, "ENTREE", 100)
        dote = gymnase["client"].post(gymnase["url"] + "doter/", {"article": str(gymnase["couvertures"].id), "depot": str(gymnase["local"].id),
                                                                   "quantite": 40}, format="json")

        assert dote.status_code == 201, dote.data
        ligne = MaterielPoint.objects.get(point=gymnase["point"])
        assert ligne.quantite == 40 and ligne.niveau_stock == "OK" and ligne.item.nom == "Couverture de survie"
        assert stocks.quantite_en_stock(gymnase["couvertures"], gymnase["local"]) == Decimal("60")
        assert MouvementStock.objects.filter(type="TRANSFERT", crise=gymnase["crise"]).count() == 2

        distribue = gymnase["client"].post(gymnase["url"] + "distribuer/", {"item": str(ligne.item_id), "quantite": 15, "tiers": "Famille relogée"}, format="json")
        assert distribue.status_code == 201 and distribue.data["lignes"][0]["quantite"] == Decimal("25")
        trop = gymnase["client"].post(gymnase["url"] + "distribuer/", {"item": str(ligne.item_id), "quantite": 26}, format="json")
        assert trop.status_code == 400 and "Il n'y a que 25" in trop.data["detail"]
        # Tout distribuer : la jauge dit « nul » d'elle-même.
        gymnase["client"].post(gymnase["url"] + "distribuer/", {"item": str(ligne.item_id), "quantite": 25}, format="json")
        ligne.refresh_from_db()
        assert ligne.quantite == 0 and ligne.niveau_stock == "NUL"

    def test_les_lots_qui_periment_dabord_partent_dabord(self, gymnase):
        tot, tard = "2027-01-31", "2028-01-31"
        for lot, date in (("TARD", tard), ("TOT", tot)):
            _mouvement(gymnase, "ENTREE", 10, lot=lot, date_peremption=date)
            gymnase["client"].post(gymnase["url"] + "doter/", {"article": str(gymnase["couvertures"].id), "depot": str(gymnase["local"].id),
                                                                "quantite": 10, "lot": lot, "date_peremption": date}, format="json")
        item = gymnase["couvertures"].__class__.objects.get(pk=gymnase["couvertures"].pk).catalogue

        gymnase["client"].post(gymnase["url"] + "distribuer/", {"item": str(item.id), "quantite": 12}, format="json")

        sorties = {m.lot: m.quantite for m in MouvementStock.objects.filter(type="SORTIE", depot__point=gymnase["point"])}
        assert sorties == {"TOT": Decimal("-10"), "TARD": Decimal("-2")}

    def test_un_don_recu_au_point_entre_au_journal_avec_les_apports_deja_traces(self, gymnase):
        from core.models import ContributionMateriel, MaterielCatalogue, MaterielPoint

        item = MaterielCatalogue.objects.create(nom="Lit de camp")
        ligne = MaterielPoint.objects.create(point=gymnase["point"], item=item)
        ContributionMateriel.objects.create(materiel_point=ligne, fournisseur_nom="Ancien don", quantite=6)      # avant le journal

        apport = gymnase["client"].post("/api/contributions-materiel/", {"materiel_point": str(ligne.id), "fournisseur_nom": "M. Martin", "quantite": 4}, format="json")

        assert apport.status_code == 201, apport.data
        assert stocks_total(gymnase["point"], item) == Decimal("10")
        etat = gymnase["client"].get(gymnase["url"]).data
        assert etat["lignes"][0]["item_nom"] == "Lit de camp" and etat["lignes"][0]["quantite"] == Decimal("10")
        assert etat["mouvements"][0]["tiers"] in ("M. Martin", "")
        # La fenêtre du point lit maintenant le journal : ce qui sort est déduit.
        gymnase["client"].post(gymnase["url"] + "distribuer/", {"item": str(item.id), "quantite": 3}, format="json")
        lignes = gymnase["client"].get(f"/api/points-operationnels/{gymnase['point'].id}/stocks/").data
        assert next(l for l in lignes if str(l["item"]) == str(item.id))["quantite_totale"] == 7

    def test_compter_au_point_corrige_dans_les_deux_sens(self, gymnase):
        from core.models import MaterielCatalogue

        item = MaterielCatalogue.objects.create(nom="Pack d'eau")
        for compte, attendu in ((24, Decimal("24")), (20, Decimal("20")), (20, Decimal("20"))):
            reponse = gymnase["client"].post(gymnase["url"] + "compter/", {"item": str(item.id), "quantite": compte}, format="json")
            assert reponse.status_code == 201 and stocks_total(gymnase["point"], item) == attendu
        assert MouvementStock.objects.filter(depot__point=gymnase["point"], type="INVENTAIRE").count() == 2

    def test_rapatrier_ramene_le_reste_au_depot(self, gymnase):
        _mouvement(gymnase, "ENTREE", 50)
        gymnase["client"].post(gymnase["url"] + "doter/", {"article": str(gymnase["couvertures"].id), "depot": str(gymnase["local"].id), "quantite": 30}, format="json")
        assert gymnase["client"].get(gymnase["url"]).data["a_rapatrier"] is True

        retour = gymnase["client"].post(gymnase["url"] + "rapatrier/", {"depot": str(gymnase["camion"].id)}, format="json")

        assert retour.status_code == 201 and retour.data["a_rapatrier"] is False
        assert stocks.quantite_en_stock(gymnase["couvertures"], gymnase["camion"]) == Decimal("30")
        assert stocks.quantite_en_stock(gymnase["couvertures"]) == Decimal("50")                # rien de créé, rien de perdu

    def test_lequipe_du_point_distribue_mais_ne_puise_pas_dans_les_depots(self, gymnase, create_user):
        _mouvement(gymnase, "ENTREE", 50)
        gymnase["client"].post(gymnase["url"] + "doter/", {"article": str(gymnase["couvertures"].id), "depot": str(gymnase["local"].id), "quantite": 30}, format="json")
        item = ArticleStock.objects.get(pk=gymnase["couvertures"].pk).catalogue
        benevole = create_user(username="accueil-stock@test.fr", email="accueil-stock@test.fr", type="UTIL_SIMPLE")
        gymnase["equipe"].members.add(benevole)
        client = APIClient()
        client.force_authenticate(user=benevole)

        assert client.post(gymnase["url"] + "distribuer/", {"item": str(item.id), "quantite": 2}, format="json").status_code == 201
        assert client.post(gymnase["url"] + "doter/", {"article": str(gymnase["couvertures"].id), "depot": str(gymnase["local"].id), "quantite": 1}, format="json").status_code == 403
        passant = create_user(username="passant-stock@test.fr", email="passant-stock@test.fr", type="UTIL_SIMPLE")
        client.force_authenticate(user=passant)
        assert client.get(gymnase["url"]).status_code == 403


def stocks_total(point, item):
    from core import stocks_points
    return stocks_points.quantites(point).get(item.id, Decimal("0"))
