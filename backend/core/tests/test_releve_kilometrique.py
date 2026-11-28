"""Relevé kilométrique des bénévoles (28/11/2026) : trajet, motif, véhicule déclaré, compteurs,
péages et stationnement avec leur ticket, tarif par puissance, relevé imprimable."""
import datetime
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from core import benevolat
from core.models import EngagementPersonnel, FraisDeplacement, Manifestation, VehiculePersonnel
from core.tests.test_manifestations_benevolat import _client, asso  # noqa: F401  (fixture)


def _png():
    from PIL import Image
    tampon = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(tampon, "PNG")
    return SimpleUploadedFile("ticket-peage.png", tampon.getvalue(), content_type="image/png")


def _manifestation(asso, jours=2):
    debut = timezone.now() - datetime.timedelta(days=jours)
    return Manifestation.objects.create(institution=asso["fcba"], titre="Exercice radio", statut="PUBLIEE",
                                        commune_code="", debut=debut, fin=debut + datetime.timedelta(hours=6))


def _ligne(asso, valide=False, **champs):
    m = _manifestation(asso)
    parti = timezone.now() - datetime.timedelta(days=2)
    return EngagementPersonnel.objects.create(
        utilisateur=asso["lea_user"], manifestation=m, institution=asso["fcba"], parti_le=parti,
        rentre_le=parti + datetime.timedelta(hours=4), valide_le=timezone.now() if valide else None,
        valide_par=asso["bureau_user"] if valide else None, **champs)


def _vehicule(asso, cv="5", genre="VOITURE"):
    r = asso["lea"].post(reverse("mes_vehicules"), {"genre": genre, "libelle": "Clio grise",
                                                    "immatriculation": "ab-123-cd", "puissance_cv": cv}, format="json")
    assert r.status_code == 201, r.data
    return r.data


@pytest.mark.django_db
class TestVehicules:
    def test_declarer_modifier_retirer(self, asso):
        v = _vehicule(asso)
        assert v["immatriculation"] == "AB-123-CD" and v["puissance_cv"] == 5
        assert v["designation"] == "Clio grise · AB-123-CD · 5 CV"
        assert asso["lea"].patch(reverse("mon_vehicule", args=[v["id"]]), {"puissance_cv": "6"}, format="json").data["puissance_cv"] == 6
        # Un véhicule qui a servi est retiré, pas supprimé : il reste sur la ligne.
        ligne = _ligne(asso, vehicule_personnel_id=v["id"], kilometres="10", vehicule="VOITURE")
        assert asso["lea"].delete(reverse("mon_vehicule", args=[v["id"]])).status_code == 204
        assert asso["lea"].get(reverse("mes_vehicules")).data == []
        ligne.refresh_from_db()
        assert ligne.vehicule_personnel is not None and ligne.vehicule_personnel.actif is False

    def test_rien_en_clair_et_pas_le_vehicule_d_un_autre(self, asso):
        v = _vehicule(asso)
        with connection.cursor() as c:
            c.execute("SELECT libelle, immatriculation, puissance_cv FROM core_vehiculepersonnel")
            libelle, immat, cv = c.fetchone()
        assert "Clio" not in libelle and "AB-123" not in immat and cv != "5"
        assert asso["max"].patch(reverse("mon_vehicule", args=[v["id"]]), {"libelle": "x"}, format="json").status_code == 404
        ligne = EngagementPersonnel.objects.create(
            utilisateur=asso["max"].handler._force_user, manifestation=_manifestation(asso),
            institution=asso["fcba"], parti_le=timezone.now() - datetime.timedelta(hours=5),
            rentre_le=timezone.now() - datetime.timedelta(hours=1))
        r = asso["max"].patch(reverse("mon_releve_ligne", args=[ligne.id]), {"vehicule_personnel": v["id"]}, format="json")
        assert r.status_code == 400 and "vôtres" in r.data["detail"]


