"""Appels aux dons : un besoin précis, à la pièce près, que les engagements des autres
institutions ferment ligne par ligne — pour qu'on ne collecte pas dix fois le chauffe-biberon."""
from core.tests.outils_chiffre import filtrer_chiffre
import datetime
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone

from core import appels_dons, stocks
from core.models import AppelAuxDons, ArticleStock, BesoinDon, Crisis, EngagementDon, FoyerSinistre
from core.tests.stocks.test_stocks import asso  # noqa: F401
from core.tests.stocks.test_stocks_echanges import _institution


@pytest.fixture(autouse=True)
def reseau_prevenu(monkeypatch):
    """La file des tâches de fond n'existe pas ici : on retient seulement qu'elle a été sollicitée."""
    lances = []
    monkeypatch.setattr("core.tasks.prevenir_le_reseau_des_dons_task.apply_async", lambda args=None, **k: lances.append(args[0]))
    return lances


@pytest.fixture
def monde(asso, create_user):
    crise = Crisis.objects.create(name="Feu des essais", type="INCENDIE", location=Point(-1.14, 44.63, srid=4326))
    _lyon, _a, lyon = _institution(create_user, "Secours de Lyon", "lyon-dons", "69123")
    _lille, _b, lille = _institution(create_user, "Entraide de Lille", "lille-dons", "59350")
    return {**asso, "crise": crise, "lyon": lyon, "lille": lille}


def _foyer(monde):
    return monde["client"].post("/api/dons/foyers/", {
        "nom": "Famille Martin", "crise": str(monde["crise"].id), "contact": "0600000000",
        "personnes": [{"public": "HOMME", "age": 41, "taille_haut": "L", "taille_bas": "L", "pointure": "43"},
                      {"public": "BEBE", "age": 0, "taille_haut": "6 mois"}],
        "besoins": [{"famille": "VETEMENTS", "designation": "T-shirt", "public": "HOMME", "taille": "L", "quantite": 4},
                    {"famille": "PUERICULTURE", "designation": "Chauffe-biberon", "public": "BEBE", "quantite": 1}],
    }, format="json")


def _appel(monde, ouvrir=True):
    appel = monde["client"].post("/api/dons/appels/", {"titre": "Familles sinistrées du feu", "crise": str(monde["crise"].id),
                                                         "depot": str(monde["local"].id), "contact_nom": "Mme Roy"}, format="json").data
    url = f"/api/dons/appels/{appel['id']}/"
    monde["client"].post(url + "reprendre-foyers/")
    if ouvrir:
        assert monde["client"].post(url + "ouvrir/").status_code == 200
    return url


def _ligne(reponse, designation):
    return next(l for l in reponse.data["besoins"] if l["designation"] == designation)


