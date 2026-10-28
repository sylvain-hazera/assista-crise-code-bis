"""Le périmètre d'un spectateur est un ENSEMBLE de zones, plus un couple unique.

Refonte du 28/10/2026. Jusque-là, la zone d'un spectateur était un seul `(niveau, code)` : cela
convient à une mairie, dont le territoire est permanent et unique, mais pas à une association
agréée de sécurité civile, dont le territoire est par nature un ensemble de communes variable
selon les crises où elle est acceptée. Une institution sans commune propre obtenait donc
`.none()` partout — **aucun dossier, tableau de bord vide** — quelle que soit la crise sur
laquelle elle intervenait.

Deux sources de droits, et seulement deux :

1. **La crise, commune par commune** — le cas par défaut. Chaque mairie accepte pour son seul
   territoire, ce qui est tout l'intérêt du grain fin sur une crise multi-communes.
2. **La convention** (`DelegationCompetence`) — l'exception, de longue durée, sans crise.

Ce fichier pin les deux, leurs limites (crise close, acceptation non validée, convention
échue), et surtout la **non-régression pour une mairie**, qui doit voir exactement ce qu'elle
voyait avant.
"""
import pytest
from django.test import RequestFactory
from django.utils import timezone

from core.models import (
    Competence,
    Crisis,
    DelegationCompetence,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    Request as Demande,
    RequestType,
    StatutImplication,
    TypeImplication,
)
from core.zone_scoping import (
    _institution_commune_or_400,
    communes_accordees,
    filter_queryset_to_viewer_zone,
    viewer_perimetre,
)

COMMUNE_A = "29026"   # celle de la mairie
COMMUNE_B = "29027"   # une autre commune de la crise
COMMUNE_C = "29028"   # une troisième, jamais accordée


@pytest.fixture
def type_mairie(db):
    return InstitutionType.objects.create(code="MAIRIE_PERIM", libelle="Mairie")


@pytest.fixture
def type_aasc(db):
    return InstitutionType.objects.create(code="AASC_PERIM", libelle="Association agréée")


@pytest.fixture
def mairie(db, type_mairie):
    return Institution.objects.create(
        nom="Mairie perimetre test", type=type_mairie, commune_code=COMMUNE_A)


@pytest.fixture
def aasc(db, type_aasc):
    """Sans commune : c'est tout le problème. Une AASC nationale n'a pas de territoire propre
    et n'en aura jamais."""
    return Institution.objects.create(nom="AASC perimetre test", type=type_aasc)


@pytest.fixture
def crise(db):
    return Crisis.objects.create(
        name="Crise multi-communes", type="INONDATION", location="POINT (-3.98 48.19)",
        zone_communes=[COMMUNE_A, COMMUNE_B, COMMUNE_C],
    )


def _accepter(crise, institution, communes=None, statut=StatutImplication.VALIDEE,
              type_implication=TypeImplication.ACTEUR):
    return ImplicationInstitution.objects.create(
        crise=crise, institution=institution, type_implication=type_implication,
        statut=statut, actif=True, communes=communes or [],
    )


def _convention(source, cible, communes=None, departements=None, **extra):
    competence, _ = Competence.objects.get_or_create(nom="Appui operationnel perimetre")
    return DelegationCompetence.objects.create(
        institution_source=source, institution_cible=cible, competence=competence,
        active=True, communes=communes or [], departements=departements or [], **extra,
    )


def _demande(titre, commune_code):
    """`Request.request_type` est obligatoire : une demande sans type n'existe pas en base."""
    rtype, _ = RequestType.objects.get_or_create(
        type="Besoin perimetre test", defaults={"description": ""})
    return Demande.objects.create(
        title=titre, commune_code=commune_code, request_type=rtype)