@pytest.mark.django_db
class TestDeplacement:
    def test_les_compteurs_font_les_kilometres(self, asso):
        v = _vehicule(asso)
        ligne = _ligne(asso)
        r = asso["lea"].patch(reverse("mon_releve_ligne", args=[ligne.id]), {
            "vehicule_personnel": v["id"], "compteur_depart": "45 210", "compteur_arrivee": "45262", "kilometres": "999",
            "lieu_depart": "Domicile", "lieu_arrivee": "Floirac", "motif": "Balisage radio", "aller_retour": False,
        }, format="json")
        assert r.status_code == 200, r.data
        assert r.data["kilometres"] == "52" and r.data["vehicule"] == "VOITURE" and r.data["aller_retour"] is False
        assert r.data["vehicule_designation"].startswith("Clio grise")
        # Ajouter son trajet ne fait pas passer les heures pour « complétées à la main ».
        assert r.data["saisie_manuelle"] is False
        with connection.cursor() as c:
            c.execute("SELECT motif, lieu_arrivee, compteur_depart FROM core_engagementpersonnel WHERE id = %s", [ligne.id])
            motif, arrivee, compteur = c.fetchone()
        assert "Balisage" not in motif and "Floirac" not in arrivee and "45210" not in compteur

    def test_compteur_d_arrivee_plus_petit_refuse(self, asso):
        ligne = _ligne(asso)
        r = asso["lea"].patch(reverse("mon_releve_ligne", args=[ligne.id]),
                              {"compteur_depart": "1000", "compteur_arrivee": "900"}, format="json")
        assert r.status_code == 400 and "plus petit" in r.data["detail"]
        r = asso["lea"].patch(reverse("mon_releve_ligne", args=[ligne.id]), {"compteur_depart": "12a"}, format="json")
        assert r.status_code == 400

    def test_je_rentre_avec_kilometres_et_peage(self, asso):
        v = _vehicule(asso)
        ouvert = EngagementPersonnel.objects.create(utilisateur=asso["lea_user"], manifestation=_manifestation(asso, 0),
                                                    institution=asso["fcba"], parti_le=timezone.now() - datetime.timedelta(hours=3),
                                                    vehicule_personnel_id=v["id"], compteur_depart="1000")
        etat = asso["lea"].get(reverse("mon_engagement")).data
        assert etat["en_cours"]["compteur_depart"] == "1000" and etat["en_cours"]["motif_propose"] == "Exercice radio"
        assert [x["id"] for x in etat["vehicules"]] == [v["id"]]
        r = asso["lea"].post(reverse("mon_engagement"), {"geste": "rentrer", "compteur_arrivee": "1046",
                                                         "peage": "3,40", "stationnement": ""}, format="json")
        assert r.status_code == 200, r.data
        assert r.data["ligne_rentree"] == str(ouvert.id) and r.data["en_cours"] is None
        ouvert.refresh_from_db()
        assert ouvert.rentre_le is not None and ouvert.kilometres == "46"
        assert ouvert.motif == "Exercice radio" and ouvert.lieu_depart == "Domicile"
        assert [(f.nature, f.montant) for f in ouvert.frais.all()] == [("PEAGE", "3.40")]

    def test_un_compteur_faux_ne_laisse_pas_un_retour_a_moitie(self, asso):
        ouvert = EngagementPersonnel.objects.create(utilisateur=asso["lea_user"], manifestation=_manifestation(asso, 0),
                                                    institution=asso["fcba"], parti_le=timezone.now() - datetime.timedelta(hours=3),
                                                    compteur_depart="1000")
        r = asso["lea"].post(reverse("mon_engagement"), {"geste": "rentrer", "compteur_arrivee": "10"}, format="json")
        assert r.status_code == 400
        ouvert.refresh_from_db()
        assert ouvert.rentre_le is None


