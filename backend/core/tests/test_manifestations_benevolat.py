"""Manifestations d'association, relevé d'heures étendu, valorisation et abandon de frais
(26/11/2026, après l'annonce de FCBA 33)."""
import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import benevolat
from core.models import (
    AbandonFrais, ContactInstitution, EngagementPersonnel, InscriptionPoste, Institution, InstitutionType,
    Manifestation, Notification,
)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def asso(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
    fcba = Institution.objects.create(nom="Radio-club d'essai", type=itype, adresse="1 rue des Ondes",
                                      commune_nom="Floirac", commune_code_postal="33270")
    bureau = create_user(username="bureau@essai.fr", email="bureau@essai.fr", type="VOLUNTEER", first_name="Paul", last_name="Bureau")
    tresorier = create_user(username="treso@essai.fr", email="treso@essai.fr", type="VOLUNTEER")
    lea = create_user(username="lea@essai.fr", email="lea@essai.fr", type="VOLUNTEER", first_name="Léa", last_name="Martin")
    max_ = create_user(username="max@essai.fr", email="max@essai.fr", type="VOLUNTEER")
    intrus = create_user(username="intrus@essai.fr", email="intrus@essai.fr", type="VOLUNTEER")
    ContactInstitution.objects.create(institution=fcba, utilisateur=bureau, actif=True, membre_bureau=True)
    ContactInstitution.objects.create(institution=fcba, utilisateur=tresorier, actif=True, membre_bureau=True)
    ContactInstitution.objects.create(institution=fcba, utilisateur=lea, actif=True)
    ContactInstitution.objects.create(institution=fcba, utilisateur=max_, actif=True)
    return {"fcba": fcba, "bureau": _client(bureau), "treso": _client(tresorier), "lea": _client(lea), "max": _client(max_),
            "intrus": _client(intrus), "lea_user": lea, "bureau_user": bureau}


def _iso(dt):
    return dt.isoformat()


def _creer(asso, debut=None, places=1):
    debut = debut or timezone.now() + datetime.timedelta(days=3)
    reponse = asso["bureau"].post(reverse("manifestations"), {
        "institution": str(asso["fcba"].id), "type": "SIGNALISATION_RADIO", "titre": "Course des 10 km",
        "lieu": "Parc du Castel", "organisateur": "Mairie", "consignes": "Gilet et radio chargée",
        "debut": _iso(debut), "fin": _iso(debut + datetime.timedelta(hours=4)),
        "postes": [{"intitule": "Carrefour D936", "places": places}],
    }, format="json")
    assert reponse.status_code == 201, reponse.data
    return reponse.data


@pytest.mark.django_db
class TestManifestations:
    def test_brouillon_invisible_puis_publication_previent_les_membres(self, asso):
        m = _creer(asso)
        assert asso["lea"].get(reverse("manifestations")).data["manifestations"] == []
        avant = Notification.objects.count()
        assert asso["bureau"].post(reverse("manifestation_geste", args=[m["id"]]), {"geste": "publier"}, format="json").status_code == 200
        assert Notification.objects.count() > avant
        assert [x["titre"] for x in asso["lea"].get(reverse("manifestations")).data["manifestations"]] == ["Course des 10 km"]
        assert asso["intrus"].get(reverse("manifestations")).data["manifestations"] == []

    def test_seul_le_bureau_cree_et_publie(self, asso):
        reponse = asso["lea"].post(reverse("manifestations"), {"institution": str(asso["fcba"].id), "titre": "x",
                                                               "debut": _iso(timezone.now()), "fin": _iso(timezone.now() + datetime.timedelta(hours=1))}, format="json")
        assert reponse.status_code == 403

    def test_liste_d_attente_et_montee_au_desistement(self, asso):
        m = _creer(asso, places=1)
        asso["bureau"].post(reverse("manifestation_geste", args=[m["id"]]), {"geste": "publier"}, format="json")
        poste = m["postes"][0]["id"]
        url = reverse("manifestation_poste", args=[poste])
        assert asso["lea"].post(url, {"geste": "inscrire"}, format="json").data["postes"][0]["mon_statut"] == "INSCRIT"
        d = asso["max"].post(url, {"geste": "inscrire"}, format="json").data["postes"][0]
        assert d["mon_statut"] == "LISTE_ATTENTE" and d["mon_rang_attente"] == 1
        asso["lea"].post(url, {"geste": "desister"}, format="json")
        assert asso["max"].get(reverse("manifestation", args=[m["id"]])).data["postes"][0]["mon_statut"] == "INSCRIT"
        # L'intrus ne s'inscrit pas.
        assert asso["intrus"].post(url, {"geste": "inscrire"}, format="json").status_code == 403

    def test_le_pointage_cree_une_seule_ligne_de_releve(self, asso):
        debut = timezone.now() + datetime.timedelta(days=1)
        m = _creer(asso, debut=debut)
        asso["bureau"].post(reverse("manifestation_geste", args=[m["id"]]), {"geste": "publier"}, format="json")
        asso["lea"].post(reverse("manifestation_poste", args=[m["postes"][0]["id"]]), {"geste": "inscrire"}, format="json")
        inscription = InscriptionPoste.objects.get()
        url = reverse("manifestation_pointer", args=[inscription.id])
        asso["bureau"].post(url, {"present": True}, format="json")
        asso["bureau"].post(url, {"present": True}, format="json")
        (ligne,) = EngagementPersonnel.objects.all()
        assert ligne.manifestation_id is not None and ligne.crise_id is None and ligne.source == "PLANNING"
        assert (ligne.rentre_le - ligne.parti_le) == datetime.timedelta(hours=4)
        # Absent : la ligne née du pointage disparaît.
        asso["bureau"].post(url, {"present": False}, format="json")
        assert not EngagementPersonnel.objects.exists()

    def test_calendrier_ical(self, asso):
        m = _creer(asso)
        asso["bureau"].post(reverse("manifestation_geste", args=[m["id"]]), {"geste": "publier"}, format="json")
        asso["lea"].post(reverse("manifestation_poste", args=[m["postes"][0]["id"]]), {"geste": "inscrire"}, format="json")
        contenu = asso["lea"].get(reverse("manifestations_ical")).content.decode()
        assert "BEGIN:VEVENT" in contenu and "Course des 10 km" in contenu

    def test_rien_en_clair(self, asso):
        _creer(asso)
        with connection.cursor() as c:
            c.execute("SELECT titre, lieu, consignes FROM core_manifestation")
            titre, lieu, consignes = c.fetchone()
            c.execute("SELECT intitule FROM core_postemanifestation")
            (intitule,) = c.fetchone()
        assert "Course" not in titre and "Castel" not in lieu and "Gilet" not in consignes and "D936" not in intitule


def _ligne_validee(asso, km="120", vehicule="VOITURE", heures=5):
    m = Manifestation.objects.create(institution=asso["fcba"], titre="Exercice radio", statut="PUBLIEE",
                                     debut=timezone.now() - datetime.timedelta(days=2), fin=timezone.now() - datetime.timedelta(days=2, hours=-6))
    parti = timezone.now() - datetime.timedelta(days=2)
    ligne = EngagementPersonnel.objects.create(utilisateur=asso["lea_user"], manifestation=m, institution=asso["fcba"],
                                               parti_le=parti, rentre_le=parti + datetime.timedelta(hours=heures),
                                               kilometres=km, vehicule=vehicule, valide_le=timezone.now(), valide_par=asso["bureau_user"])
    return m, ligne


@pytest.mark.django_db
class TestBenevolat:
    def test_ligne_de_manifestation_complete_a_la_main_avec_kilometres(self, asso):
        m = Manifestation.objects.create(institution=asso["fcba"], titre="Réunion", statut="PUBLIEE",
                                         debut=timezone.now() - datetime.timedelta(days=1), fin=timezone.now() - datetime.timedelta(hours=20))
        parti = timezone.now() - datetime.timedelta(days=1)
        reponse = asso["lea"].post(reverse("mon_releve"), {"manifestation": str(m.id), "parti_le": _iso(parti),
                                                           "rentre_le": _iso(parti + datetime.timedelta(hours=3)),
                                                           "kilometres": "42,5", "vehicule": "VOITURE"}, format="json")
        assert reponse.status_code == 201, reponse.data
        assert reponse.data["crise_nom"] == "Réunion" and reponse.data["kilometres"] == "42.5"
        releve = asso["lea"].get(reverse("mon_releve")).data
        assert releve["total_kilometres"] == 42.5
        # Le bureau relit cette ligne comme les autres.
        assert asso["bureau"].post(reverse("releves_equipe"), {"ligne": reponse.data["id"], "geste": "valider"}, format="json").status_code == 200
        # Validée : les kilomètres ne bougent plus.
        assert asso["lea"].patch(reverse("mon_releve_ligne", args=[reponse.data["id"]]), {"kilometres": "300"}, format="json").status_code == 400

    def test_valorisation_avec_les_taux_de_l_association(self, asso):
        _ligne_validee(asso)
        annee = timezone.localdate().year
        asso["bureau"].put(reverse("benevolat_reglages"), {"institution": str(asso["fcba"].id), "annee": annee,
                                                           "taux_horaire": "12.02", "tarif_km_voiture": "0,4"}, format="json")
        d = asso["bureau"].get(reverse("benevolat"), {"institution": str(asso["fcba"].id), "annee": annee}).data
        assert d["heures"] == Decimal("5") and d["valorisation_heures"] == Decimal("60.10") and d["frais"] == Decimal("48.00")
        assert asso["lea"].get(reverse("benevolat"), {"institution": str(asso["fcba"].id), "annee": annee}).status_code == 403
        export = asso["bureau"].get(reverse("benevolat_export"), {"institution": str(asso["fcba"].id), "annee": annee, "fichier": "xlsx"})
        assert export.status_code == 200 and export.content[:2] == b"PK"

    def test_abandon_de_frais_et_recu(self, asso):
        _ligne_validee(asso)
        annee = timezone.localdate().year
        corps = {"institution": str(asso["fcba"].id), "annee": annee, "tarif_km_voiture": "0.4"}
        asso["bureau"].put(reverse("benevolat_reglages"), corps, format="json")
        demande = {"institution": str(asso["fcba"].id), "annee": annee, "adresse": "3 allée des Pins, 33270 Floirac"}
        # Sans habilitation : refusé.
        assert asso["lea"].post(reverse("mon_abandon"), demande, format="json").status_code == 400
        asso["bureau"].put(reverse("benevolat_reglages"), dict(corps, recus_fiscaux=True, signataire_nom="Paul Bureau",
                                                                signataire_qualite="Président"), format="json")
        abandon = asso["lea"].post(reverse("mon_abandon"), demande, format="json").data
        assert abandon["montant"] == "48.00"
        accepte = asso["treso"].post(reverse("benevolat_abandon", args=[abandon["id"]]), {"geste": "accepter"}, format="json").data
        assert accepte["numero_recu"] == f"{annee}-0001"
        pdf = asso["lea"].get(reverse("benevolat_recu", args=[abandon["id"]]))
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        assert asso["max"].get(reverse("benevolat_recu", args=[abandon["id"]])).status_code == 403
        # L'adresse est chiffrée en base.
        with connection.cursor() as c:
            c.execute("SELECT detail FROM core_abandonfrais")
            assert "Pins" not in c.fetchone()[0]
        assert AbandonFrais.objects.get().statut == "RECU_EMIS"

    def test_montant_en_lettres(self):
        assert benevolat.montant_en_lettres(Decimal("48.00")) == "quarante-huit euros"
        assert benevolat.montant_en_lettres(Decimal("171.21")) == "cent soixante et onze euros et vingt et un centimes"
        assert benevolat.montant_en_lettres(Decimal("1280")) == "mille deux cent quatre-vingts euros"
        assert benevolat.montant_en_lettres(Decimal("200")) == "deux cents euros"


@pytest.mark.django_db
def test_plan_joint_a_une_manifestation(asso, settings, tmp_path):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image
    settings.MEDIA_ROOT = str(tmp_path)
    m = _creer(asso)
    tampon = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(tampon, "PNG")
    image = SimpleUploadedFile("plan.png", tampon.getvalue(), content_type="image/png")
    reponse = asso["bureau"].post(reverse("manifestation_documents", args=[m["id"]]), {"fichier": image}, format="multipart")
    assert reponse.status_code == 201, reponse.data
    (doc,) = reponse.data["documents"]
    assert doc["nom"] == "plan.png"
    # Un membre ne joint rien ; il télécharge une fois publiée.
    asso["bureau"].post(reverse("manifestation_geste", args=[m["id"]]), {"geste": "publier"}, format="json")
    assert asso["lea"].get(reverse("manifestation_document", args=[m["id"], doc["id"]])).status_code == 200
    texte = SimpleUploadedFile("x.txt", b"pas une image", content_type="text/plain")
    assert asso["bureau"].post(reverse("manifestation_documents", args=[m["id"]]), {"fichier": texte}, format="multipart").status_code == 400