def _requete(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


def _compte(create_user, institution, nom, type_compte="SECOURS"):
    user = create_user(username=nom, email=nom, type=type_compte)
    user.institution = institution
    user.save()
    return user


@pytest.mark.django_db
class TestNonRegressionMairie:
    """Une mairie sans rien d'accordé doit voir exactement ce qu'elle voyait avant la refonte."""

    def test_sa_zone_et_rien_d_autre(self, create_user, mairie):
        user = _compte(create_user, mairie, "mairie@perim.fr", "AUT_LOCALE")

        assert viewer_perimetre(_requete(user)) == [("commune", COMMUNE_A)]
        assert communes_accordees(_requete(user)) == []

    def test_le_filtrage_reste_celui_d_avant(self, create_user, mairie):
        user = _compte(create_user, mairie, "mairie-filtre@perim.fr", "AUT_LOCALE")
        _demande("Chez moi", COMMUNE_A)
        _demande("Ailleurs", COMMUNE_C)

        visibles = filter_queryset_to_viewer_zone(_requete(user), Demande.objects.all())

        assert [d.title for d in visibles] == ["Chez moi"]


@pytest.mark.django_db
class TestAascSansRien:
    def test_aucune_zone_donc_rien(self, create_user, aasc):
        """C'est l'état avant toute acceptation — et c'était l'état PERMANENT d'une AASC avant
        la refonte, quelle que soit la crise sur laquelle elle intervenait."""
        user = _compte(create_user, aasc, "aasc-nue@perim.fr")
        _demande("Quelque part", COMMUNE_A)

        assert viewer_perimetre(_requete(user)) is None
        assert filter_queryset_to_viewer_zone(_requete(user), Demande.objects.all()).count() == 0


@pytest.mark.django_db
class TestDroitsParLaCrise:
    def test_acceptee_sur_une_commune_elle_ne_voit_que_celle_la(self, create_user, aasc, crise):
        """Le cœur de la règle : « par commune dans la crise ». Chaque mairie accepte pour son
        seul territoire ; être acceptée par l'une n'ouvre pas celui des autres."""
        user = _compte(create_user, aasc, "aasc-une@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B])
        _demande("Commune B", COMMUNE_B)
        _demande("Commune C", COMMUNE_C)

        assert viewer_perimetre(_requete(user)) == [("commune", COMMUNE_B)]
        visibles = filter_queryset_to_viewer_zone(_requete(user), Demande.objects.all())
        assert [d.title for d in visibles] == ["Commune B"]

    def test_acceptee_sur_plusieurs_communes_elle_les_voit_toutes(self, create_user, aasc, crise):
        user = _compte(create_user, aasc, "aasc-plusieurs@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_A, COMMUNE_B])
        for c, titre in ((COMMUNE_A, "A"), (COMMUNE_B, "B"), (COMMUNE_C, "C")):
            _demande(titre, c)

        visibles = filter_queryset_to_viewer_zone(_requete(user), Demande.objects.all())

        assert sorted(d.title for d in visibles) == ["A", "B"]

    def test_liste_vide_vaut_toute_la_crise(self, create_user, aasc, crise):
        """Une acceptation sans précision ouvre l'ensemble de la zone déclarée : c'est le cas
        d'une crise mono-commune, où exiger de nommer la commune serait une formalité vide."""
        user = _compte(create_user, aasc, "aasc-toute@perim.fr")
        _accepter(crise, aasc, communes=[])

        perimetre = viewer_perimetre(_requete(user))

        assert set(perimetre) == {("commune", COMMUNE_A), ("commune", COMMUNE_B),
                                  ("commune", COMMUNE_C)}

    def test_une_crise_close_n_ouvre_plus_rien(self, create_user, aasc, crise):
        """L'acceptation ne vaut que pour la crise : une fois celle-ci terminée, l'accès au
        territoire se referme de lui-même, sans geste de la mairie."""
        user = _compte(create_user, aasc, "aasc-close@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B])
        crise.end_date = timezone.now()
        crise.save(update_fields=["end_date"])

        assert viewer_perimetre(_requete(user)) is None

    def test_une_acceptation_non_validee_n_ouvre_rien(self, create_user, aasc, crise):
        """Candidater n'est pas être accepté : c'est la validation par la commune qui ouvre."""
        user = _compte(create_user, aasc, "aasc-attente@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B], statut=StatutImplication.EN_ATTENTE)

        assert viewer_perimetre(_requete(user)) is None

    def test_etre_impliquee_ne_suffit_pas(self, create_user, aasc, crise):
        """IMPLIQUE décrit un territoire touché, pas un mandat d'intervention. Seul ACTEUR,
        validé, ouvre des données."""
        user = _compte(create_user, aasc, "aasc-impliquee@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B],
                  type_implication=TypeImplication.IMPLIQUE)

        assert viewer_perimetre(_requete(user)) is None

    def test_une_acceptation_desactivee_n_ouvre_rien(self, create_user, aasc, crise):
        user = _compte(create_user, aasc, "aasc-inactive@perim.fr")
        implication = _accepter(crise, aasc, communes=[COMMUNE_B])
        implication.actif = False
        implication.save(update_fields=["actif"])

        assert viewer_perimetre(_requete(user)) is None


@pytest.mark.django_db
class TestDroitsParConvention:
    def test_une_convention_ouvre_sans_aucune_crise(self, create_user, aasc, mairie):
        """L'exception de longue durée : la mairie accorde une fois, et l'association travaille
        en préparation sans attendre qu'une crise survienne."""
        user = _compte(create_user, aasc, "aasc-convention@perim.fr")
        _convention(mairie, aasc, communes=[COMMUNE_A])

        assert viewer_perimetre(_requete(user)) == [("commune", COMMUNE_A)]

    def test_un_departement_delegue_reste_un_departement(self, create_user, aasc, mairie):
        """Non déplié en communes : le convertir demanderait de requêter le référentiel à
        chaque appel, et perdrait les communes qui y seraient créées ensuite."""
        user = _compte(create_user, aasc, "aasc-departement@perim.fr")
        _convention(mairie, aasc, departements=["29"])

        assert viewer_perimetre(_requete(user)) == [("departement", "29")]

    def test_une_convention_echue_n_ouvre_rien(self, create_user, aasc, mairie):
        user = _compte(create_user, aasc, "aasc-echue@perim.fr")
        _convention(mairie, aasc, communes=[COMMUNE_A],
                    date_fin=timezone.now() - timezone.timedelta(days=1))

        assert viewer_perimetre(_requete(user)) is None

    def test_une_convention_desactivee_n_ouvre_rien(self, create_user, aasc, mairie):
        user = _compte(create_user, aasc, "aasc-conv-inactive@perim.fr")
        convention = _convention(mairie, aasc, communes=[COMMUNE_A])
        convention.active = False
        convention.save(update_fields=["active"])

        assert viewer_perimetre(_requete(user)) is None


@pytest.mark.django_db
class TestReunionDesSources:
    def test_une_mairie_garde_sa_commune_et_gagne_les_accordees(
        self, create_user, mairie, crise
    ):
        """Une mairie peut elle aussi intervenir ailleurs (entraide intercommunale) : les
        droits accordés s'AJOUTENT à son territoire, ils ne le remplacent pas."""
        user = _compte(create_user, mairie, "mairie-entraide@perim.fr", "AUT_LOCALE")
        _accepter(crise, mairie, communes=[COMMUNE_B])

        assert set(viewer_perimetre(_requete(user))) == {
            ("commune", COMMUNE_A), ("commune", COMMUNE_B)}

    def test_les_doublons_sont_reduits(self, create_user, mairie, crise):
        """Sa propre commune ré-accordée par une crise ne doit pas apparaître deux fois : le
        filtre la joindrait à lui-même et dupliquerait les lignes."""
        user = _compte(create_user, mairie, "mairie-doublon@perim.fr", "AUT_LOCALE")
        _accepter(crise, mairie, communes=[COMMUNE_A])

        assert viewer_perimetre(_requete(user)) == [("commune", COMMUNE_A)]

    def test_la_crise_et_la_convention_se_cumulent(self, create_user, aasc, mairie, crise):
        user = _compte(create_user, aasc, "aasc-cumul@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B])
        _convention(mairie, aasc, communes=[COMMUNE_C])

        assert set(viewer_perimetre(_requete(user))) == {
            ("commune", COMMUNE_B), ("commune", COMMUNE_C)}

    def test_une_ligne_couverte_par_deux_zones_n_apparait_qu_une_fois(
        self, create_user, aasc, mairie, crise
    ):
        """Réunir plusieurs zones ne doit pas multiplier les résultats — d'où le distinct()."""
        user = _compte(create_user, aasc, "aasc-distinct@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B])
        _convention(mairie, aasc, communes=[COMMUNE_B])
        _demande("Unique", COMMUNE_B)

        visibles = filter_queryset_to_viewer_zone(_requete(user), Demande.objects.all())

        assert [d.title for d in visibles] == ["Unique"]


@pytest.mark.django_db
class TestChoixDeLaCollectivite:
    """« Vue Ma Collectivité » : une AASC doit pouvoir préciser laquelle elle consulte."""

    def test_le_refus_nomme_les_communes_disponibles(self, create_user, aasc, crise):
        """Nommer les choix dans le refus permet à l'écran de proposer un sélecteur au lieu
        d'annoncer une impasse — et évite un aller-retour de plus."""
        user = _compte(create_user, aasc, "aasc-choix@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B, COMMUNE_C])

        reponse = _institution_commune_or_400(_requete(user))

        assert reponse.status_code == 400
        assert reponse.data["communes_disponibles"] == [COMMUNE_B, COMMUNE_C]
        assert reponse.data["choix_requis"] == "commune"

    def test_sans_aucun_droit_le_refus_le_dit(self, create_user, aasc):
        user = _compte(create_user, aasc, "aasc-sans-droit@perim.fr")

        reponse = _institution_commune_or_400(_requete(user))

        assert reponse.status_code == 400
        assert reponse.data["communes_disponibles"] == []
        assert "accepté" in reponse.data["error"]

    def test_une_commune_accordee_est_acceptee(self, create_user, aasc, crise):
        user = _compte(create_user, aasc, "aasc-precise@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B])
        request = RequestFactory().get("/", {"commune": COMMUNE_B})
        request.user = user

        assert _institution_commune_or_400(request) == COMMUNE_B

    def test_une_commune_non_accordee_est_refusee_en_403(self, create_user, aasc, crise):
        """403 et non 400 : ce n'est pas une saisie malformée, c'est un droit absent. Le
        paramètre choisit parmi des droits, il n'en crée aucun."""
        user = _compte(create_user, aasc, "aasc-interdite@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B])
        request = RequestFactory().get("/", {"commune": COMMUNE_C})
        request.user = user

        reponse = _institution_commune_or_400(request)

        assert reponse.status_code == 403

    def test_une_mairie_reste_sur_sa_commune_sans_parametre(self, create_user, mairie):
        user = _compte(create_user, mairie, "mairie-defaut@perim.fr", "AUT_LOCALE")

        assert _institution_commune_or_400(_requete(user)) == COMMUNE_A

    def test_une_mairie_peut_viser_sa_propre_commune(self, create_user, mairie):
        user = _compte(create_user, mairie, "mairie-sienne@perim.fr", "AUT_LOCALE")
        request = RequestFactory().get("/", {"commune": COMMUNE_A})
        request.user = user

        assert _institution_commune_or_400(request) == COMMUNE_A


@pytest.mark.django_db
class TestCoutDuCalcul:
    """Le périmètre est sur le chemin de lecture de presque toutes les listes, et certains
    sérialiseurs l'interrogent PAR LIGNE. Sans mémoire par requête, lister vingt-cinq demandes
    passait de 15 requêtes SQL à 113 — régression attrapée par
    test_liste_demandes_est_affectee_sans_requete_par_ligne lors de la refonte du 28/10/2026."""

    def test_le_perimetre_n_est_calcule_qu_une_fois_par_requete(
        self, create_user, aasc, crise, django_assert_num_queries
    ):
        user = _compte(create_user, aasc, "aasc-cout@perim.fr")
        _accepter(crise, aasc, communes=[COMMUNE_B])
        request = _requete(user)
        viewer_perimetre(request)  # premier appel : il paie

        with django_assert_num_queries(0):
            for _ in range(20):
                viewer_perimetre(request)

    def test_deux_requetes_distinctes_ne_partagent_pas_la_memoire(
        self, create_user, aasc, crise
    ):
        """La mémoire vit le temps d'une requête HTTP, pas davantage : un droit retiré entre
        deux appels doit être vu au suivant."""
        user = _compte(create_user, aasc, "aasc-memoire@perim.fr")
        implication = _accepter(crise, aasc, communes=[COMMUNE_B])
        assert viewer_perimetre(_requete(user)) == [("commune", COMMUNE_B)]

        implication.actif = False
        implication.save(update_fields=["actif"])

        assert viewer_perimetre(_requete(user)) is None
