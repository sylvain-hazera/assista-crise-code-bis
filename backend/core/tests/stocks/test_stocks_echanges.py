"""Second volet des stocks : denrées (froid, préparation), commandes et factures, prêts dans les
deux sens avec fiche d'état, et don qui change de mains entre deux points."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core import stocks, stocks_points
from core.models import (
    ArticleStock, CommandeStock, ContactInstitution, Crisis, DepotStock, Document, Institution, InstitutionType, MaterielPoint,
    MouvementStock, PointOperationnel, PointType, PretMateriel, Team, TiersStock,
)
from core.tests.stocks.test_stocks import _mouvement, asso  # noqa: F401  (fixture partagée)


def _image() -> bytes:
    import io

    from PIL import Image
    tampon = io.BytesIO()
    Image.new("RGB", (320, 240), (120, 120, 120)).save(tampon, format="JPEG")
    return tampon.getvalue()


def _institution(create_user, nom, identifiant, commune="42218"):
    itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
    institution = Institution.objects.create(nom=nom, type=itype, commune_code=commune)
    compte = create_user(username=f"{identifiant}@test.fr", email=f"{identifiant}@test.fr", type="AUT_LOCALE")
    compte.institution = institution
    compte.save()
    ContactInstitution.objects.create(institution=institution, utilisateur=compte, actif=True)
    client = APIClient()
    client.force_authenticate(user=compte)
    return institution, compte, client


def _point(nom, crise, institution, membre):
    equipe = Team.objects.create(name=f"Équipe {nom}", description="", color="#3b82f6", institution=institution)
    equipe.members.add(membre)
    ptype = PointType.objects.first() or PointType.objects.create(nom="Centre d'accueil")
    return PointOperationnel.objects.create(nom=nom, type=ptype, crise=crise, equipe=equipe, location=Point(4.51, 45.47, srid=4326))


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name="Crue des essais", type="INONDATION", location=Point(4.51, 45.47, srid=4326))


@pytest.mark.django_db
class TestDenrees:
    def test_une_denree_au_frais_rangee_sans_froid_est_signalee_pas_refusee(self, asso):
        plats = ArticleStock.objects.create(institution=asso["institution"], reference="PLAT", designation="Plat cuisiné",
                                            conservation="FRAIS", preparation="A_RECHAUFFER", perissable=True)

        entree = asso["client"].post("/api/stocks/mouvements/", {"article": str(plats.id), "depot": str(asso["local"].id),
                                                                  "type": "ENTREE", "quantite": 40}, format="json")

        assert entree.status_code == 201 and "pas de réfrigérateur" in entree.data["avertissement"]
        etat = asso["client"].get("/api/stocks/etat/").data
        ligne = next(a for a in etat["articles"] if a["reference"] == "PLAT")
        assert ligne["mal_range"][0]["nom"] == "Local" and etat["alertes"]["mal_ranges"] == 1
        # Le dépôt s'équipe : plus rien à signaler. (La préparation ne se juge qu'à un point.)
        asso["client"].patch(f"/api/stocks/depots/{asso['local'].id}/", {"froid_positif": True}, format="json")
        assert asso["client"].get("/api/stocks/etat/").data["alertes"]["mal_ranges"] == 0

    def test_un_point_sans_de_quoi_chauffer_le_dit_pour_un_plat_a_rechauffer(self, asso, crise):
        point = _point("Gymnase", crise, asso["institution"], asso["agent"])
        plats = ArticleStock.objects.create(institution=asso["institution"], reference="PLAT", designation="Plat cuisiné",
                                            conservation="FRAIS", preparation="A_RECHAUFFER")
        asso["client"].post("/api/stocks/mouvements/", {"article": str(plats.id), "depot": str(asso["local"].id), "type": "ENTREE", "quantite": 40}, format="json")
        url = f"/api/stocks/points/{point.id}/"

        dote = asso["client"].post(url + "doter/", {"article": str(plats.id), "depot": str(asso["local"].id), "quantite": 20}, format="json").data

        ligne = dote["lignes"][0]
        assert ligne["conservation"] == "FRAIS" and ligne["preparation"] == "A_RECHAUFFER"
        assert len(ligne["manques"]) == 2 and "rien pour chauffer" in " ".join(ligne["manques"])
        equipe = asso["client"].post(url + "moyens/", {"froid_positif": True, "cuisson": "RECHAUFFAGE"}, format="json")
        assert equipe.status_code == 201 and equipe.data["lignes"][0]["manques"] == []
        assert equipe.data["moyens"] == {"froid_positif": True, "froid_negatif": False, "cuisson": "RECHAUFFAGE"}


@pytest.mark.django_db
class TestDonQuiChangeDeMains:
    def test_un_transfert_entre_points_fait_passer_le_stock_a_linstitution_darrivee(self, asso, crise, create_user):
        mairie, agent_mairie, client_mairie = _institution(create_user, "Mairie voisine", "mairie-stock")
        gymnase = _point("Gymnase", crise, asso["institution"], asso["agent"])
        salle = _point("Salle des fêtes", crise, mairie, agent_mairie)
        from core.models import MaterielCatalogue
        eau = MaterielCatalogue.objects.create(nom="Pack d'eau")
        # Un don reçu au gymnase appartient à l'association qui le tient.
        asso["client"].post(f"/api/stocks/points/{gymnase.id}/recevoir/", {"item": str(eau.id), "quantite": 30, "tiers": "Supermarché"}, format="json")
        assert DepotStock.objects.get(point=gymnase).institution == asso["institution"]

        # Un transfert ne se fait plus d'office : la mairie le demande, l'association qui tient le gymnase l'accepte.
        assert asso["client"].post(f"/api/stocks/points/{gymnase.id}/transferer/", {"destination": str(salle.id), "item": str(eau.id), "quantite": 12}, format="json").status_code == 400
        assert asso["client"].post("/api/stocks/transferts/", {"source": str(gymnase.id), "destination": str(salle.id), "item": str(eau.id), "quantite": 20}, format="json").status_code == 403
        demande = client_mairie.post("/api/stocks/transferts/", {"source": str(gymnase.id), "destination": str(salle.id), "item": str(eau.id),
                                                                  "quantite": 20, "message": "Pour la nuit."}, format="json")
        assert demande.status_code == 201 and demande.data["statut"] == "DEMANDEE" and Decimal(demande.data["en_stock_au_depart"]) == 30
        assert stocks_points.quantites(gymnase)[eau.id] == Decimal("30")                               # rien n'a bougé
        assert client_mairie.post(f"/api/stocks/transferts/{demande.data['id']}/accepter/").status_code == 403    # ce n'est pas à elle de décider
        reponse = asso["client"].post(f"/api/stocks/transferts/{demande.data['id']}/accepter/", {"quantite": 12, "reponse": "On en garde pour ici."}, format="json")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["statut"] == "ACCEPTEE" and reponse.data["quantite_accordee"] == 12
        assert asso["client"].post(f"/api/stocks/transferts/{demande.data['id']}/accepter/").status_code == 400    # déjà répondu
        assert stocks_points.quantites(gymnase)[eau.id] == Decimal("18") and stocks_points.quantites(salle)[eau.id] == Decimal("12")
        arrivee = MouvementStock.objects.get(depot__point=salle)
        assert arrivee.depot.institution == mairie and arrivee.article.institution == mairie          # il a changé de mains
        assert "passe de Réserve des essais à Mairie voisine" in arrivee.motif and arrivee.type == "TRANSFERT"
        assert MaterielPoint.objects.get(point=salle, item=eau).quantite == 12
        # La mairie le voit dans SON stock, l'association ne le compte plus.
        assert Decimal(client_mairie.get("/api/stocks/etat/").data["articles"][0]["total"]) == 12
        assert Decimal(next(a for a in asso["client"].get("/api/stocks/etat/").data["articles"] if a["designation"] == "Pack d'eau")["total"]) == 18
        # Demander plus qu'il n'y a : l'acceptation échoue et rien ne part ; un refus se dit avec sa raison.
        trop = client_mairie.post("/api/stocks/transferts/", {"source": str(gymnase.id), "destination": str(salle.id), "item": str(eau.id), "quantite": 99}, format="json").data
        assert asso["client"].post(f"/api/stocks/transferts/{trop['id']}/accepter/").status_code == 400
        assert stocks_points.quantites(salle)[eau.id] == Decimal("12")
        refus = asso["client"].post(f"/api/stocks/transferts/{trop['id']}/refuser/", {"reponse": "Nous en avons besoin."}, format="json")
        assert refus.data["statut"] == "REFUSEE" and refus.data["reponse"] == "Nous en avons besoin."
        assert [d["statut"] for d in client_mairie.get("/api/stocks/transferts/", {"point": str(salle.id)}).data] == ["REFUSEE", "ACCEPTEE"]


@pytest.mark.django_db
class TestCommandesEtFactures:
    def _commande(self, asso):
        fournisseur = asso["client"].post("/api/stocks/tiers/", {"nom": "Protec SARL", "type": "PROFESSIONNEL", "est_fournisseur": True}, format="json").data
        commande = asso["client"].post("/api/stocks/commandes/", {
            "tiers": fournisseur["id"], "depot": str(asso["local"].id),
            "lignes": [{"article": str(asso["couvertures"].id), "quantite": 100, "prix_unitaire": "1,20"}]}, format="json")
        assert commande.status_code == 201, commande.data
        return fournisseur, commande.data

    def test_une_commande_recue_en_deux_fois_entre_en_stock_au_prix_commande(self, asso):
        _fournisseur, commande = self._commande(asso)
        assert commande["numero"].startswith("CF-") and commande["numero"].endswith("-0001") and Decimal(commande["total"]) == Decimal("120.00")
        url = f"/api/stocks/commandes/{commande['id']}/"
        ligne = commande["lignes"][0]["id"]

        assert asso["client"].post(url + "recevoir/", {"receptions": [{"ligne": ligne, "quantite": 10}]}, format="json").status_code == 400   # pas encore passée
        assert asso["client"].post(url + "passer/").data["statut"] == "COMMANDEE"
        assert asso["client"].patch(url, {"lignes": []}, format="json").status_code == 400                                              # figée
        partie = asso["client"].post(url + "recevoir/", {"receptions": [{"ligne": ligne, "quantite": 60, "lot": "L1"}]}, format="json")
        assert partie.data["statut"] == "RECUE_EN_PARTIE" and Decimal(partie.data["lignes"][0]["quantite_recue"]) == 60
        assert asso["client"].post(url + "annuler/").status_code == 400
        tout = asso["client"].post(url + "recevoir/", {"receptions": [{"ligne": ligne, "quantite": 40}]}, format="json")

        assert tout.data["statut"] == "RECUE" and stocks.quantite_en_stock(asso["couvertures"], asso["local"]) == Decimal("100")
        entree = MouvementStock.objects.filter(lot="L1").get()
        assert entree.prix_unitaire == Decimal("1.2") and entree.tiers == "Protec SARL" and commande["numero"] in entree.motif
        asso["couvertures"].refresh_from_db()
        assert asso["couvertures"].prix_unitaire == Decimal("1.2")

    def test_la_facture_se_range_avec_sa_commande_et_sa_piece_reste_chiffree(self, asso, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        fournisseur, commande = self._commande(asso)
        hier = datetime.date.today() - datetime.timedelta(days=1)

        cree = asso["client"].post("/api/stocks/factures/", {
            "tiers": fournisseur["id"], "commande": commande["id"], "numero": "F-2026-118", "date_facture": str(hier),
            "montant_ht": "100.00", "montant_ttc": "120.00", "echeance": str(hier),
            "fichier": SimpleUploadedFile("facture.pdf", b"%PDF-1.4 facture d'essai", content_type="application/pdf")}, format="multipart")

        assert cree.status_code == 201, cree.data
        assert cree.data["a_une_piece"] is True and cree.data["en_retard"] is True and "fichier" not in cree.data
        assert cree.data["commande_numero"] == commande["numero"]
        piece = asso["client"].get(f"/api/stocks/factures/{cree['id'] if False else cree.data['id']}/piece/")
        assert piece.content == b"%PDF-1.4 facture d'essai"
        from core.models import FactureStock
        with open(FactureStock.objects.get().fichier.path, "rb") as brut:
            assert b"facture d'essai" not in brut.read()                                   # rien en clair sur le disque
        payee = asso["client"].patch(f"/api/stocks/factures/{cree.data['id']}/", {"payee_le": str(datetime.date.today())}, format="json")
        assert payee.data["en_retard"] is False

    def test_les_tiers_dune_autre_institution_ne_se_voient_ni_ne_semploient(self, asso, create_user):
        fournisseur, _commande = self._commande(asso)
        _mairie, _agent, client = _institution(create_user, "Mairie voisine", "mairie-tiers")

        assert client.get("/api/stocks/tiers/").data == [] and client.get("/api/stocks/commandes/").data == []
        refus = client.post("/api/stocks/commandes/", {"tiers": fournisseur["id"], "lignes": []}, format="json")
        assert refus.status_code == 400 and CommandeStock.objects.count() == 1
        assert [t["nom"] for t in asso["client"].get("/api/stocks/tiers/", {"recherche": "protec"}).data] == ["Protec SARL"]
        assert asso["client"].get("/api/stocks/tiers/", {"recherche": "inconnu"}).data == []


@pytest.mark.django_db
class TestPrets:
    def _tiers(self, asso, nom="M. Bernard", type_tiers="PARTICULIER"):
        return asso["client"].post("/api/stocks/tiers/", {"nom": nom, "type": type_tiers, "telephone": "0600000000"}, format="json").data["id"]

    def test_un_pret_consenti_sort_du_stock_et_y_revient_avec_sa_fiche_detat(self, asso, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        _mouvement(asso, "ENTREE", 10)
        debut = datetime.date.today() - datetime.timedelta(days=10)

        pret = asso["client"].post("/api/stocks/prets/", {
            "sens": "CONSENTI", "tiers": self._tiers(asso), "article": str(asso["couvertures"].id), "depot": str(asso["local"].id),
            "quantite": 4, "date_debut": str(debut), "retour_prevu": str(debut + datetime.timedelta(days=3)),
            "etat_depart": "BON", "constat_depart": "Emballages intacts."}, format="json")

        assert pret.status_code == 201, pret.data
        assert pret.data["designation"] == "Couverture de survie" and pret.data["en_retard"] is True
        assert stocks.quantite_en_stock(asso["couvertures"], asso["local"]) == Decimal("6")
        assert "Prêt à M. Bernard" in MouvementStock.objects.get(type="SORTIE").motif
        url = f"/api/stocks/prets/{pret.data['id']}/"
        # Photos au départ ; un moment mal nommé est refusé.
        photo = lambda moment: asso["client"].post("/api/documents/", {  # noqa: E731
            "pret": pret.data["id"], "moment_pret": moment,
            "fichier": SimpleUploadedFile("etat.jpg", _image(), content_type="image/jpeg")}, format="multipart")
        premiere = photo("DEPART")
        assert premiere.status_code == 201, premiere.data
        assert photo("AVANT").status_code == 400
        assert asso["client"].patch(url, {"quantite": 2}, format="json").status_code == 400            # a fait bouger le stock
        assert asso["client"].delete(url).status_code == 400

        rendu = asso["client"].post(url + "rendre/", {"etat_retour": "DEGRADE", "constat_retour": "Une couverture déchirée.", "quantite_rendue": 3}, format="json")

        assert rendu.status_code == 200 and rendu.data["statut"] == "LITIGE" and rendu.data["en_retard"] is False
        assert rendu.data["photos"] == {"depart": 1, "retour": 0}
        assert stocks.quantite_en_stock(asso["couvertures"], asso["local"]) == Decimal("9")            # trois sur quatre
        assert asso["client"].post(url + "rendre/", {"etat_retour": "BON"}, format="json").status_code == 400
        fiche = asso["client"].get(url + "fiche/")
        assert fiche.status_code == 200 and fiche.content.startswith(b"%PDF")

    def test_un_materiel_prete_a_linstitution_entre_puis_ressort(self, asso):
        groupe = ArticleStock.objects.create(institution=asso["institution"], reference="GE", designation="Groupe électrogène")

        pret = asso["client"].post("/api/stocks/prets/", {
            "sens": "RECU", "tiers": self._tiers(asso, "Garage Durand", "PROFESSIONNEL"), "article": str(groupe.id),
            "depot": str(asso["local"].id), "quantite": 1, "date_debut": str(datetime.date.today()), "etat_depart": "USAGE",
            "identification": "SN-4471"}, format="json")

        assert pret.status_code == 201 and stocks.quantite_en_stock(groupe) == Decimal("1")
        rendu = asso["client"].post(f"/api/stocks/prets/{pret.data['id']}/rendre/", {"etat_retour": "USAGE"}, format="json")
        assert rendu.data["statut"] == "RENDU" and stocks.quantite_en_stock(groupe) == Decimal("0")
        assert PretMateriel.objects.get().identification == "SN-4471"

    def test_un_pret_hors_stock_se_trace_sans_mouvement_et_reste_a_linstitution(self, asso, create_user):
        pret = asso["client"].post("/api/stocks/prets/", {
            "sens": "RECU", "tiers": self._tiers(asso), "designation": "Remorque bâchée", "date_debut": str(datetime.date.today()),
            "etat_depart": "BON"}, format="json")

        assert pret.status_code == 201 and MouvementStock.objects.count() == 0
        sans_nom = asso["client"].post("/api/stocks/prets/", {"sens": "RECU", "tiers": pret.data["tiers"], "date_debut": str(datetime.date.today())}, format="json")
        assert sans_nom.status_code == 400
        _mairie, _agent, client = _institution(create_user, "Mairie voisine", "mairie-prets")
        assert client.get("/api/stocks/prets/").data == []
        assert client.post(f"/api/stocks/prets/{pret.data['id']}/rendre/", {"etat_retour": "BON"}, format="json").status_code == 404
        assert client.post("/api/documents/", {"pret": pret.data["id"], "moment_pret": "DEPART",
                                                "fichier": SimpleUploadedFile("x.jpg", _image(), content_type="image/jpeg")}, format="multipart").status_code == 403
        assert Document.objects.count() == 0 and TiersStock.objects.count() == 1


@pytest.mark.django_db
class TestInventaireDunBloc:
    def test_la_feuille_liste_ce_quil_faut_compter_et_la_saisie_corrige_dun_coup(self, asso):
        masques = ArticleStock.objects.create(institution=asso["institution"], reference="MASQ", designation="Masque FFP2", unite="boîte")
        _mouvement(asso, "ENTREE", 50)
        asso["client"].post("/api/stocks/mouvements/", {"article": str(masques.id), "depot": str(asso["local"].id), "type": "ENTREE",
                                                         "quantite": 30, "lot": "L7", "date_peremption": "2027-06-30"}, format="json")

        feuille = asso["client"].get("/api/stocks/inventaire/", {"depot": str(asso["local"].id)}).data["lignes"]
        assert [(l["reference"], l["lot"], Decimal(l["attendu"])) for l in feuille] == [("COUV", "", Decimal("50")), ("MASQ", "L7", Decimal("30"))]
        pdf = asso["client"].get("/api/stocks/etat/", {"depot": str(asso["local"].id), "format_fichier": "pdf", "aveugle": "1"})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert asso["client"].get("/api/stocks/etat/", {"format_fichier": "pdf"}).status_code == 400          # sans dépôt

        saisie = asso["client"].post("/api/stocks/inventaire/", {"depot": str(asso["local"].id), "comptes": [
            {"article": str(asso["couvertures"].id), "quantite": 47},
            {"article": str(masques.id), "lot": "L7", "date_peremption": "2027-06-30", "quantite": 30},     # conforme
            {"article": str(masques.id), "quantite": ""}]}, format="json")                                 # pas comptée

        assert saisie.status_code == 201 and saisie.data["comptees"] == 2 and len(saisie.data["corrections"]) == 1
        assert stocks.quantite_en_stock(asso["couvertures"]) == Decimal("47") and stocks.quantite_en_stock(masques) == Decimal("30")
        # Une ligne fausse annule toute la saisie.
        rate = asso["client"].post("/api/stocks/inventaire/", {"depot": str(asso["local"].id), "comptes": [
            {"article": str(asso["couvertures"].id), "quantite": 10}, {"article": "00000000-0000-0000-0000-000000000000", "quantite": 1}]}, format="json")
        assert rate.status_code == 400 and stocks.quantite_en_stock(asso["couvertures"]) == Decimal("47")


@pytest.mark.django_db
class TestAlertesPoussees:
    def test_le_releve_part_a_ceux_qui_tiennent_le_stock_et_ne_se_repete_pas(self, asso, mailoutbox):
        from core import alertes_stock
        from core.models import Environment, Notification

        _mouvement(asso, "ENTREE", 12)                                # seuil à 20 : alerte ; le magasinier devient destinataire
        tiers = asso["client"].post("/api/stocks/tiers/", {"nom": "M. Bernard", "type": "PARTICULIER"}, format="json").data["id"]
        debut = datetime.date.today() - datetime.timedelta(days=10)
        asso["client"].post("/api/stocks/prets/", {"sens": "CONSENTI", "tiers": tiers, "designation": "Remorque", "date_debut": str(debut),
                                                    "retour_prevu": str(debut + datetime.timedelta(days=2))}, format="json")
        mailoutbox.clear()

        premier = alertes_stock.envoyer(asso["institution"], Environment.PROD)
        second = alertes_stock.envoyer(asso["institution"], Environment.PROD)

        assert premier == {"institution": "Réserve des essais", "alertes": 2, "envoye": True, "destinataires": 1}
        assert second["envoye"] is False and len(mailoutbox) == 1 and mailoutbox[0].to == ["magasinier@test.fr"]
        assert "Seuil franchi — Couverture de survie" in mailoutbox[0].body and "Prêt en retard — Remorque, prêté à M. Bernard" in mailoutbox[0].body
        assert Notification.objects.filter(utilisateur=asso["agent"], titre__contains="2 point(s) à voir").exists()
        # Le stock remonte : le relevé change, il repart.
        _mouvement(asso, "ENTREE", 50)
        assert alertes_stock.envoyer(asso["institution"], Environment.PROD)["alertes"] == 1 and len(mailoutbox) == 2

    def test_tout_est_leve_se_dit_une_fois_et_une_institution_sans_alerte_reste_en_silence(self, asso, mailoutbox):
        from django.core.management import call_command

        from core import alertes_stock
        from core.models import Environment

        _mouvement(asso, "ENTREE", 50)                                # au-dessus du seuil : rien à dire
        mailoutbox.clear()
        assert alertes_stock.envoyer(asso["institution"], Environment.PROD)["envoye"] is False and mailoutbox == []
        _mouvement(asso, "SORTIE", 40)
        alertes_stock.envoyer(asso["institution"], Environment.PROD)
        _mouvement(asso, "ENTREE", 40)
        call_command("alerter_stocks")
        call_command("alerter_stocks")
        assert [m.subject.split(" : ")[-1] for m in mailoutbox] == ["1 point(s) à voir", "plus rien à signaler"]


@pytest.mark.django_db
class TestReservations:
    def test_ce_qui_est_reserve_reste_au_depot_mais_ne_sort_pas_pour_un_autre(self, asso):
        _mouvement(asso, "ENTREE", 10)

        reserve = asso["client"].post("/api/stocks/reservations/", {"article": str(asso["couvertures"].id), "depot": str(asso["local"].id),
                                                                     "quantite": 6, "pour": "Mme Durand, rue du Gier"}, format="json")

        assert reserve.status_code == 201, reserve.data
        assert stocks.quantite_en_stock(asso["couvertures"]) == Decimal("10")                # toujours là
        ligne = asso["client"].get("/api/stocks/etat/").data["articles"][0]
        assert Decimal(ligne["reserve"]) == 6 and Decimal(ligne["disponible"]) == 4
        refus = _mouvement(asso, "SORTIE", 5)
        assert refus.status_code == 400 and "6 sont réservés" in refus.data["detail"]
        assert _mouvement(asso, "SORTIE", 4).status_code == 201
        assert asso["client"].post("/api/stocks/reservations/", {"article": str(asso["couvertures"].id), "depot": str(asso["local"].id), "quantite": 1}, format="json").status_code == 400

        servie = asso["client"].post(f"/api/stocks/reservations/{reserve.data['id']}/servir/")
        assert servie.data["statut"] == "SERVIE" and stocks.quantite_en_stock(asso["couvertures"]) == Decimal("0")
        assert MouvementStock.objects.get(motif="Réservation servie").tiers == "Mme Durand, rue du Gier"    # chiffré : se lit, ne se filtre pas
        assert asso["client"].post(f"/api/stocks/reservations/{reserve.data['id']}/liberer/").status_code == 400

    def test_on_sait_ou_on_en_a_et_liberer_rend_le_stock(self, asso):
        _mouvement(asso, "ENTREE", 10)
        _mouvement(asso, "ENTREE", 5, depot="camion")
        reserve = asso["client"].post("/api/stocks/reservations/", {"article": str(asso["couvertures"].id), "depot": str(asso["local"].id), "quantite": 10}, format="json").data

        ou = asso["client"].get("/api/stocks/disponibilite/", {"recherche": "couverture"}).data

        assert ou["en_stock"] is True and Decimal(ou["articles"][0]["libre"]) == 5
        assert [(l["depot_nom"], Decimal(l["libre"])) for l in ou["articles"][0]["lieux"]] == [("Camion", Decimal("5")), ("Local", Decimal("0"))]
        assert asso["client"].get("/api/stocks/disponibilite/", {"recherche": "tronçonneuse"}).data["en_stock"] is False
        asso["client"].post(f"/api/stocks/reservations/{reserve['id']}/liberer/")
        assert Decimal(asso["client"].get("/api/stocks/disponibilite/", {"recherche": "couverture"}).data["articles"][0]["libre"]) == 15


@pytest.mark.django_db
class TestDotationsTypes:
    def test_un_sac_se_verifie_se_sort_en_entier_ou_pas_du_tout_et_se_rentre(self, asso):
        lampes = ArticleStock.objects.create(institution=asso["institution"], reference="LAMPE", designation="Lampe frontale")
        _mouvement(asso, "ENTREE", 10)
        asso["client"].post("/api/stocks/mouvements/", {"article": str(lampes.id), "depot": str(asso["local"].id), "type": "ENTREE", "quantite": 1}, format="json")
        sac = asso["client"].post("/api/stocks/lots-types/", {"nom": "Sac d'intervention", "lignes": [
            {"article": str(asso["couvertures"].id), "quantite": 4}, {"article": str(lampes.id), "quantite": 2}]}, format="json")
        assert sac.status_code == 201 and len(sac.data["lignes"]) == 2
        url = f"/api/stocks/lots-types/{sac.data['id']}/"

        verif = asso["client"].get(url + "verifier/", {"depot": str(asso["local"].id)}).data
        assert verif["complet"] is False and [Decimal(l["manque"]) for l in verif["lignes"]] == [Decimal("0"), Decimal("1")]
        incomplet = asso["client"].post(url + "sortir/", {"depot": str(asso["local"].id)}, format="json")
        assert incomplet.status_code == 400 and "il manque 1 unité de Lampe frontale" in incomplet.data["detail"]
        assert stocks.quantite_en_stock(asso["couvertures"]) == Decimal("10")                # rien n'est parti

        asso["client"].post("/api/stocks/mouvements/", {"article": str(lampes.id), "depot": str(asso["local"].id), "type": "ENTREE", "quantite": 1}, format="json")
        assert asso["client"].post(url + "sortir/", {"depot": str(asso["local"].id)}, format="json").status_code == 201
        assert stocks.quantite_en_stock(asso["couvertures"]) == Decimal("6") and stocks.quantite_en_stock(lampes) == Decimal("0")
        # Au retour, deux couvertures ont servi : elles ne reviennent pas.
        retour = asso["client"].post(url + "rentrer/", {"depot": str(asso["local"].id), "quantites": {str(asso["couvertures"].id): 2}}, format="json")
        assert retour.status_code == 201 and stocks.quantite_en_stock(asso["couvertures"]) == Decimal("8") and stocks.quantite_en_stock(lampes) == Decimal("2")


@pytest.mark.django_db
class TestAppareils:
    def test_le_controle_se_signale_sans_jamais_bloquer(self, asso):
        from core import alertes_stock
        from core.models import Environment

        il_y_a_14_mois = datetime.date.today() - datetime.timedelta(days=430)
        cree = asso["client"].post("/api/stocks/appareils/", {
            "designation": "Groupe électrogène", "numero": "GE-2", "depot": str(asso["local"].id), "controle_libelle": "Révision annuelle",
            "controle_periodicite_mois": 12, "controle_dernier_le": str(il_y_a_14_mois)}, format="json")

        assert cree.status_code == 201 and cree.data["controle"] == "en_retard" and cree.data["etat"] == "EN_SERVICE"    # en retard, mais en service
        assert any("Contrôle en retard — Groupe électrogène (n° GE-2)" in l for l in alertes_stock.releve(asso["institution"], Environment.PROD))
        url = f"/api/stocks/appareils/{cree.data['id']}/"
        assert asso["client"].post(url + "controler/", {"date": "2999-01-01"}, format="json").status_code == 400

        fait = asso["client"].post(url + "controler/", {"conforme": True, "commentaire": "Vidange faite."}, format="json")

        assert fait.data["controle"] == "a_jour" and fait.data["controles"][0]["commentaire"] == "Vidange faite."
        assert not any("Groupe électrogène" in l for l in alertes_stock.releve(asso["institution"], Environment.PROD))
        sans = asso["client"].post("/api/stocks/appareils/", {"designation": "Tronçonneuse"}, format="json")
        assert sans.data["controle"] == "" and sans.data["controle_prochain_le"] is None
        panne = asso["client"].patch(f"/api/stocks/appareils/{sans.data['id']}/", {"etat": "EN_PANNE"}, format="json")
        assert panne.status_code == 200 and "Appareil en panne — Tronçonneuse." in alertes_stock.releve(asso["institution"], Environment.PROD)


@pytest.mark.django_db
class TestStockDansLeRapportEtLePlan:
    def test_le_rapport_de_crise_dit_ce_qui_a_ete_distribue_et_sa_valeur(self, asso, crise):
        from core import rapports_pdf

        _mouvement(asso, "ENTREE", 100, prix_unitaire=2)
        asso["client"].post("/api/stocks/mouvements/", {"article": str(asso["couvertures"].id), "depot": str(asso["local"].id), "type": "SORTIE",
                                                         "quantite": 30, "crise": str(crise.id)}, format="json")

        bilan = stocks.bilan_de_crise(asso["institution"], crise, "PROD")
        assert bilan["distribue"] == [{"designation": "Couverture de survie", "quantite": "30", "unite": "unité", "valeur": Decimal("60.00")}]
        assert bilan["valeur_distribuee"] == Decimal("60.00") and bilan["recu"] == []
        resume = rapports_pdf.crise_resume(crise, asso["institution"], "PROD", lambda u: "")
        assert resume["stock"]["distribue"][0]["quantite"] == "30"
        assert rapports_pdf.generer("crise", resume, edite_par="Agent").startswith(b"%PDF")
