"""La commande qui bâtit l'arborescence, et la table de référence qu'elle lit.

`core/zones_defense.py` est recopiée à la main : il n'existe pas d'API publique stable qui serve
la découpe en zones de défense, fixée par le décret du 10 décembre 2015. Une table figée se
vérifie donc, sinon on crée une arborescence fausse qui a l'air juste — et dont l'erreur ne se
verra qu'à l'usage, dans un département manquant.

Le recoupement qui a servi à l'établir : les comptes officiels par zone (Nord 1 région /
5 départements, Est 2/18, Ouest 4/20, Sud 3/21) et le total de 96 départements de métropole,
Corse comptée pour deux.
"""
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import EchelonEquipe, Institution, InstitutionType, Team
from core.zones_defense import (
    DEPARTEMENTS_METROPOLE, ZONES_DEFENSE, ZONES_DEFENSE_OUTRE_MER, departements_de_zone,
    verifier_coherence,
)

NOM = "Reserve Resilience Commande Test"


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_CMD',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom=NOM, type=itype)


def lancer(**options):
    sortie = StringIO()
    call_command('creer_arborescence_coordination', institution=NOM, stdout=sortie, **options)
    return sortie.getvalue()


class TestTableDeReference:

    def test_la_table_est_coherente(self):
        """Le garde-fou de la recopie : aucun département dans deux régions, aucune région dans
        deux zones, et le total de métropole juste."""
        assert verifier_coherence() == []

    def test_les_96_departements_de_metropole_sont_la(self):
        total = sum(len(d) for _c, _l, _s, regions in ZONES_DEFENSE
                    for _rc, _rl, d in regions)
        assert total == DEPARTEMENTS_METROPOLE == 96

    def test_sept_zones_en_metropole(self):
        assert len(ZONES_DEFENSE) == 7

    @pytest.mark.parametrize("code_zone,regions,departements", [
        # Comptes officiels relevés zone par zone, qui ont servi à vérifier la composition.
        ("ZD-NORD", 1, 5),
        ("ZD-EST", 2, 18),
        ("ZD-OUEST", 4, 20),
        ("ZD-SUD", 3, 21),
    ])
    def test_les_comptes_officiels_par_zone_tombent_juste(self, code_zone, regions,
                                                          departements):
        zone = next(z for z in ZONES_DEFENSE if z[0] == code_zone)
        assert len(zone[3]) == regions
        assert len(departements_de_zone(code_zone)) == departements

    def test_la_corse_compte_deux_departements_et_ils_ne_sont_pas_numeriques(self):
        """2A et 2B : un code de département n'est pas un entier, et traiter la table comme
        telle casserait ici."""
        codes = [c for c, _l in departements_de_zone("ZD-SUD")]
        assert "2A" in codes and "2B" in codes

    def test_l_outre_mer_est_inclus(self):
        """Le projet a un satellite à La Réunion : une arborescence « nationale » sans
        l'outre-mer aurait été incomplète là où elle sert déjà."""
        libelles = [
            libelle for _c, _l, _s, regions in ZONES_DEFENSE_OUTRE_MER
            for _rc, libelle, _d in regions
        ]
        assert "La Réunion" in libelles
        assert "Mayotte" in libelles


@pytest.mark.django_db
class TestCommande:

    def test_une_institution_inconnue_echoue_sans_rien_ecrire(self, institution):
        with pytest.raises(CommandError, match="Aucune institution"):
            call_command('creer_arborescence_coordination',
                         institution="Institution Qui N Existe Pas", stdout=StringIO())
        assert not Team.objects.exists()

    def test_compter_n_ecrit_rien(self, institution):
        sortie = lancer(compter=True)
        assert not Team.objects.exists()
        assert "rien n'a été écrit" in sortie

    def test_l_arborescence_complete_est_creee(self, institution):
        lancer()
        national = Team.objects.get(echelon=EchelonEquipe.NATIONAL)
        assert national.name == "Coordination Nationale"
        assert national.equipe_parente is None

        zones = Team.objects.filter(echelon=EchelonEquipe.ZONE_DEFENSE)
        assert zones.count() == len(ZONES_DEFENSE) + len(ZONES_DEFENSE_OUTRE_MER)
        assert all(z.equipe_parente_id == national.id for z in zones)

        # 96 départements de métropole ; l'outre-mer s'arrête à l'échelon régional.
        assert Team.objects.filter(
            echelon=EchelonEquipe.DEPARTEMENTAL).count() == DEPARTEMENTS_METROPOLE

    def test_chaque_departement_est_rattache_a_sa_region_et_a_sa_zone(self, institution):
        lancer()
        isere = Team.objects.get(echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code='38')
        assert isere.territoire_libelle == "Isère"
        region = isere.equipe_parente
        assert region.echelon == EchelonEquipe.REGIONAL
        assert region.territoire_libelle == "Auvergne-Rhône-Alpes"
        zone = region.equipe_parente
        assert zone.echelon == EchelonEquipe.ZONE_DEFENSE
        assert zone.territoire_libelle == "Sud-Est"
        assert zone.equipe_parente.echelon == EchelonEquipe.NATIONAL

    def test_une_equipe_departementale_renseigne_aussi_departements(self, institution):
        """`territoire_code` dit ce que l'équipe REPRÉSENTE ; `departements` est ce que lit le
        matching d'intervention existant. Oublier le second rendrait l'équipe invisible au
        moteur d'affectation."""
        lancer()
        isere = Team.objects.get(echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code='38')
        assert isere.departements == ['38']
        region = isere.equipe_parente
        assert sorted(region.departements) == sorted([
            '01', '03', '07', '15', '26', '38', '42', '43', '63', '69', '73', '74'])

    def test_la_commande_est_idempotente(self, institution):
        """Relançable après un décret, ou pour rattraper une branche."""
        lancer()
        total = Team.objects.count()
        sortie = lancer()
        assert Team.objects.count() == total
        assert "équipes créées       : 0" in sortie
        assert f"équipes mises à jour : {total}" in sortie

    def test_un_renommage_a_la_main_n_est_pas_duplique(self, institution):
        """L'équipe est retrouvée par (institution, échelon, territoire) et JAMAIS par son nom :
        un libellé d'affichage n'a aucune raison d'être stable."""
        lancer()
        isere = Team.objects.get(echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code='38')
        isere.name = "Les Casques Jaunes de l'Isère"
        isere.save(update_fields=['name'])

        lancer()
        assert Team.objects.filter(echelon=EchelonEquipe.DEPARTEMENTAL,
                                   territoire_code='38').count() == 1

    def test_aucun_salon_matrix_n_est_provisionne(self, institution):
        """Décision du 11/11/2026 : 127 équipes feraient 254 salons, presque tous vides et tous
        affichés dans Element. Un salon se crée quand l'équipe a des membres."""
        from core.models import SalonMatrixEquipe

        sortie = lancer()
        assert not SalonMatrixEquipe.objects.exists()
        assert "Aucun salon Matrix n'a été provisionné" in sortie

    def test_sans_outre_mer_ne_cree_que_la_metropole(self, institution):
        lancer(sans_outre_mer=True)
        assert Team.objects.filter(
            echelon=EchelonEquipe.ZONE_DEFENSE).count() == len(ZONES_DEFENSE)