@pytest.mark.django_db
class TestBesoinDesFoyers:
    def test_le_catalogue_donne_les_tailles_par_public(self, monde):
        familles = {f["famille"]: f for f in monde["client"].get("/api/dons/catalogue/").data["familles"]}

        tshirt = next(a for a in familles["VETEMENTS"]["articles"] if a["designation"] == "T-shirt")
        assert "L" in tshirt["tailles"]["HOMME"] and "8 ans" in tshirt["tailles"]["GARCON"] and "BEBE" not in tshirt["tailles"]
        chaussures = next(a for a in familles["VETEMENTS"]["articles"] if a["designation"] == "Chaussures")
        assert "43" in chaussures["tailles"]["HOMME"] and "28" in chaussures["tailles"]["FILLE"]
        assert any(a["designation"] == "Chauffe-biberon" for a in familles["PUERICULTURE"]["articles"])
        assert any(a["designation"] == "Réfrigérateur" for a in familles["ELECTROMENAGER"]["articles"])

    def test_le_trousseau_se_propose_dans_les_tailles_de_chacun(self, monde):
        foyer = _foyer(monde)
        assert foyer.status_code == 201, foyer.data
        assert foyer.data["reference"] == "F-001" and len(foyer.data["personnes"]) == 2

        trousseau = monde["client"].get(f"/api/dons/foyers/{foyer.data['id']}/trousseau/").data

        homme = next(p for p in trousseau if p["public"] == "HOMME")["lignes"]
        assert next(l for l in homme if l["designation"] == "Chaussures")["taille"] == "43"
        assert next(l for l in homme if l["designation"] == "T-shirt")["taille"] == "L"
        assert next(l for l in homme if l["designation"].startswith("Sous-vêtements"))["neuf_exige"] is True
        bebe = next(p for p in trousseau if p["public"] == "BEBE")["lignes"]
        assert next(l for l in bebe if l["designation"] == "Body")["taille"] == "6 mois"
        assert any(l["designation"] == "Chauffe-biberon" for l in bebe) and not any(l["designation"] == "Chaussures" for l in bebe)

    def test_lappel_porte_la_somme_des_foyers_et_jamais_leurs_noms(self, monde):
        _foyer(monde)
        monde["client"].post("/api/dons/foyers/", {"nom": "Famille Petit", "crise": str(monde["crise"].id), "besoins": [
            {"famille": "VETEMENTS", "designation": "T-shirt", "public": "HOMME", "taille": "L", "quantite": 3}]}, format="json")
        url = _appel(monde)

        vu_de_lyon = monde["lyon"].get(url)

        assert _ligne(vu_de_lyon, "T-shirt")["quantite_voulue"] == 7 and _ligne(vu_de_lyon, "Chauffe-biberon")["quantite_voulue"] == 1
        assert vu_de_lyon.data["le_mien"] is False and vu_de_lyon.data["depot_nom"] is None
        assert "Martin" not in str(vu_de_lyon.data) and "Petit" not in str(vu_de_lyon.data)
        assert monde["lyon"].get("/api/dons/foyers/").data == []                       # les foyers restent chez l'institution

    def test_un_brouillon_ne_se_voit_pas_dailleurs_et_ne_souvre_pas_vide(self, monde):
        vide = monde["client"].post("/api/dons/appels/", {"titre": "Vide", "depot": str(monde["local"].id)}, format="json").data
        assert monde["client"].post(f"/api/dons/appels/{vide['id']}/ouvrir/").status_code == 400
        _foyer(monde)
        url = _appel(monde, ouvrir=False)

        assert monde["lyon"].get(url).status_code == 404 and monde["lyon"].get("/api/dons/appels/").data == []
        assert monde["lyon"].post(url + "ouvrir/").status_code == 404


