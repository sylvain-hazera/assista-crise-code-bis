"""Format canonique des numéros de téléphone (E.164), pour traverser tout fournisseur.

Demande de Sylvain du 12/11/2026 : « prévois un nouveau format d'enregistrement des numéros de
portable, et prévois le complet pour être compatible ensuite toutes solutions ».

Ce que ces tests tiennent :

1. **L'outre-mer n'est pas en +33.** Un portable réunionnais « 0692 12 34 56 » converti en
   « 33692… » part vers un numéro métropolitain qui n'est pas le sien. Le projet a un
   satellite à La Réunion : l'erreur serait passée inaperçue jusqu'au jour où il aurait fallu
   joindre quelqu'un.
2. **Le numéro est enregistré en E.164**, pas converti à l'envoi : la base dit désormais de
   quel pays il s'agit, et un numéro étranger a une façon correcte d'être saisi.
3. **On ne jette jamais ce qu'on ne sait pas lire.** Une saisie incompréhensible est conservée
   telle quelle — l'écraser ferait perdre le seul moyen de joindre quelqu'un.
"""
import pytest

from core.telephone import afficher, est_canonique, normaliser, pour_fournisseur


class TestLaFranceEtSesTerritoires:
    @pytest.mark.parametrize("saisi,attendu", [
        ("0612345678", "+33612345678"),
        ("06 12 34 56 78", "+33612345678"),
        ("06.12.34.56.78", "+33612345678"),
        ("+33 6 12 34 56 78", "+33612345678"),
        ("0033612345678", "+33612345678"),
        ("0145678901", "+33145678901"),
    ])
    def test_la_metropole(self, saisi, attendu):
        assert normaliser(saisi) == attendu

    @pytest.mark.parametrize("saisi,attendu", [
        ("0692 12 34 56", "+262692123456"),   # La Réunion, mobile
        ("0262 12 34 56", "+262262123456"),   # La Réunion, fixe
        ("0639 12 34 56", "+262639123456"),   # Mayotte, mobile
        ("0690 12 34 56", "+590690123456"),   # Guadeloupe, mobile
        ("0696 12 34 56", "+596696123456"),   # Martinique, mobile
        ("0694 12 34 56", "+594694123456"),   # Guyane, mobile
    ])
    def test_l_outre_mer_a_son_propre_indicatif(self, saisi, attendu):
        assert normaliser(saisi) == attendu


class TestLEtrangerEtLesSaisiesDouteuses:
    @pytest.mark.parametrize("saisi,attendu", [
        ("+32 470 12 34 56", "+32470123456"),
        ("0032470123456", "+32470123456"),
        ("+41 79 123 45 67", "+41791234567"),
    ])
    def test_un_numero_etranger_passe(self, saisi, attendu):
        """Un renfort belge, un prestataire suisse : jusqu'ici aucune façon correcte de le
        saisir."""
        assert normaliser(saisi) == attendu

    @pytest.mark.parametrize("saisi", ["", None, "néant", "voir standard", "06123", "12"])
    def test_ce_qu_on_ne_sait_pas_lire_rend_none(self, saisi):
        assert normaliser(saisi) is None

    def test_un_zero_suivi_d_autre_chose_n_est_pas_devine(self):
        """Dix chiffres est la seule longueur nationale interprétable sans risque."""
        assert normaliser("012345678901") is None

    def test_est_canonique_distingue_le_format_cible(self):
        assert est_canonique("+33612345678") is True
        assert est_canonique("0612345678") is False
        assert est_canonique("") is False


class TestCeQueChaqueFournisseurAttend:
    def test_brevo_veut_les_chiffres_sans_le_plus(self):
        assert pour_fournisseur("0692123456") == "262692123456"

    def test_un_fournisseur_qui_veut_le_plus_l_obtient(self):
        """Chaque API a sa manie de présentation ; aucune n'a besoin de sa propre table."""
        assert pour_fournisseur("0692123456", avec_plus=True) == "+262692123456"

    def test_envoi_brevo_delegue_au_module_canonique(self):
        from core.envoi_brevo import numero_international

        assert numero_international("0692 12 34 56") == "262692123456"


class TestLAffichage:
    def test_un_numero_francais_se_relit_a_l_oeil(self):
        """Un E.164 ne se lit pas sur une fiche imprimée à 3 h du matin."""
        assert afficher("+33612345678") == "06 12 34 56 78"
        assert afficher("+262692123456") == "06 92 12 34 56"

    def test_un_numero_etranger_reste_en_e164(self):
        assert afficher("+32470123456") == "+32470123456"

    def test_une_saisie_illisible_est_rendue_telle_quelle(self):
        assert afficher("voir standard") == "voir standard"


@pytest.mark.django_db
class TestLEnregistrement:
    def test_le_numero_d_un_compte_est_stocke_en_e164(self, create_user):
        """Posé dans `save()` et non dans un sérialiseur : les imports de fichiers et les
        scripts doivent en bénéficier aussi."""
        user = create_user(username="tel@test.fr", email="tel@test.fr",
                           phone_number="06 12 34 56 78")

        user.refresh_from_db()
        assert user.phone_number == "+33612345678"

    def test_un_numero_reunionnais_garde_son_pays(self, create_user):
        user = create_user(username="tel974@test.fr", email="tel974@test.fr",
                           phone_number="0692 12 34 56")

        user.refresh_from_db()
        assert user.phone_number == "+262692123456"

    def test_une_saisie_illisible_est_conservee(self, create_user):
        """L'écraser ferait perdre le seul moyen de joindre quelqu'un."""
        user = create_user(username="telko@test.fr", email="telko@test.fr",
                           phone_number="voir le standard")

        user.refresh_from_db()
        assert user.phone_number == "voir le standard"

    def test_l_interlocuteur_pcs_aussi(self, db):
        """C'est à ce téléphone que part l'alerte PCS : un préfixe mal deviné l'envoie à
        quelqu'un d'autre."""
        from core.models import CategorieInterlocuteurPCS, InterlocuteurAlertePCS

        interlocuteur = InterlocuteurAlertePCS.objects.create(
            nom="Préfecture", telephone="0692 12 34 56",
            categorie=CategorieInterlocuteurPCS.values[0], environment="PROD")

        interlocuteur.refresh_from_db()
        assert interlocuteur.telephone == "+262692123456"
