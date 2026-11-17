"""Plans de prévention des risques de la commune (17/11/2026) : relevés auprès de Géorisques,
gardés en base, jamais redemandés sans raison. Aucun appel réseau ici : la réponse d'essai est
celle, réelle, relevée pour une commune le jour de l'écriture."""
import pytest

from core import plans_prevention, zonages_officiels
from core.models import ProcedurePPR, RelevePPR

REPONSE = [{
    "idGaspar": "33DREAL20170013", "libPpr": "PPR Bordeaux (revision)", "modeleProcedure": "PPRN-I",
    "libBassinRisques": "Agglomération bordelaise", "etatRevision": True, "supExists": True,
    "zonageReglementaire": {"zoneRegExists": True, "listTypeReg": [
        {"code": "02", "libelle": "Prescriptions", "nom": "Bleu", "codeZone": "Bleu"},
        {"code": "03", "libelle": "Interdiction", "nom": "Rouge non urbanise", "codeZone": "Rouge non urbanisé"},
    ]},
    "dateModification": "17/02/2025", "listePprRevises": ["33DDTM20010026"],
}]


@pytest.fixture(autouse=True)
def sans_attente(monkeypatch):
    monkeypatch.setattr(zonages_officiels, "PAUSE_S", 0)


def _source(reponses, appels):
    def interroger(famille, commune_code):
        appels.append(famille)
        valeur = reponses.get(famille, [])
        if isinstance(valeur, Exception):
            raise valeur
        return valeur
    return interroger


@pytest.mark.django_db
class TestReleve:

    def test_les_plans_sont_gardes_avec_les_zones_de_leur_reglement(self):
        appels = []
        bilan = plans_prevention.relever("33063", "PROD", interroger=_source({"pprn": REPONSE}, appels))

        assert appels == ["pprn", "pprt", "pprm"] and bilan["relevees"] == appels
        etat = plans_prevention.etat("33063", "PROD")
        assert etat["complet"] is True
        (plan,) = etat["plans"]
        assert (plan["libelle"], plan["famille"], plan["en_revision"]) == (
            "PPR Bordeaux (revision)", "Risques naturels", True)
        assert plan["zones"] == [{"nom": "Bleu", "regle": "Prescriptions"},
                                 {"nom": "Rouge non urbanisé", "regle": "Interdiction"}]
        assert str(plan["modifie_le"]) == "2025-02-17"

    def test_un_releve_recent_n_est_pas_refait(self):
        """On ne presse pas Géorisques : la carte et le document relisent la base."""
        appels = []
        source = _source({"pprn": REPONSE}, appels)
        plans_prevention.relever("33063", "PROD", interroger=source)
        bilan = plans_prevention.relever("33063", "PROD", interroger=source)
        assert len(appels) == 3 and bilan["ignorees"] == ["pprn", "pprt", "pprm"]
        assert len(plans_prevention.relever("33063", "PROD", forcer=True, interroger=source)["relevees"]) == 3

    def test_une_panne_n_efface_pas_ce_qu_on_savait(self):
        plans_prevention.relever("33063", "PROD", interroger=_source({"pprn": REPONSE}, []))
        bilan = plans_prevention.relever(
            "33063", "PROD", forcer=True, interroger=_source({"pprn": OSError("503")}, []))
        assert "pprn" in bilan["erreurs"]
        assert ProcedurePPR.objects.filter(commune_code="33063").count() == 1

    def test_un_plan_abroge_disparait_au_releve_suivant(self):
        plans_prevention.relever("33063", "PROD", interroger=_source({"pprn": REPONSE}, []))
        plans_prevention.relever("33063", "PROD", forcer=True, interroger=_source({"pprn": []}, []))
        assert not ProcedurePPR.objects.exists()
        assert RelevePPR.objects.count() == 3

    def test_releve_et_rien_ici_n_est_pas_jamais_releve(self):
        assert plans_prevention.etat("42001", "PROD")["releve"] is False
        plans_prevention.relever("42001", "PROD", interroger=_source({}, []))
        etat = plans_prevention.etat("42001", "PROD")
        assert (etat["releve"], etat["plans"]) == (True, [])