@pytest.mark.django_db
class TestEngagements:
    def test_un_seul_chauffe_biberon_ne_se_promet_quune_fois(self, monde):
        _foyer(monde)
        url = _appel(monde)
        biberon = _ligne(monde["lyon"].get(url), "Chauffe-biberon")["id"]

        premier = monde["lyon"].post(url + "engager/", {"besoin": biberon, "quantite": 1}, format="json")
        second = monde["lille"].post(url + "engager/", {"besoin": biberon, "quantite": 1}, format="json")

        assert premier.status_code == 201 and _ligne(premier, "Chauffe-biberon")["reste"] == 0
        assert second.status_code == 400 and "déjà entièrement couvert" in second.data["detail"]
        # Lille voit la ligne fermée, sans savoir par qui ; Lyon voit son engagement ; l'auteur de l'appel voit qui.
        assert _ligne(monde["lille"].get(url), "Chauffe-biberon")["engagements"] == []
        assert _ligne(monde["lyon"].get(url), "Chauffe-biberon")["engagements"][0]["le_mien"] is True
        assert _ligne(monde["client"].get(url), "Chauffe-biberon")["engagements"][0]["institution_nom"] == "Secours de Lyon"

    def test_on_ne_sengage_pas_au_dela_du_reste_et_la_part_se_partage(self, monde):
        _foyer(monde)
        url = _appel(monde)
        tshirt = _ligne(monde["lyon"].get(url), "T-shirt")["id"]

        assert monde["lyon"].post(url + "engager/", {"besoin": tshirt, "quantite": 3}, format="json").status_code == 201
        trop = monde["lille"].post(url + "engager/", {"besoin": tshirt, "quantite": 2}, format="json")
        juste = monde["lille"].post(url + "engager/", {"besoin": tshirt, "quantite": 1}, format="json")

        assert trop.status_code == 400 and "Il n'en reste que 1" in trop.data["detail"]
        assert juste.status_code == 201 and juste.data["avancement"]["pieces_restantes"] == 1          # le chauffe-biberon
        assert monde["client"].post(url + "engager/", {"besoin": tshirt, "quantite": 1}, format="json").status_code == 400   # son propre appel

    def test_un_engagement_sans_envoi_se_relache_et_rouvre_la_ligne(self, monde):
        _foyer(monde)
        url = _appel(monde)
        biberon = _ligne(monde["lyon"].get(url), "Chauffe-biberon")["id"]
        monde["lyon"].post(url + "engager/", {"besoin": biberon, "quantite": 1}, format="json")
        EngagementDon.objects.update(expire_le=timezone.now() - datetime.timedelta(hours=1))          # huit jours ont passé

        vu = monde["lille"].get(url)

        assert _ligne(vu, "Chauffe-biberon")["reste"] == 1 and EngagementDon.objects.get().statut == "RELACHE"
        assert monde["lille"].post(url + "engager/", {"besoin": biberon, "quantite": 1}, format="json").status_code == 201

    def test_renoncer_rend_la_part_tant_que_rien_nest_parti(self, monde):
        _foyer(monde)
        url = _appel(monde)
        tshirt = _ligne(monde["lyon"].get(url), "T-shirt")["id"]
        engagement = _ligne(monde["lyon"].post(url + "engager/", {"besoin": tshirt, "quantite": 4}, format="json"), "T-shirt")["engagements"][0]["id"]

        assert monde["lille"].post(url + "annuler-engagement/", {"engagement": engagement}, format="json").status_code == 400   # pas le sien
        rendu = monde["lyon"].post(url + "annuler-engagement/", {"engagement": engagement}, format="json")

        assert rendu.status_code == 200 and _ligne(rendu, "T-shirt")["reste"] == 4


