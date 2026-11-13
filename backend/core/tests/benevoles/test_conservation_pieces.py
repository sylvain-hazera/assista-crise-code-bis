"""Les pièces justificatives : ce qu'on annonce, et ce qu'on fait.

Demande de Sylvain du 13/11/2026 : afficher la politique de conservation sur la page de dépôt
et sur la page de validation, et **l'appliquer** — « pour le permis, la destruction du fichier
une fois validé, et une destruction à 30 jours s'il n'est pas validé ».

Ce qui est tenu ici n'est pas l'affichage, c'est la promesse :

1. **La table affichée et le code qui détruit sont la MÊME source.** Un tableau qui promet une
   destruction qui n'a pas lieu est pire que pas de tableau : il endort la vigilance de celui
   qui dépose.
2. **La trace survit au fichier.** Détruire la pièce ne doit jamais faire perdre la preuve que
   le contrôle a eu lieu — sinon personne n'osera détruire.
3. **Un dépôt oublié ne devient pas un stock.** Trente jours sans décision, et le fichier
   part ; la ligne reste, pour que le membre sache qu'il doit redéposer.
4. **On ne détruit pas ce qui doit être produit à un tiers.** Un PSE1 se conserve : c'est la
   pièce qui prouve, après coup, que l'équipe envoyée était qualifiée.
"""
import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.conservation_pieces import (
    CLES_DEPOSABLES, PIECES, REGIME_VERIFIER_DETRUIRE, detruire_apres_validation, piece,
)
from core.models import (
    ContactInstitution, Institution, InstitutionType, Qualification, QualificationMembre,
    StatutQualification, UserRole,
)


def _pdf(nom="permis.pdf"):
    return SimpleUploadedFile(nom, b"%PDF-1.4 faux", content_type="application/pdf")


@pytest.fixture
def association(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "Association"})
    return Institution.objects.create(nom="AASC Conservation", type=itype)


@pytest.fixture
def bureau(create_user, association):
    user = create_user(username="bureau-cons@test.fr", email="bureau-cons@test.fr",
                       type=UserRole.ORGANIZED_RESCUE)
    ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True,
                                      membre_bureau=True)
    return user


@pytest.fixture
def membre(create_user, association):
    user = create_user(username="membre-cons@test.fr", email="membre-cons@test.fr",
                       type=UserRole.ORGANIZED_RESCUE)
    ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True)
    return user


@pytest.fixture
def titre_permis(db):
    return Qualification.objects.create(nom="Permis B — test", categorie_piece="PERMIS")


@pytest.fixture
def titre_pse(db):
    return Qualification.objects.create(nom="PSE1 — test", categorie_piece="SECOURISME")


def _depot(utilisateur, titre, depose_le=None):
    ligne = QualificationMembre.objects.create(
        utilisateur=utilisateur, qualification=titre, environment="PROD",
        justificatif=_pdf(), justificatif_nom="permis-2019.pdf",
        justificatif_depose_le=depose_le or timezone.now(),
        statut=StatutQualification.DECLAREE,
    )
    return ligne


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestLaTableEstLaSourceUnique:
    def test_chaque_piece_deposable_porte_une_base_legale_et_un_pourquoi(self):
        """Une durée sans texte applicable n'est qu'une affirmation de plus."""
        for cle in CLES_DEPOSABLES:
            regle = piece(cle)
            assert regle["base_legale"].strip(), cle
            assert regle["pourquoi"].strip(), cle
            assert regle["duree"].strip(), cle

    def test_une_duree_ferme_cite_un_article(self):
        """`ferme` veut dire « un texte l'impose » : si rien n'est cité, le drapeau ment."""
        for regle in PIECES:
            if regle["ferme"]:
                assert any(mot in regle["base_legale"]
                           for mot in ("art.", "Art.", "Loi", "décret", "RGPD")), regle["cle"]

    def test_le_permis_se_verifie_et_ne_se_conserve_pas(self):
        assert detruire_apres_validation("PERMIS") is True
        assert piece("PERMIS")["regime"] == REGIME_VERIFIER_DETRUIRE

    def test_un_titre_de_secourisme_se_conserve(self):
        """C'est la pièce qui prouve, après coup, que l'équipe envoyée était qualifiée."""
        assert detruire_apres_validation("SECOURISME") is False

    def test_une_categorie_inconnue_retombe_sur_la_moins_destructrice(self):
        """Une entrée de catalogue créée par une institution ne doit pas faire détruire une
        pièce par accident : se tromper fait garder de trop, jamais perdre."""
        assert detruire_apres_validation("CATEGORIE_QUI_N_EXISTE_PAS") is False

    def test_la_table_est_servie_a_l_interface(self, membre):
        reponse = _client(membre).get(reverse("conservation_pieces"))

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["jours_avant_purge_non_validee"] == 30
        assert len(reponse.data["regimes"]) == 3
        assert any(p["cle"] == "PERMIS" for p in reponse.data["pieces"])


