"""La règle de l'arbre pour gérer une équipe d'association (21/11/2026).

« Un membre du bureau départemental ne peut pas modifier un membre du bureau régional (sauf
s'il a des droits supérieurs). » Un cadre gère son équipe (pairs compris) et tout ce qui est en
dessous ; le bureau de l'association gère tout ; une mairie, sans bureau, garde la règle d'avant."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, Team


@pytest.fixture
def arbre(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    asso = Institution.objects.create(nom="Association arbre", type=itype)
    nat = Team.objects.create(name="National", institution=asso, echelon="NATIONAL")
    reg = Team.objects.create(name="Région", institution=asso, echelon="REGIONAL", equipe_parente=nat)
    dep = Team.objects.create(name="Département", institution=asso, echelon="DEPARTEMENTAL", equipe_parente=reg)
    voisin = Team.objects.create(name="Département voisin", institution=asso, echelon="DEPARTEMENTAL", equipe_parente=reg)
    terrain = Team.objects.create(name="Terrain", institution=asso, equipe_parente=dep)

    def membre(email, bureau=False, cadre_de=None):
        u = create_user(username=email, email=email, type="SECOURS")
        u.institution = asso
        u.save(update_fields=["institution"])
        ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True, membre_bureau=bureau)
        if cadre_de is not None:
            cadre_de.members.add(u); cadre_de.membres_encadrement.add(u)
        return u
    gens = {
        "bureau": membre("bureau@arbre.test", bureau=True),
        "regional": membre("regional@arbre.test", cadre_de=reg),
        "departemental": membre("dep@arbre.test", cadre_de=dep),
        "pair": membre("pair@arbre.test"),
        "simple": membre("simple@arbre.test"),
    }
    dep.members.add(gens["pair"])
    return {"nat": nat, "reg": reg, "dep": dep, "voisin": voisin, "terrain": terrain, **gens}


def _encadrement(qui, equipe, ids):
    c = APIClient(); c.force_authenticate(user=qui)
    return c.post(reverse("team-definir-encadrement", args=[equipe.id]), {"membres_encadrement": [str(i) for i in ids]}, format="json")


@pytest.mark.django_db
class TestArbre:

    def test_le_departemental_ne_touche_pas_au_regional_ni_au_voisin(self, arbre):
        assert _encadrement(arbre["departemental"], arbre["reg"], []).status_code == 403
        assert _encadrement(arbre["departemental"], arbre["voisin"], []).status_code == 403
        assert list(arbre["reg"].membres_encadrement.all()) == [arbre["regional"]]

    def test_le_departemental_nomme_un_pair_et_gere_en_dessous(self, arbre):
        r = _encadrement(arbre["departemental"], arbre["dep"], [arbre["departemental"].id, arbre["pair"].id])
        assert r.status_code == 200, r.data
        assert _encadrement(arbre["departemental"], arbre["terrain"], []).status_code == 200

    def test_le_regional_gere_ses_departements(self, arbre):
        assert _encadrement(arbre["regional"], arbre["dep"], []).status_code == 200
        assert _encadrement(arbre["regional"], arbre["nat"], []).status_code == 403

    def test_le_bureau_a_les_droits_superieurs(self, arbre):
        assert _encadrement(arbre["bureau"], arbre["nat"], []).status_code == 200

    def test_un_membre_sans_cadre_ne_gere_rien(self, arbre):
        assert _encadrement(arbre["simple"], arbre["terrain"], []).status_code == 403

    def test_on_ne_rattache_pas_sous_une_branche_qu_on_ne_gere_pas(self, arbre):
        libre = Team.objects.create(name="Nouvelle équipe", institution=arbre["dep"].institution)
        c = APIClient(); c.force_authenticate(user=arbre["departemental"])
        assert c.post(reverse("team-rattacher-equipe", args=[arbre["voisin"].id]), {"equipe_id": str(libre.id)}, format="json").status_code == 403
        assert c.post(reverse("team-rattacher-equipe", args=[arbre["dep"].id]), {"equipe_id": str(libre.id)}, format="json").status_code == 403
        # Le bureau, lui, peut ranger l'équipe libre sous le département ; le département
        # peut ensuite la gérer.
        b = APIClient(); b.force_authenticate(user=arbre["bureau"])
        assert b.post(reverse("team-rattacher-equipe", args=[arbre["dep"].id]), {"equipe_id": str(libre.id)}, format="json").status_code == 200

    def test_la_liste_dit_ce_que_l_on_peut_administrer(self, arbre):
        c = APIClient(); c.force_authenticate(user=arbre["departemental"])
        donnees = {t["name"]: t["peut_administrer"] for t in c.get(reverse("team-list")).data}
        assert donnees["Département"] and donnees["Terrain"]
        assert not donnees["Région"] and not donnees["National"] and not donnees["Département voisin"]

    def test_une_mairie_sans_bureau_garde_la_regle_d_avant(self, db, create_user):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie sans bureau", type=itype)
        equipe = Team.objects.create(name="Services techniques", institution=mairie)
        agent = create_user(username="agent@mairie.test", email="agent@mairie.test", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
        assert _encadrement(agent, equipe, []).status_code == 200