@pytest.mark.django_db
class TestEnvoiReceptionRemise:
    def test_de_la_promesse_au_foyer_en_passant_par_le_stock(self, monde):
        foyer = _foyer(monde).data
        url = _appel(monde)
        tshirt = _ligne(monde["lyon"].get(url), "T-shirt")["id"]
        engage = monde["lyon"].post(url + "engager/", {"besoin": tshirt, "quantite": 4}, format="json")
        engagement = _ligne(engage, "T-shirt")["engagements"][0]["id"]

        annonce = monde["lyon"].post(url + "annoncer-envoi/", {"engagements": [engagement], "date_expedition": "2026-11-20",
                                                               "transporteur": "Camion de l'association", "contact": "Paul, 0611111111"}, format="json")
        assert annonce.status_code == 201 and annonce.data["envois"][0]["statut"] == "ANNONCE"
        assert _ligne(annonce, "T-shirt")["engagements"][0]["statut"] == "EXPEDIE"
        envoi = annonce.data["envois"][0]["id"]
        assert monde["lyon"].post(url + "recevoir-envoi/", {"envoi": envoi}, format="json").status_code == 403    # seul le destinataire compte
        assert monde["lille"].get(url).data["envois"] == []                                                      # un tiers ne voit pas l'envoi

        # À l'arrivée on en compte trois sur quatre : la ligne se rouvre d'une pièce.
        recu = monde["client"].post(url + "recevoir-envoi/", {"envoi": envoi, "comptes": {engagement: 3}}, format="json")

        assert recu.status_code == 200 and recu.data["entre_en_stock"] is True and recu.data["depot_nom"] == "Local"
        ligne = _ligne(recu, "T-shirt")
        assert ligne["quantite_recue"] == 3 and ligne["reste"] == 1 and ligne["engagements"][0]["statut"] == "RECU"
        article = filtrer_chiffre(ArticleStock.objects.filter(), designation="T-shirt, homme, L").get()
        assert stocks.quantite_en_stock(article, monde["local"]) == Decimal("3")
        assert article.mouvements.get().tiers == "Secours de Lyon"
        assert monde["client"].post(url + "recevoir-envoi/", {"envoi": envoi}, format="json").status_code == 400  # déjà compté

        # Remise au foyer : sort du stock, et ne lui manque plus.
        besoin = next(b for b in foyer["besoins"] if b["designation"] == "T-shirt")["id"]
        remis = monde["client"].post(f"/api/dons/foyers/{foyer['id']}/remettre/", {"besoin": besoin, "quantite": 3, "depot": str(monde["local"].id)}, format="json")
        assert remis.status_code == 200 and next(b for b in remis.data["besoins"] if b["designation"] == "T-shirt")["quantite_remise"] == 3
        assert stocks.quantite_en_stock(article) == Decimal("0")
        # Trois sur quatre : le foyer est dépanné, pas couvert. L'appel redemande ce qui manque encore,
        # sans passer sous ce qui est déjà reçu.
        assert next(b for b in remis.data["besoins"] if b["designation"] == "T-shirt")["etat"] == "DEPANNE"
        monde["client"].post(url + "reprendre-foyers/")
        assert filtrer_chiffre(BesoinDon.objects.filter(), designation="T-shirt").get().quantite_voulue == 3

    def test_lignes_a_la_main_cloture_et_suppression(self, monde):
        _foyer(monde)
        url = _appel(monde)

        ajout = monde["client"].post(url + "lignes/", {"lignes": [
            {"famille": "ELECTROMENAGER", "designation": "Réfrigérateur", "quantite_voulue": 2, "precision": "Classe A, moins de 10 ans"}]}, format="json")
        assert _ligne(ajout, "Réfrigérateur")["quantite_voulue"] == 2 and _ligne(ajout, "Réfrigérateur")["precision"].startswith("Classe A")
        frigo = _ligne(ajout, "Réfrigérateur")["id"]
        monde["lyon"].post(url + "engager/", {"besoin": frigo, "quantite": 2}, format="json")
        # Baisser sous ce qui est promis est sans effet ; retirer la ligne est refusé.
        baisse = monde["client"].post(url + "lignes/", {"lignes": [{"famille": "ELECTROMENAGER", "designation": "Réfrigérateur", "quantite_voulue": 1}]}, format="json")
        assert _ligne(baisse, "Réfrigérateur")["quantite_voulue"] == 2
        assert monde["client"].post(url + "lignes/", {"lignes": [{"famille": "ELECTROMENAGER", "designation": "Réfrigérateur", "quantite_voulue": 0}]}, format="json").status_code == 400
        assert monde["lyon"].post(url + "lignes/", {"lignes": []}, format="json").status_code == 403
        assert monde["client"].delete(url).status_code == 400                           # ouvert : se clôt, ne se supprime pas

        clos = monde["client"].post(url + "clore/")
        assert clos.data["statut"] == "CLOS" and EngagementDon.objects.get().statut == "ANNULE"
        assert monde["lille"].get(url).status_code == 404                               # plus visible de qui ne s'y était pas engagé
        assert monde["lyon"].get(url).status_code == 200 and AppelAuxDons.objects.count() == 1 and FoyerSinistre.objects.count() == 1