@pytest.mark.django_db
class TestFrais:
    def test_ticket_ajoute_puis_lu_par_qui_a_le_droit(self, asso, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        ligne = _ligne(asso, kilometres="20", vehicule="VOITURE")
        r = asso["lea"].post(reverse("mon_releve_frais", args=[ligne.id]),
                             {"nature": "PEAGE", "montant": "4,50", "fichier": _png()}, format="multipart")
        assert r.status_code == 201, r.data
        assert r.data["montant"] == "4.50" and r.data["justificatif"] is True
        url = reverse("frais_justificatif", args=[r.data["id"]])
        assert asso["lea"].get(url).status_code == 200
        assert asso["bureau"].get(url).status_code == 200           # bureau de l'association
        assert asso["max"].get(url).status_code == 404               # simple membre
        assert asso["intrus"].get(url).status_code == 404
        # Le fichier est chiffré au repos.
        chemin = FraisDeplacement.objects.get().justificatif.path
        with open(chemin, "rb") as f:
            assert not f.read().startswith(b"\x89PNG")

    def test_autre_justificatif_photo_obligatoire_sans_montant(self, asso, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        ligne = _ligne(asso, kilometres="20", vehicule="VOITURE")
        url = reverse("mon_releve_frais", args=[ligne.id])
        r = asso["lea"].post(url, {"nature": "AUTRE"}, format="multipart")
        assert r.status_code == 400 and "photo" in r.data["detail"]
        r = asso["lea"].post(url, {"nature": "AUTRE", "montant": "99", "fichier": _png()}, format="multipart")
        assert r.status_code == 201, r.data
        assert r.data["nature_libelle"] == "Autre justificatif" and r.data["montant"] == "0" and r.data["justificatif"] is True
        # Il ne compte dans aucun frais.
        assert benevolat.frais_annexes_ligne(EngagementPersonnel.objects.get(id=ligne.id)) == Decimal("0.00")

    def test_rien_sur_une_ligne_validee(self, asso):
        ligne = _ligne(asso, valide=True, kilometres="20", vehicule="VOITURE")
        r = asso["lea"].post(reverse("mon_releve_frais", args=[ligne.id]), {"nature": "STATIONNEMENT", "montant": "2"},
                             format="multipart")
        assert r.status_code == 400 and "validée" in r.data["detail"]

    def test_montant_absurde_refuse(self, asso):
        ligne = _ligne(asso)
        r = asso["lea"].post(reverse("mon_releve_frais", args=[ligne.id]), {"nature": "PEAGE", "montant": "5000"},
                             format="multipart")
        assert r.status_code == 400


@pytest.mark.django_db
class TestTarifsEtRecu:
    def _reglages(self, asso, **plus):
        corps = {"institution": str(asso["fcba"].id), "annee": timezone.localdate().year, "tarif_km_voiture": "0.4",
                 "tarifs_km_puissance": {"3": "0.529", "5": "0.636", "7": "0.697"}}
        corps.update(plus)
        r = asso["bureau"].put(reverse("benevolat_reglages"), corps, format="json")
        assert r.status_code == 200, r.data
        return r

    def test_tarif_par_puissance_et_repli(self, asso):
        self._reglages(asso)
        v5 = VehiculePersonnel.objects.create(utilisateur=asso["lea_user"], libelle="A", puissance_cv="5")
        v4 = VehiculePersonnel.objects.create(utilisateur=asso["lea_user"], libelle="B", puissance_cv="4")
        v9 = VehiculePersonnel.objects.create(utilisateur=asso["lea_user"], libelle="C", puissance_cv="9")
        r = benevolat.reglages(asso["fcba"], timezone.localdate().year, "PROD")
        ligne = EngagementPersonnel(vehicule="VOITURE", kilometres="100")
        for vp, attendu in ((v5, "63.60"), (v4, "40.00"), (v9, "69.70"), (None, "40.00")):
            ligne.vehicule_personnel = vp
            assert benevolat.frais_km_ligne(ligne, r) == Decimal(attendu)

    def test_peages_et_stationnement_dans_l_abandon_et_le_recu(self, asso):
        ligne = _ligne(asso, valide=True, kilometres="100", vehicule="VOITURE")
        FraisDeplacement.objects.create(engagement=ligne, nature="PEAGE", montant="6.20")
        FraisDeplacement.objects.create(engagement=ligne, nature="STATIONNEMENT", montant="3.00")
        self._reglages(asso, recus_fiscaux=True, signataire_nom="Paul Bureau")
        annee = timezone.localdate().year
        d = asso["bureau"].get(reverse("benevolat"), {"institution": str(asso["fcba"].id), "annee": annee}).data
        assert d["frais"] == Decimal("49.20") and d["frais_annexes"] == Decimal("9.20")
        abandon = asso["lea"].post(reverse("mon_abandon"), {"institution": str(asso["fcba"].id), "annee": annee,
                                                            "adresse": "3 allée des Pins"}, format="json").data
        assert abandon["montant"] == "49.20"
        accepte = asso["treso"].post(reverse("benevolat_abandon", args=[abandon["id"]]), {"geste": "accepter"}, format="json")
        assert accepte.status_code == 200, accepte.data
        pdf = asso["lea"].get(reverse("benevolat_recu", args=[abandon["id"]]))
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    def test_export_porte_le_trajet(self, asso):
        _ligne(asso, valide=True, kilometres="30", vehicule="VOITURE", motif="Balisage", lieu_depart="Domicile",
               lieu_arrivee="Floirac", compteur_depart="100", compteur_arrivee="130")
        self._reglages(asso)
        export = asso["bureau"].get(reverse("benevolat_export"), {"institution": str(asso["fcba"].id),
                                                                  "annee": timezone.localdate().year, "fichier": "csv"})
        texte = export.content.decode("utf-8-sig")
        entete, rang = texte.splitlines()[:2]
        assert "Trajet" in entete and "Compteur départ" in entete and "Péages (€)" in entete
        assert "Domicile → Floirac" in rang and "Balisage" in rang


@pytest.mark.django_db
class TestReleveImprimable:
    def test_mon_releve_et_celui_du_bureau(self, asso):
        v = VehiculePersonnel.objects.create(utilisateur=asso["lea_user"], libelle="Clio", immatriculation="AB-123-CD", puissance_cv="5")
        _ligne(asso, valide=True, kilometres="30", vehicule="VOITURE", vehicule_personnel=v)
        _ligne(asso, kilometres="12", vehicule="VOITURE")
        aujourdhui = timezone.localdate()
        r = asso["lea"].get(reverse("mon_releve_km"), {"institution": str(asso["fcba"].id),
                                                      "du": str(aujourdhui - datetime.timedelta(days=10)), "au": str(aujourdhui)})
        assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and r.content[:4] == b"%PDF"
        assert len(benevolat.lignes_de_deplacement(asso["fcba"], "PROD", asso["lea_user"], aujourdhui - datetime.timedelta(days=10),
                                                   aujourdhui, validees_seulement=False)) == 2
        b = asso["bureau"].get(reverse("benevolat_releve_km"), {"institution": str(asso["fcba"].id),
                                                               "utilisateur": str(asso["lea_user"].id), "annee": aujourdhui.year})
        assert b.status_code == 200 and b.content[:4] == b"%PDF"
        # Un simple membre ne tire pas le relevé d'un autre ; un intrus pas le sien chez nous.
        assert asso["max"].get(reverse("benevolat_releve_km"), {"institution": str(asso["fcba"].id),
                                                               "utilisateur": str(asso["lea_user"].id)}).status_code == 403
        assert asso["intrus"].get(reverse("mon_releve_km"), {"institution": str(asso["fcba"].id)}).status_code == 400

    def test_beaucoup_de_lignes_plusieurs_pages(self, asso):
        m = _manifestation(asso, 30)
        for n in range(60):
            parti = timezone.now() - datetime.timedelta(days=28, hours=-n * 5)
            EngagementPersonnel.objects.create(utilisateur=asso["lea_user"], manifestation=m, institution=asso["fcba"],
                                               parti_le=parti, rentre_le=parti + datetime.timedelta(hours=2),
                                               kilometres="10", vehicule="VOITURE", valide_le=timezone.now())
        pdf = benevolat.releve_km_pdf(asso["lea_user"], asso["fcba"], "PROD", timezone.localdate() - datetime.timedelta(days=40),
                                      timezone.localdate())
        import re
        assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) >= 2