class TestLaValidationDetruitCeQuiDoitLEtre:
    def test_valider_un_permis_detruit_le_fichier(self, bureau, membre, titre_permis):
        ligne = _depot(membre, titre_permis)

        reponse = _client(bureau).post(
            reverse("qualificationmembre-verifier", args=[ligne.id]))

        assert reponse.status_code == status.HTTP_200_OK
        ligne.refresh_from_db()
        assert not ligne.justificatif
        assert ligne.justificatif_nom == ""

    def test_la_trace_survit_au_fichier(self, bureau, membre, titre_permis):
        """Sans cela, personne n'oserait détruire : il ne resterait plus rien pour montrer
        que le contrôle a eu lieu."""
        ligne = _depot(membre, titre_permis)

        _client(bureau).post(reverse("qualificationmembre-verifier", args=[ligne.id]))

        ligne.refresh_from_db()
        assert ligne.statut == StatutQualification.VERIFIEE
        assert ligne.verifie_par_id == bureau.id
        assert ligne.verifie_le is not None
        assert ligne.piece_detruite_le is not None

    def test_valider_un_pse_garde_le_fichier(self, bureau, membre, titre_pse):
        ligne = _depot(membre, titre_pse)

        _client(bureau).post(reverse("qualificationmembre-verifier", args=[ligne.id]))

        ligne.refresh_from_db()
        assert ligne.justificatif
        assert ligne.piece_detruite_le is None

    def test_refuser_un_permis_detruit_aussi(self, bureau, membre, titre_permis):
        """Une copie refusée n'a plus rien à prouver, et le membre va en redéposer une."""
        ligne = _depot(membre, titre_permis)

        _client(bureau).post(reverse("qualificationmembre-refuser", args=[ligne.id]),
                             {"motif": "Illisible"}, format="json")

        ligne.refresh_from_db()
        assert not ligne.justificatif
        assert ligne.statut == StatutQualification.REFUSEE
        assert ligne.motif_refus == "Illisible"

    def test_la_regle_est_servie_avec_le_titre(self, bureau, membre, titre_permis):
        """L'écran doit pouvoir annoncer la destruction AU MOMENT du dépôt, pas après."""
        ligne = _depot(membre, titre_permis)

        reponse = _client(bureau).get(
            reverse("qualificationmembre-detail", args=[ligne.id]))

        assert reponse.data["conservation"]["regime"] == REGIME_VERIFIER_DETRUIRE
        assert reponse.data["conservation"]["jours_avant_purge_non_validee"] == 30