@pytest.mark.django_db
class TestRemiseSouple:
    """Remettre n'est pas couvrir : trois T-shirts dépannent quelques jours."""

    def _etat(self, monde, foyer, besoin, quantite):
        reponse = monde["client"].post(f"/api/dons/foyers/{foyer}/remettre/", {"besoin": besoin, "quantite": quantite}, format="json")
        assert reponse.status_code == 200, reponse.data
        return next(b for b in reponse.data["besoins"] if b["id"] == besoin)

    def test_a_couvrir_puis_depanne_puis_couvert_et_meme_au_dela(self, monde):
        foyer = monde["client"].post("/api/dons/foyers/", {"nom": "Famille Roux", "besoins": [
            {"famille": "VETEMENTS", "designation": "T-shirt", "public": "HOMME", "taille": "L", "quantite": 7, "quantite_urgence": 3}]}, format="json").data
        besoin = foyer["besoins"][0]
        assert besoin["etat"] == "A_COUVRIR" and besoin["quantite_urgence"] == 3

        assert self._etat(monde, foyer["id"], besoin["id"], 2)["etat"] == "A_COUVRIR"      # pas encore de quoi tenir
        assert self._etat(monde, foyer["id"], besoin["id"], 1)["etat"] == "DEPANNE"        # trois : quelques jours
        assert self._etat(monde, foyer["id"], besoin["id"], 4)["etat"] == "COUVERT"
        au_dela = self._etat(monde, foyer["id"], besoin["id"], 2)                           # le besoin était sous-estimé
        assert au_dela["quantite_remise"] == 9 and au_dela["quantite"] == 9 and au_dela["etat"] == "COUVERT"

    def test_lurgence_se_propose_a_la_moitie_et_remonte_dans_lappel(self, monde):
        _foyer(monde)                                                                        # 4 T-shirts, urgence proposée : 2
        url = _appel(monde)

        tshirt = _ligne(monde["lyon"].get(url), "T-shirt")

        assert tshirt["quantite_urgente"] == 2 and tshirt["urgent"] is True


@pytest.mark.django_db
class TestFormulationEtMotPersonnel:
    def test_un_besoin_se_dit_pour_des_personnes_pas_en_pieces(self, monde):
        for nom in ("Famille Martin", "Famille Petit", "Famille Roux"):
            monde["client"].post("/api/dons/foyers/", {"nom": nom, "crise": str(monde["crise"].id), "besoins": [
                {"famille": "VETEMENTS", "designation": "T-shirt", "public": "HOMME", "taille": "L", "quantite": 4},
                {"famille": "ELECTROMENAGER", "designation": "Réfrigérateur", "quantite": 1}]}, format="json")
        url = _appel(monde)

        vu = monde["lyon"].get(url)

        tshirt, frigo = _ligne(vu, "T-shirt"), _ligne(vu, "Réfrigérateur")
        assert tshirt["nb_beneficiaires"] == 3 and tshirt["quantite_voulue"] == 12
        assert tshirt["formulation"] == "T-shirt, taille L — pour 3 hommes (12 pièces)"
        assert frigo["formulation"] == "Réfrigérateur — pour 3 foyers"

    def test_deux_personnes_du_meme_foyer_comptent_pour_deux(self, monde):
        ligne = {"famille": "VETEMENTS", "designation": "Pull, sweat", "public": "GARCON", "taille": "8 ans", "quantite": 2}
        foyer = monde["client"].post("/api/dons/foyers/", {"nom": "Jumeaux", "crise": str(monde["crise"].id), "besoins": [ligne, ligne]}, format="json")
        assert len(foyer.data["besoins"]) == 2
        url = _appel(monde)

        assert _ligne(monde["lyon"].get(url), "Pull, sweat")["formulation"] == "Pull, sweat, taille 8 ans — pour 2 garçons (4 pièces)"

    def test_un_mot_personnel_garde_sa_ligne_et_se_lit_dans_lappel(self, monde):
        monde["client"].post("/api/dons/foyers/", {"nom": "Famille Martin", "crise": str(monde["crise"].id), "besoins": [
            {"famille": "LOISIRS", "designation": "Vélo", "public": "FILLE", "quantite": 1, "message": "Elle avait un vélo rose, avec un panier."},
            {"famille": "LOISIRS", "designation": "Vélo", "public": "FILLE", "quantite": 1},
            {"famille": "LOISIRS", "designation": "Cartes à collectionner, figurines", "public": "GARCON", "quantite": 1, "message": "Ses cartes Pokémon."}]}, format="json")
        url = _appel(monde)

        velos = [l for l in monde["lyon"].get(url).data["besoins"] if l["designation"] == "Vélo"]

        assert len(velos) == 2 and sorted(v["message"] for v in velos) == ["", "Elle avait un vélo rose, avec un panier."]
        familles = {f["famille"] for f in monde["client"].get("/api/dons/catalogue/").data["familles"]}
        assert {"OUTILLAGE", "LOISIRS", "ANIMAUX"} <= familles


