"""La couche SMS : registre de fournisseurs, et refus explicite d'inventer un contrat.

**Mobimel n'est pas implémenté, et ces tests l'affirment.** L'opérateur existe, mais aucune
documentation publique de son API n'a pu être trouvée le 11/11/2026 : ni endpoint, ni
paramètres, ni forme d'authentification. Un adaptateur écrit sur des suppositions produirait du
code qui compile, qui a l'air juste, qui échoue au premier envoi — et qui enverrait des
identifiants à une URL inventée.

Ce qui EST construit se teste donc : la configuration par institution, le stockage chiffré, le
registre, la journalisation de l'échec, et le fait qu'un envoi non implémenté ne casse jamais
l'action qui l'accompagne.
"""
import pytest
from django.db import connection

from core.envoi_sms import (
    FOURNISSEURS, EchecSms, FournisseurNonImplemente, envoyer_sms_pour_institution,
    fournisseurs_disponibles,
)
from core.models import ConfigurationEnvoiInstitution, Institution, InstitutionType

CLE_SMS = "cle-sms-essai-0123456789"


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_SMS',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom="Association SMS Test", type=itype,
                                      nom_affichage="Reserve SMS")


@pytest.fixture
def config(institution):
    return ConfigurationEnvoiInstitution.objects.create(
        institution=institution, fournisseur_sms="MOBIMEL", sms_cle_api=CLE_SMS,
        sms_expediteur="ReserveSMS")


class TestRegistre:

    def test_mobimel_est_declare_mais_marque_non_implemente(self):
        """Déclaré plutôt que masqué : un opérateur absent de la liste laisse croire qu'il n'est
        pas prévu, alors qu'il attend sa documentation. Le dire est plus utile que le cacher."""
        assert "MOBIMEL" in FOURNISSEURS
        assert FOURNISSEURS["MOBIMEL"]["implemente"] is False

    def test_la_liste_servie_a_l_interface_dit_ce_qui_marche(self):
        disponibles = {f['code']: f for f in fournisseurs_disponibles()}
        assert disponibles["MOBIMEL"]["libelle"] == "Mobimel"
        assert disponibles["MOBIMEL"]["implemente"] is False

    def test_un_fournisseur_non_implemente_leve_une_erreur_distincte(self):
        """`FournisseurNonImplemente` et pas un `EchecSms` générique : ce n'est pas une panne,
        c'est une fonctionnalité qui n'existe pas encore, et le message à l'écran diffère."""
        with pytest.raises(FournisseurNonImplemente):
            FOURNISSEURS["MOBIMEL"]["envoyer"](
                cle_api="x", expediteur="E", numero="+33600000000", message="M")
        assert issubclass(FournisseurNonImplemente, EchecSms)


@pytest.mark.django_db
class TestEnvoi:

    def test_un_envoi_non_implemente_ne_casse_rien_et_est_trace(self, institution, config):
        """Un SMS est un canal d'appoint : son échec ne doit pas faire échouer l'action qu'il
        accompagne. Mais il laisse une trace, sinon personne ne sait pourquoi rien n'est parti."""
        envoye, motif = envoyer_sms_pour_institution(institution, "+33600000000", "Alerte")

        assert envoye is False
        assert "pas encore implémenté" in motif
        config.refresh_from_db()
        assert "pas encore implémenté" in config.derniere_erreur_sms

    def test_sans_configuration_l_envoi_est_refuse_proprement(self, institution):
        envoye, motif = envoyer_sms_pour_institution(institution, "+33600000000", "Alerte")
        assert (envoye, motif) == (False, "non configuré")

    def test_un_fournisseur_inconnu_est_nomme(self, institution, config):
        """`fournisseur_sms` est une chaîne libre pour éviter une migration par opérateur : la
        contrepartie est qu'une faute de frappe est possible, et doit se voir."""
        config.fournisseur_sms = "OPERATEUR_INEXISTANT"
        config.save(update_fields=['fournisseur_sms'])

        envoye, motif = envoyer_sms_pour_institution(institution, "+33600000000", "Alerte")
        assert envoye is False
        assert "OPERATEUR_INEXISTANT" in motif

    def test_un_adaptateur_qui_leve_n_importe_quoi_ne_propage_pas(self, institution, config,
                                                                  monkeypatch):
        """Un bug dans un adaptateur futur ne doit pas remonter jusqu'à l'appelant."""
        def adaptateur_casse(**_):
            raise RuntimeError("bug dans l'adaptateur")

        monkeypatch.setitem(FOURNISSEURS, "MOBIMEL",
                            {**FOURNISSEURS["MOBIMEL"], "envoyer": adaptateur_casse})
        envoye, motif = envoyer_sms_pour_institution(institution, "+33600000000", "Alerte")
        assert envoye is False
        assert "bug dans l'adaptateur" in motif

    def test_un_adaptateur_qui_reussit_horodate_et_efface_l_erreur(self, institution, config,
                                                                   monkeypatch):
        monkeypatch.setitem(FOURNISSEURS, "MOBIMEL",
                            {**FOURNISSEURS["MOBIMEL"],
                             "envoyer": lambda **_: "identifiant-operateur"})
        config.derniere_erreur_sms = "ancienne erreur"
        config.save(update_fields=['derniere_erreur_sms'])

        envoye, identifiant = envoyer_sms_pour_institution(institution, "+33600000000", "M")
        assert (envoye, identifiant) == (True, "identifiant-operateur")
        config.refresh_from_db()
        assert config.derniere_erreur_sms == ""
        assert config.dernier_envoi_sms_le is not None

    def test_l_expediteur_retombe_sur_le_nom_de_l_institution(self, institution, config,
                                                              monkeypatch):
        recus = {}
        monkeypatch.setitem(FOURNISSEURS, "MOBIMEL",
                            {**FOURNISSEURS["MOBIMEL"],
                             "envoyer": lambda **kw: recus.update(kw) or "id"})
        config.sms_expediteur = ""
        config.save(update_fields=['sms_expediteur'])

        envoyer_sms_pour_institution(institution, "+33600000000", "M")
        assert recus['expediteur'] == "Reserve SMS"

    def test_la_cle_sms_est_chiffree_au_repos(self, config):
        """Vérifié en SQL brut : seule façon de constater ce qu'un `pg_dump` contiendrait."""
        with connection.cursor() as curseur:
            curseur.execute(
                "SELECT sms_cle_api FROM core_configurationenvoiinstitution WHERE id = %s",
                [str(config.id)],
            )
            stocke = curseur.fetchone()[0]
        assert CLE_SMS not in (stocke or "")
        config.refresh_from_db()
        assert config.sms_cle_api == CLE_SMS
