"""Chaîne d'affectation automatique de la crise démo du Gier (commande
completer_affectation_auto_gier, 28/10/2026).

Chaque test pose un des quatre maillons manquants constatés dans la base de démo, parce que
chacun suffit seul à rendre l'affectation automatique muette : correspondance thème -> besoin ->
compétence, AffectationCompetence (la seule table lue par le matching), régulateur disponible
(sinon EN_ATTENTE_DISTRIBUTION), et absence de recouvrement de compétences entre équipes (deux
équipes à égalité parfaite ne produisent aucune suggestion, décision du 26/09).
"""
import pytest
from django.core.management import call_command
from django.contrib.gis.geos import MultiPolygon, Point, Polygon

from core.management.commands.generate_crise_gier_pilat import (
    CRISIS_NAME,
    EQUIPE_HEBERGEMENT,
    EQUIPE_LOGISTIQUE,
    EQUIPE_TRANSPORT,
)
from core.models import (
    AffectationCompetence,
    AffectationRoleOperationnel,
    Besoin,
    BesoinCompetence,
    Competence,
    Crisis,
    Dossier,
    DossierParticipant,
    Environment,
    Information,
    InformationType,
    Institution,
    InstitutionType,
    Request,
    RequestType,
    Team,
    TypeCrise,
    User,
    UserRole,
)

COMMUNE = "42207"
# Dans le polygone de la crise construit ci-dessous.
POINT = Point(4.51, 45.47, srid=4326)


@pytest.fixture
def catalogue(db):
    """Le minimum du catalogue partagé : les besoins et compétences que la commande relie."""
    for nom in [
        "Organisation de l'accueil / hébergement", "Accueil", "Soutien psychologique",
        "Nettoyage et déblaiement", "Logistique", "Transport", "Secourisme",
    ]:
        Competence.objects.get_or_create(nom=nom)
    for nom in ["Hébergement", "Nettoyage - déblaiement", "Route barrée", "Autre"]:
        Besoin.objects.get_or_create(nom=nom)


@pytest.fixture
def crise(db):
    zone = Polygon.from_bbox((4.40, 45.40, 4.60, 45.55))
    zone.srid = 4326
    return Crisis.objects.create(
        name=CRISIS_NAME, description="Crise de test", type=TypeCrise.INONDATION,
        location=POINT, zone=zone, zone_communes=[COMMUNE], zone_departements=["42"],
        zone_secteurs=MultiPolygon(zone, srid=4326), environment=Environment.DEMO,
    )