@pytest.mark.django_db
class TestAvisPublics:
    def test_tout_le_monde_lit_le_besoin_sans_contact_ni_lieu_ni_donateur(self, monde):
        from rest_framework.test import APIClient

        monde["client"].post("/api/dons/foyers/", {"nom": "Famille Martin", "crise": str(monde["crise"].id), "besoins": [
            {"famille": "LOISIRS", "designation": "Vélo", "public": "FILLE", "quantite": 1, "message": "Elle avait un vélo rose."},
            {"famille": "PUERICULTURE", "designation": "Chauffe-biberon", "public": "BEBE", "quantite": 1}]}, format="json")
        url = _appel(monde)
        monde["client"].patch(url, {"livraison_adresse": "2 rue du Port", "contact_telephone": "0600000000"}, format="json")
        biberon = _ligne(monde["lyon"].get(url), "Chauffe-biberon")["id"]
        monde["lyon"].post(url + "engager/", {"besoin": biberon, "quantite": 1}, format="json")

        public = APIClient().get("/api/dons/avis/")

        assert public.status_code == 200 and "rejoint le réseau gratuitement" in public.data["comment_aider"]
        avis = public.data["avis"][0]
        assert avis["titre"] == "Familles sinistrées du feu" and avis["pieces_restantes"] == 1
        velo = next(l for l in avis["lignes"] if l["formulation"].startswith("Vélo"))
        assert velo["message"] == "Elle avait un vélo rose." and velo["formulation"] == "Vélo — pour 1 fille" and velo["couvert"] is False
        assert next(l for l in avis["lignes"] if l["formulation"].startswith("Chauffe-biberon"))["couvert"] is True
        texte = str(public.data)
        assert "rue du Port" not in texte and "0600000000" not in texte and "Lyon" not in texte and "Martin" not in texte
        # Un brouillon ou un appel clos n'est pas un avis.
        monde["client"].post(url + "clore/")
        assert APIClient().get("/api/dons/avis/").data["avis"] == []