class TestLaPurgeDesDepotsOublies:
    def test_un_depot_sans_decision_est_detruit_a_trente_jours(self, membre, titre_permis):
        from core.pieces_conformite import purger

        vieux = timezone.now() - datetime.timedelta(days=31)
        ligne = _depot(membre, titre_permis, depose_le=vieux)

        purgees = purger()

        assert [p.id for p in purgees] == [ligne.id]
        ligne.refresh_from_db()
        assert not ligne.justificatif
        assert ligne.piece_detruite_le is not None

    def test_la_ligne_survit_a_la_purge(self, membre, titre_permis):
        """Supprimer la ligne ferait perdre au membre la date et l'organisme qu'il avait
        saisis — une double peine pour une négligence qui n'est pas la sienne."""
        from core.pieces_conformite import purger

        vieux = timezone.now() - datetime.timedelta(days=31)
        ligne = _depot(membre, titre_permis, depose_le=vieux)
        ligne.organisme = "Préfecture"
        ligne.save()

        purger()

        ligne.refresh_from_db()
        assert ligne.organisme == "Préfecture"
        assert ligne.statut == StatutQualification.DECLAREE

    def test_un_depot_recent_n_est_pas_touche(self, membre, titre_permis):
        from core.pieces_conformite import purger

        ligne = _depot(membre, titre_permis,
                       depose_le=timezone.now() - datetime.timedelta(days=5))

        assert purger() == []
        ligne.refresh_from_db()
        assert ligne.justificatif

    def test_une_piece_deja_validee_n_est_pas_purgee(self, membre, titre_pse):
        """Elle est conservée exprès : la purge ne vise que ce que personne n'a instruit."""
        from core.pieces_conformite import purger

        ligne = _depot(membre, titre_pse,
                       depose_le=timezone.now() - datetime.timedelta(days=90))
        ligne.statut = StatutQualification.VERIFIEE
        ligne.save()

        assert purger() == []
        ligne.refresh_from_db()
        assert ligne.justificatif

    def test_le_mode_simulation_ne_detruit_rien(self, membre, titre_permis):
        """Une purge ne se lance pas à l'aveugle."""
        from core.pieces_conformite import purger

        ligne = _depot(membre, titre_permis,
                       depose_le=timezone.now() - datetime.timedelta(days=31))

        annoncees = purger(appliquer=False)

        assert [p.id for p in annoncees] == [ligne.id]
        ligne.refresh_from_db()
        assert ligne.justificatif

    def test_le_rappel_part_une_seule_fois(self, membre, titre_permis):
        """Un rappel quotidien pendant une semaine n'est plus un rappel, c'est du bruit."""
        from core.pieces_conformite import a_rappeler

        _depot(membre, titre_permis,
               depose_le=timezone.now() - datetime.timedelta(days=23, hours=2))

        assert a_rappeler().count() == 1
        # Le lendemain, la même ligne n'est plus dans la fenêtre.
        demain = timezone.now() + datetime.timedelta(days=1)
        assert a_rappeler(maintenant=demain).count() == 0