@pytest.fixture
def equipes(db, crise):
    """Les trois équipes telles que le générateur les crée : « Logistique » posée sur DEUX
    équipes à la fois, aucune zone, et aucune AffectationCompetence."""
    type_mairie, _ = InstitutionType.objects.get_or_create(
        code="mairie", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(
        nom="Mairie de Saint-Chamond", type=type_mairie, commune_code=COMMUNE)
    noms_par_equipe = {
        EQUIPE_HEBERGEMENT: ["Organisation de l'accueil / hébergement", "Logistique"],
        EQUIPE_LOGISTIQUE: ["Nettoyage et déblaiement", "Logistique"],
        EQUIPE_TRANSPORT: ["Transport", "Secourisme"],
    }
    equipes = {}
    for nom, competences in noms_par_equipe.items():
        equipe = Team.objects.create(
            name=nom, institution=institution, environment=Environment.DEMO)
        equipe.competences.set(Competence.objects.filter(nom__in=competences))
        equipe.assigned_crises.add(crise)
        equipes[nom] = equipe
    return equipes


def _demande(crise, type_nom):
    request_type, _ = RequestType.objects.get_or_create(type=type_nom)
    return Request.objects.create(
        title=f"Demande {type_nom}", request_type=request_type, crisis=crise,
        location=POINT, commune_code=COMMUNE, departement_code="42",
        first_name_request="Jean", last_name_request="Dupont",
        email_request="demandeur@exemple.fr", environment=Environment.DEMO,
    )


def _signalement(crise, type_nom):
    information_type, _ = InformationType.objects.get_or_create(type=type_nom)
    return Information.objects.create(
        title=f"Signalement {type_nom}", information_type=information_type, crisis=crise,
        location=POINT, commune_code=COMMUNE,
        first_name_information="Marie", last_name_information="Martin",
        email_information="temoin@exemple.fr", environment=Environment.DEMO,
    )


@pytest.mark.django_db
class TestCorrespondances:
    def test_un_signalement_route_barree_recoit_enfin_une_competence(self, catalogue, crise, equipes):
        """Le défaut le plus large : la migration 0174 a créé les besoins des signalements sans
        jamais les relier à une compétence, donc AUCUN signalement ne pouvait être affecté."""
        signalement = _signalement(crise, "Route barrée")
        assert not BesoinCompetence.objects.filter(besoin__nom="Route barrée").exists()

        call_command("completer_affectation_auto_gier")

        dossier = Dossier.objects.get(information=signalement)
        assert dossier.competence.nom == "Nettoyage et déblaiement"
        assert dossier.equipe.name == EQUIPE_LOGISTIQUE

    def test_un_type_de_demande_au_nom_decale_est_relie(self, catalogue, crise, equipes):
        """« Nettoyage / déblaiement » (libellé du formulaire) et « Nettoyage - déblaiement »
        (besoin) ne coïncident pas : sans alias, le miroir par nom ne trouve rien."""
        demande = _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier")

        dossier = Dossier.objects.get(demande=demande)
        assert dossier.besoin.nom == "Nettoyage - déblaiement"
        assert dossier.competence.nom == "Nettoyage et déblaiement"

    def test_une_correspondance_existante_n_est_jamais_ecrasee(self, catalogue, crise, equipes):
        """`resolve_competence_for_request` lit `.first()` sans ordre : ajouter un second lien
        sur un besoin déjà relié rendrait la résolution non déterministe."""
        besoin = Besoin.objects.get(nom="Hébergement")
        BesoinCompetence.objects.create(
            besoin=besoin, competence=Competence.objects.get(nom="Accueil"))

        call_command("completer_affectation_auto_gier")

        assert BesoinCompetence.objects.filter(besoin=besoin).count() == 1

    def test_un_besoin_manquant_est_cree_en_miroir_du_type(self, catalogue, crise, equipes):
        """« Danger imminent » n'existe comme Besoin que si la migration 0174 a trouvé
        l'InformationType homonyme : sans lui, le signalement n'a aucun thème et le dossier
        reste orphelin au lieu d'aller au secourisme."""
        signalement = _signalement(crise, "Danger imminent")
        assert not Besoin.objects.filter(nom="Danger imminent").exists()

        call_command("completer_affectation_auto_gier")

        assert Dossier.objects.get(information=signalement).competence.nom == "Secourisme"

    def test_autre_reste_sans_competence(self, catalogue, crise, equipes):
        """Fourre-tout du formulaire public : le dossier doit tomber en tri manuel, c'est son
        rôle — pas se voir attribuer une compétence inventée."""
        demande = _demande(crise, "Autre")

        call_command("completer_affectation_auto_gier")

        dossier = Dossier.objects.get(demande=demande)
        assert dossier.competence is None
        assert dossier.statut == Dossier.Statut.EN_ATTENTE_AFFECTATION


@pytest.mark.django_db
class TestEquipes:
    def test_les_affectations_de_competence_sont_creees(self, catalogue, crise, equipes):
        """`Team.competences` ne sert qu'à l'affichage : seule AffectationCompetence est lue
        par meilleure_equipe_pour_competence."""
        assert not AffectationCompetence.objects.exists()

        call_command("completer_affectation_auto_gier")

        assert AffectationCompetence.objects.filter(crise=crise, active=True).exists()

    def test_le_recouvrement_de_competences_est_defait(self, catalogue, crise, equipes):
        """« Logistique » sur deux équipes sans zone ni charge = égalité parfaite = aucune
        suggestion. La commande n'en laisse qu'une porteuse."""
        porteuses = Team.objects.filter(
            competences__nom="Logistique", environment=Environment.DEMO)
        assert porteuses.count() == 2

        call_command("completer_affectation_auto_gier")

        assert porteuses.count() == 1
        assert porteuses.first().name == EQUIPE_LOGISTIQUE

    def test_la_zone_de_la_crise_est_declaree_sur_chaque_equipe(self, catalogue, crise, equipes):
        call_command("completer_affectation_auto_gier")

        for equipe in Team.objects.filter(environment=Environment.DEMO):
            assert equipe.communes == [COMMUNE]


@pytest.mark.django_db
class TestDesignationDeLaCrise:
    def test_une_crise_renommee_est_quand_meme_trouvee(self, catalogue, crise, equipes):
        """Constaté le 28/10/2026 : la crise réelle s'appelait « démo inondation vallée du gier
        et pilat ». Chercher le nom littéral du générateur échouait alors qu'elle était là."""
        Crisis.objects.filter(pk=crise.pk).update(
            name="démo inondation vallée du gier et pilat")
        demande = _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier")

        assert Dossier.objects.filter(demande=demande).exists()

    def test_plusieurs_crises_candidates_refuse_de_choisir(self, catalogue, crise, equipes):
        from django.core.management.base import CommandError

        Crisis.objects.create(
            name="Autre essai Gier", type=TypeCrise.INONDATION,
            location=POINT, environment=Environment.DEMO,
        )

        with pytest.raises(CommandError, match="préciser --crise"):
            call_command("completer_affectation_auto_gier")

    def test_le_nom_exact_leve_l_ambiguite(self, catalogue, crise, equipes):
        Crisis.objects.create(
            name="Autre essai Gier", type=TypeCrise.INONDATION,
            location=POINT, environment=Environment.DEMO,
        )
        demande = _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier", crise=crise.name)

        assert Dossier.objects.get(demande=demande).crise_id == crise.id


@pytest.mark.django_db
class TestIntervenant:
    @pytest.fixture
    def fred(self, db):
        return User.objects.create_user(
            username="fred", email="fred@exemple.fr", password="MotDePasse!2026",
            first_name="Fred", last_name="Bouchet", type=UserRole.LOCAL_AUTHORITY,
        )

    def test_retrouve_par_prenom_et_nom(self, catalogue, crise, equipes, fred):
        """L'email est chiffré et ne doit pas circuler : « Prénom Nom » doit suffire."""
        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        assert set(fred.teams.values_list("name", flat=True)) == set(equipes)

    def test_un_prenom_usuel_retrouve_un_prenom_accentue(self, catalogue, crise, equipes, fred):
        """« Fred » ne préfixe pas « Frédéric » pour la base : la différence tombe sur le
        troisième caractère. C'est pourtant exactement ce qu'on tape."""
        fred.first_name = "Frédéric"
        fred.save(update_fields=["first_name"])

        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        assert fred.teams.exists()

    def test_retrouve_par_email(self, catalogue, crise, equipes, fred):
        call_command("completer_affectation_auto_gier", intervenant="fred@exemple.fr")

        assert fred.teams.exists()

    def test_devient_regulateur_disponible_sur_les_themes(self, catalogue, crise, equipes, fred):
        """Sans régulateur disponible, le dossier naît EN_ATTENTE_DISTRIBUTION et la file
        /dossiers/ma_file/ reste vide pour tout le monde."""
        demande = _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        affectation = AffectationRoleOperationnel.objects.get(
            utilisateur=fred, role__code="REGULATEUR",
            competence__nom="Nettoyage et déblaiement")
        assert affectation.disponibilites.filter(
            disponible=True, date_fin__isnull=True).exists()
        assert Dossier.objects.get(demande=demande).statut == (
            Dossier.Statut.EN_ATTENTE_AFFECTATION)

    def test_sans_regulateur_le_dossier_reste_en_attente_de_distribution(
            self, catalogue, crise, equipes):
        demande = _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier")

        assert Dossier.objects.get(demande=demande).statut == (
            Dossier.Statut.EN_ATTENTE_DISTRIBUTION)

    def test_le_role_demo_est_pose_car_c_est_lui_qui_ouvre_les_menus(
            self, catalogue, crise, equipes, fred):
        """En zone de démonstration, `AuthService.getEffectiveRole` lit `demo_role` et jamais
        `type` : sans lui, un compte institutionnel en production n'ouvre aucun menu en démo."""
        assert fred.demo_role is None

        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        fred.refresh_from_db()
        assert fred.demo_role == UserRole.REGULATEUR

    def test_un_role_demo_institutionnel_n_est_jamais_abaisse(
            self, catalogue, crise, equipes, fred):
        fred.demo_role = UserRole.LOCAL_AUTHORITY
        fred.save(update_fields=["demo_role"])

        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        fred.refresh_from_db()
        assert fred.demo_role == UserRole.LOCAL_AUTHORITY

    def test_le_role_de_production_n_est_pas_touche(self, catalogue, crise, equipes, fred):
        """Relever `type` donnerait des droits réels sur des données réelles pour les besoins
        d'une démonstration."""
        fred.type = UserRole.SIMPLE_USER
        fred.save(update_fields=["type"])

        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        fred.refresh_from_db()
        assert fred.type == UserRole.SIMPLE_USER

    def test_est_participant_des_dossiers_rattrapes(self, catalogue, crise, equipes, fred):
        """C'est ce lien, et non le rôle du compte, qui fait apparaître un dossier dans
        « Mes interventions »."""
        demande = _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        assert DossierParticipant.objects.filter(
            dossier__demande=demande, utilisateur=fred,
            role=DossierParticipant.Role.EQUIPE).exists()

    def test_une_personne_inconnue_ne_fait_pas_echouer_le_reste(self, catalogue, crise, equipes):
        demande = _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier", intervenant="Personne Inexistante")

        assert Dossier.objects.filter(demande=demande).exists()


@pytest.mark.django_db
class TestCategoriesParentes:
    def test_une_equipe_couvre_la_categorie_de_sa_specialite(self, catalogue, crise, equipes):
        """Le catalogue réel relie « Danger imminent » à la CATÉGORIE « Secours & sécurité »,
        qu'aucune équipe ne porte. Sans remontée au parent, un dossier correctement qualifié
        n'a aucun candidat."""
        categorie, _ = Competence.objects.get_or_create(nom="Secours & sécurité")
        Competence.objects.filter(nom="Secourisme").update(parent=categorie)
        besoin, _ = Besoin.objects.get_or_create(nom="Danger imminent")
        BesoinCompetence.objects.filter(besoin=besoin).delete()
        BesoinCompetence.objects.create(besoin=besoin, competence=categorie)
        signalement = _signalement(crise, "Danger imminent")

        call_command("completer_affectation_auto_gier")

        dossier = Dossier.objects.get(information=signalement)
        assert dossier.competence == categorie
        assert dossier.equipe.name == EQUIPE_TRANSPORT


@pytest.mark.django_db
class TestResuggestion:
    def test_un_dossier_deja_ouvert_recoit_son_equipe(self, catalogue, crise, equipes):
        """Le cas réel : tous les dossiers existaient déjà, sans équipe. Leur suggestion n'est
        calculée qu'à la création — la phase de rattrapage ne les voit même pas."""
        demande = _demande(crise, "Nettoyage / déblaiement")
        dossier = Dossier.objects.create(
            numero="DOS-TEST0001", crise=crise, demande=demande, titre=demande.title,
            description="Dossier anterieur", statut=Dossier.Statut.EN_ATTENTE_AFFECTATION,
            competence=Competence.objects.get(nom="Nettoyage et déblaiement"),
            environment=Environment.DEMO,
        )

        call_command("completer_affectation_auto_gier")

        dossier.refresh_from_db()
        assert dossier.equipe.name == EQUIPE_LOGISTIQUE

    def test_une_competence_sans_equipe_est_signalee(self, catalogue, crise, equipes, capsys):
        orpheline, _ = Competence.objects.get_or_create(nom="Plongée subaquatique")
        demande = _demande(crise, "Nettoyage / déblaiement")
        Dossier.objects.create(
            numero="DOS-TEST0002", crise=crise, demande=demande, titre=demande.title,
            description="Dossier anterieur", statut=Dossier.Statut.EN_ATTENTE_AFFECTATION,
            competence=orpheline, environment=Environment.DEMO,
        )

        call_command("completer_affectation_auto_gier")

        assert "Plongée subaquatique" in capsys.readouterr().out


@pytest.mark.django_db
class TestRattrapage:
    def test_les_lignes_deja_en_base_recoivent_un_dossier(self, catalogue, crise, equipes):
        """Le générateur crée demandes et signalements en bulk_create : aucun perform_create,
        donc aucun dossier, même une fois la chaîne réparée."""
        _demande(crise, "Nettoyage / déblaiement")
        _signalement(crise, "Route barrée")
        assert not Dossier.objects.exists()

        call_command("completer_affectation_auto_gier")

        assert Dossier.objects.count() == 2

    def test_relancer_la_commande_ne_duplique_rien(self, catalogue, crise, equipes):
        _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")
        call_command("completer_affectation_auto_gier", intervenant="Fred Bouchet")

        assert Dossier.objects.count() == 1
        assert AffectationCompetence.objects.filter(crise=crise).count() == (
            AffectationCompetence.objects.filter(crise=crise).distinct().count())

    def test_aucun_compte_n_est_fabrique_pour_les_demandeurs(self, catalogue, crise, equipes):
        """`resolve_or_invite_demandeur` créerait un compte par contact Faker : plusieurs
        centaines de comptes pour une démo."""
        _demande(crise, "Nettoyage / déblaiement")
        avant = User.objects.count()

        call_command("completer_affectation_auto_gier")

        assert User.objects.count() == avant

    def test_simulation_n_ecrit_rien(self, catalogue, crise, equipes):
        _demande(crise, "Nettoyage / déblaiement")

        call_command("completer_affectation_auto_gier", simulation=True)

        assert not Dossier.objects.exists()
        # Ciblé, pas global : les migrations du catalogue (0139) laissent déjà des
        # correspondances dans la base de test.
        assert not BesoinCompetence.objects.filter(besoin__nom="Nettoyage - déblaiement").exists()
        assert not AffectationCompetence.objects.exists()

    def test_crise_absente_echoue_clairement(self, catalogue, db):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="Aucune crise DEMO"):
            call_command("completer_affectation_auto_gier")