@pytest.mark.django_db
class TestCourrielsEtNotifications:
    def test_chaque_etape_previent_la_bonne_personne(self, monde, mailoutbox):
        from core.models import Notification

        monde["client"].post("/api/dons/foyers/", {"nom": "Famille Martin", "crise": str(monde["crise"].id), "besoins": [
            {"famille": "VETEMENTS", "designation": "T-shirt", "public": "HOMME", "taille": "L", "quantite": 4}]}, format="json")
        url = _appel(monde)
        monde["client"].patch(url, {"contact_email": "dons@mairie.test"}, format="json")
        tshirt = _ligne(monde["lyon"].get(url), "T-shirt")["id"]
        mailoutbox.clear()

        engage = monde["lyon"].post(url + "engager/", {"besoin": tshirt, "quantite": 4}, format="json")
        # L'auteur de l'appel et son adresse de contact sont prévenus de l'engagement.
        assert filtrer_chiffre(filtrer_chiffre(Notification.objects.filter(), utilisateur__username="magasinier@test.fr"), titre__contains="Secours de Lyon s'engage").exists()
        destinataires = {a for m in mailoutbox for a in m.to}
        assert {"dons@mairie.test", "magasinier@test.fr"} <= destinataires and "lyon-dons@test.fr" not in destinataires
        assert "4 pièce(s)" in mailoutbox[-1].body and "/admin/appels-dons" in mailoutbox[-1].body

        engagement = _ligne(engage, "T-shirt")["engagements"][0]["id"]
        mailoutbox.clear()
        annonce = monde["lyon"].post(url + "annoncer-envoi/", {"engagements": [engagement], "date_expedition": "2026-11-20"}, format="json")
        assert "Un envoi part" in mailoutbox[-1].subject and "20/11/2026" in mailoutbox[-1].body

        mailoutbox.clear()
        monde["client"].post(url + "recevoir-envoi/", {"envoi": annonce.data["envois"][0]["id"], "comptes": {engagement: 3}}, format="json")
        # Le donateur apprend que c'est arrivé, et l'écart.
        assert filtrer_chiffre(filtrer_chiffre(Notification.objects.filter(), utilisateur__username="lyon-dons@test.fr"), titre__contains="est bien arrivé").exists()
        assert mailoutbox[-1].to == ["lyon-dons@test.fr"] and "(annoncé : 4)" in mailoutbox[-1].body

    def test_le_rappel_part_une_fois_puis_lengagement_en_retard_est_relache(self, monde, mailoutbox):
        from django.core.management import call_command

        _foyer(monde)
        url = _appel(monde)
        biberon = _ligne(monde["lyon"].get(url), "Chauffe-biberon")["id"]
        monde["lyon"].post(url + "engager/", {"besoin": biberon, "quantite": 1}, format="json")
        mailoutbox.clear()

        EngagementDon.objects.update(expire_le=timezone.now() + datetime.timedelta(days=1))           # il reste un jour
        call_command("rappeler_engagements_dons")
        call_command("rappeler_engagements_dons")
        assert [m.to for m in mailoutbox] == [["lyon-dons@test.fr"]] and "attend son envoi" in mailoutbox[0].subject

        EngagementDon.objects.update(expire_le=timezone.now() - datetime.timedelta(hours=1))
        call_command("rappeler_engagements_dons")
        assert EngagementDon.objects.get().statut == "RELACHE" and "a été rendu aux autres" in mailoutbox[-1].subject
        assert _ligne(monde["lille"].get(url), "Chauffe-biberon")["reste"] == 1


@pytest.mark.django_db
class TestPerimetre:
    """Un appel se lance d'abord près du sinistre, puis s'élargit si le besoin n'est pas couvert."""

    @pytest.fixture
    def carte(self, monde):
        from core.models import Commune
        # La crise est près d'Arcachon ; Bordeaux est à ~50 km, Lille à ~700 km.
        Commune.objects.update_or_create(code="69123", defaults={"nom": "Bordeaux (essai)", "centre_latitude": 44.84, "centre_longitude": -0.58})
        Commune.objects.update_or_create(code="59350", defaults={"nom": "Lille", "centre_latitude": 50.63, "centre_longitude": 3.06})
        _foyer(monde)
        url = _appel(monde, ouvrir=False)
        return {**monde, "url": url}

    def test_un_appel_a_100_km_ne_sadresse_pas_a_une_institution_lointaine(self, carte):
        pose = carte["client"].patch(carte["url"], {"portee_km": 100}, format="json")
        assert pose.status_code == 200 and pose.data["portee"] == "dans un rayon de 100 km"
        carte["client"].post(carte["url"] + "ouvrir/")

        pres, loin = carte["lyon"].get(carte["url"]), carte["lille"].get(carte["url"])

        assert pres.status_code == 200 and 30 < pres.data["distance_km"] < 70
        assert loin.status_code == 404 and carte["lille"].get("/api/dons/appels/", {"autres": 1}).data == []
        biberon = _ligne(pres, "Chauffe-biberon")["id"]
        assert carte["lille"].post(carte["url"] + "engager/", {"besoin": biberon, "quantite": 1}, format="json").status_code == 404

    def test_elargir_la_portee_ouvre_lappel_aux_suivants(self, carte):
        carte["client"].patch(carte["url"], {"portee_km": 50}, format="json")
        carte["client"].post(carte["url"] + "ouvrir/")
        assert carte["lille"].get(carte["url"]).status_code == 404

        elargi = carte["client"].patch(carte["url"], {"portee_km": None}, format="json")           # toute la France

        assert elargi.data["portee"] == "dans toute la France" and carte["lille"].get(carte["url"]).status_code == 200
        assert carte["client"].patch(carte["url"], {"portee_km": 75}, format="json").status_code == 400    # portée hors grille

    def test_lavis_public_dit_la_portee_et_une_institution_non_situee_nest_pas_ecartee(self, carte, create_user):
        from rest_framework.test import APIClient
        carte["client"].patch(carte["url"], {"portee_km": 200}, format="json")
        carte["client"].post(carte["url"] + "ouvrir/")

        avis = APIClient().get("/api/dons/avis/").data["avis"][0]
        assert avis["portee_km"] == 200 and avis["portee"] == "dans un rayon de 200 km" and avis["latitude"] == 44.63

        _nulle_part, _c, client = _institution(create_user, "Association sans commune connue", "sans-commune", "00000")
        assert client.get(carte["url"]).status_code == 200 and client.get(carte["url"]).data["distance_km"] is None