class TestRequalifierUnePieceMalRangee:
    """« Si le bénévole se plante et met permis dans diplôme, le management doit pouvoir
    modifier cela » (13/11/2026).

    L'enjeu n'est pas l'étiquette : le titre décide du régime de conservation, donc du sort
    du fichier. Une pièce mal rangée est une pièce dont on appliquera la mauvaise règle."""

    def test_le_management_corrige_le_titre(self, bureau, membre, titre_permis, titre_pse):
        ligne = _depot(membre, titre_pse)   # permis déposé sous « PSE1 »

        reponse = _client(bureau).post(
            reverse("qualificationmembre-requalifier", args=[ligne.id]),
            {"qualification": str(titre_permis.id)}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        ligne.refresh_from_db()
        assert ligne.qualification_id == titre_permis.id

    def test_la_bonne_regle_s_applique_ensuite(self, bureau, membre, titre_permis,
                                               titre_pse):
        """Le vrai test : requalifier puis valider doit DÉTRUIRE, là où valider sans
        corriger aurait conservé la photo du permis cinq ans."""
        ligne = _depot(membre, titre_pse)

        _client(bureau).post(reverse("qualificationmembre-requalifier", args=[ligne.id]),
                             {"qualification": str(titre_permis.id)}, format="json")
        _client(bureau).post(reverse("qualificationmembre-verifier", args=[ligne.id]))

        ligne.refresh_from_db()
        assert not ligne.justificatif
        assert ligne.piece_detruite_le is not None

    def test_la_piece_repasse_a_instruire(self, bureau, membre, titre_permis, titre_pse):
        """On se prononce sur le titre corrigé, pas sur celui qu'on vient de remplacer."""
        ligne = _depot(membre, titre_pse)
        _client(bureau).post(reverse("qualificationmembre-refuser", args=[ligne.id]),
                             {"motif": "Ce n'est pas un PSE1"}, format="json")

        _client(bureau).post(reverse("qualificationmembre-requalifier", args=[ligne.id]),
                             {"qualification": str(titre_permis.id)}, format="json")

        ligne.refresh_from_db()
        assert ligne.statut == StatutQualification.DECLAREE
        assert ligne.motif_refus == ""
        assert ligne.verifie_par is None

    def test_une_piece_deja_verifiee_ne_se_requalifie_pas(self, bureau, membre, titre_permis,
                                                          titre_pse):
        """Son fichier peut avoir été détruit : la déplacer sous un régime conservateur
        ferait croire à une pièce qu'on n'a plus."""
        ligne = _depot(membre, titre_permis)
        _client(bureau).post(reverse("qualificationmembre-verifier", args=[ligne.id]))

        reponse = _client(bureau).post(
            reverse("qualificationmembre-requalifier", args=[ligne.id]),
            {"qualification": str(titre_pse.id)}, format="json")

        assert reponse.status_code == status.HTTP_409_CONFLICT

    def test_un_doublon_est_annonce_au_lieu_de_casser(self, bureau, membre, titre_permis,
                                                      titre_pse):
        """La contrainte d'unicité (personne, titre) existe : on l'explique plutôt que de
        rendre une erreur de base de données."""
        _depot(membre, titre_permis)
        autre = _depot(membre, titre_pse)

        reponse = _client(bureau).post(
            reverse("qualificationmembre-requalifier", args=[autre.id]),
            {"qualification": str(titre_permis.id)}, format="json")

        assert reponse.status_code == status.HTTP_409_CONFLICT
        assert "déjà une ligne" in reponse.data["error"]

    def test_on_ne_requalifie_pas_sa_propre_piece(self, membre, titre_permis, titre_pse):
        ligne = _depot(membre, titre_pse)

        reponse = _client(membre).post(
            reverse("qualificationmembre-requalifier", args=[ligne.id]),
            {"qualification": str(titre_permis.id)}, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN


class TestReglerLaCategorieDuCatalogue:
    """Sans ce réglage, tout le catalogue reste sur le défaut prudent et aucune pièce n'est
    jamais détruite — la politique serait affichée sans jamais s'appliquer."""

    def test_le_bureau_regle_la_categorie_d_un_titre(self, bureau, titre_pse):
        reponse = _client(bureau).patch(
            reverse("qualification-detail", args=[titre_pse.id]),
            {"categorie_piece": "PERMIS"}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        titre_pse.refresh_from_db()
        assert titre_pse.categorie_piece == "PERMIS"
        assert detruire_apres_validation(titre_pse.categorie_piece) is True

    def test_une_categorie_inventee_est_refusee(self, bureau, titre_pse):
        """Le repli silencieux existe pour les entrées anciennes ; il ne doit pas couvrir une
        faute de frappe au moment même où l'on règle le sort d'un fichier."""
        reponse = _client(bureau).patch(
            reverse("qualification-detail", args=[titre_pse.id]),
            {"categorie_piece": "PERMIIS"}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        titre_pse.refresh_from_db()
        assert titre_pse.categorie_piece == "SECOURISME"

    def test_la_regle_est_servie_avec_le_catalogue(self, bureau, titre_permis):
        """L'écran de dépôt doit pouvoir annoncer la règle au moment du choix du titre."""
        reponse = _client(bureau).get(reverse("qualification-list"))

        ligne = next(q for q in reponse.data if q["id"] == str(titre_permis.id))
        assert ligne["conservation"]["regime"] == REGIME_VERIFIER_DETRUIRE