@pytest.mark.django_db
class TestReseauPrevenu:
    def test_les_institutions_du_perimetre_sont_prevenues_une_fois_et_les_suivantes_a_lelargissement(self, monde, mailoutbox, reseau_prevenu):
        from core import notifications_dons
        from core.models import Commune, ContactInstitution, Notification

        Commune.objects.update_or_create(code="69123", defaults={"nom": "Bordeaux (essai)", "centre_latitude": 44.84, "centre_longitude": -0.58})
        Commune.objects.update_or_create(code="59350", defaults={"nom": "Lille", "centre_latitude": 50.63, "centre_longitude": 3.06})
        filtrer_chiffre(ContactInstitution.objects.filter(), utilisateur__username="lyon-dons@test.fr").update(contact_principal=True)
        filtrer_chiffre(ContactInstitution.objects.filter(), utilisateur__username="lille-dons@test.fr").update(membre_bureau=True)
        _foyer(monde)
        url = _appel(monde, ouvrir=False)
        monde["client"].patch(url, {"portee_km": 100}, format="json")
        appel = AppelAuxDons.objects.get()
        assert notifications_dons.prevenir_le_reseau(appel) == {"institutions": 0, "personnes": 0}      # un brouillon ne prévient personne
        monde["client"].post(url + "ouvrir/")
        assert reseau_prevenu == [str(appel.id)]                                                         # l'ouverture lance la tâche de fond
        mailoutbox.clear()
        appel.refresh_from_db()

        premier = notifications_dons.prevenir_le_reseau(appel)
        encore = notifications_dons.prevenir_le_reseau(appel)

        assert premier == {"institutions": 1, "personnes": 1} and encore["institutions"] == 0
        assert [m.to for m in mailoutbox] == [["lyon-dons@test.fr"]]                                   # à portée ; Lille est trop loin
        assert "dans un rayon de 100 km" in mailoutbox[0].body and "km de vous" in mailoutbox[0].body
        assert filtrer_chiffre(filtrer_chiffre(Notification.objects.filter(), utilisateur__username="lyon-dons@test.fr"), titre__contains="Appel aux dons de Réserve des essais").exists()
        assert not filtrer_chiffre(filtrer_chiffre(Notification.objects.filter(), utilisateur__username="magasinier@test.fr"), titre__contains="Appel aux dons de").exists()

        # On élargit à toute la France : seule Lille, nouvelle venue, est prévenue.
        monde["client"].patch(url, {"portee_km": None}, format="json")
        assert reseau_prevenu == [str(appel.id)] * 2                                                      # l'élargissement aussi
        appel.refresh_from_db()
        mailoutbox.clear()
        suite = notifications_dons.prevenir_le_reseau(appel)
        assert suite["institutions"] >= 1 and ["lille-dons@test.fr"] in [m.to for m in mailoutbox]
        assert ["lyon-dons@test.fr"] not in [m.to for m in mailoutbox]
        assert "institutions_prevenues" not in monde["lyon"].get(url).data                                # ne se lit pas de l'extérieur
