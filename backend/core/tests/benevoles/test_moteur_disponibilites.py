"""Un seul moteur de disponibilité : celui à quatre créneaux, clé sur `Offer`.

Correction du 11/11/2026, après une première version qui s'était trompée de moteur. Sylvain :
« Tu as bien pris l'ancien moteur a 4 créneaux par jour sur 15 jours ? » — non, j'avais pris
`DisponibiliteOperationnelle`, une déclaration à la JOURNÉE que seule la grille de
l'association lisait. Le moteur qui décide réellement des mobilisations est
`DisponibiliteOffre`, que lit `/admin/teams` pour constituer une équipe.

Ce que ces tests verrouillent :

1. **Le créneau est l'unité**, pas la journée. Quelqu'un de libre le matin et pris l'après-midi
   est une situation ordinaire ; une déclaration à la journée forcerait à répondre
   « indisponible » et perdrait une demi-journée d'effectif à chaque fois.
2. **Le bénévole a une ressource**, une offre « Bénévolat » — c'est ce qui le fait entrer dans
   le moteur, puisque celui-ci est clé sur `Offer`.
3. **Cette ressource est INTERNE.** `Offer` alimente la carte publique en `AllowAny` :
   publier l'annuaire des adhérents serait l'inverse de la consigne (« seule la réserve
   résilience a le droit de les voir comme ressource »).
4. **La grille de l'association lit les mêmes lignes** que la constitution d'équipe. Deux
   sources pour la même question, c'était pouvoir afficher « disponible » là où l'autre écran
   ne voyait rien.
5. **Le moteur à la journée, lui, était grand ouvert** : `objects.all()` sans permission. On
   pouvait déclarer un inconnu indisponible la veille d'une garde. Corrigé, et vérifié ici.
"""
import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel, ContactInstitution, DisponibiliteOffre,
    DisponibiliteOperationnelle, EchelonEquipe, FicheBenevole, Institution, InstitutionType,
    Offer, OfferType, RoleOperationnel, Team, User, VisibiliteOffre,
)

URL = "/api/mes-disponibilites/"
GRILLE = "/api/disponibilites/grille/"
OFFRES = "/api/offres/"


@pytest.fixture
def asso(db):
    type_aasc = InstitutionType.objects.create(code="AASC", libelle="Association agréée")
    return Institution.objects.create(nom="Reserve essai dispo", type=type_aasc)


@pytest.fixture
def gironde(db, asso):
    return Team.objects.create(
        name="Coordination Departementale Gironde", institution=asso,
        echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="33",
    )


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


def demain():
    return (timezone.localdate() + datetime.timedelta(days=1)).isoformat()


def _membre(create_user, nom, asso, equipe=None, encadrant=False, bureau=False,
            avec_ressource=True):
    """Un membre de l'association, avec sa fiche et sa ressource comme en production."""
    u = create_user(username=f"{nom}@dispo.test", email=f"{nom}@dispo.test",
                    type="UTIL_SIMPLE", first_name=nom.capitalize(), last_name="Durand")
    ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True,
                                      membre_bureau=bureau)
    if equipe is not None:
        equipe.members.add(u)
        if encadrant:
            equipe.membres_encadrement.add(u)
    if avec_ressource:
        from core.fiches_benevoles import ressource_du_benevole

        fiche = FicheBenevole.objects.create(utilisateur=u, adresse="1 rue des Lilas",
                                             commune_code="33063", departement_code="33")
        ressource_du_benevole(fiche, asso)
    return u


@pytest.mark.django_db
class TestLeCreneauEstLUnite:

    def test_la_fiche_ne_porte_aucune_disponibilite(self):
        """Elle porte un volume annuel, qui n'est pas une disponibilité."""
        champs = {f.name for f in FicheBenevole._meta.get_fields()}
        assert "frequence_engagement" in champs
        assert "disponibilite" not in champs

    def test_un_creneau_se_declare_seul(self, create_user, asso, gironde):
        benevole = _membre(create_user, "cre", asso, gironde)

        reponse = _client(benevole).post(
            URL, {"date": demain(), "creneau": "MATIN", "disponible": True}, format="json")

        assert reponse.status_code == 200, reponse.data
        lignes = DisponibiliteOffre.objects.all()
        assert [l.creneau for l in lignes] == ["MATIN"]
        assert lignes[0].offer.author == benevole

    def test_le_creneau_omis_coche_toute_la_journee(self, create_user, asso, gironde):
        """Soixante cases sur quinze jours, personne ne les coche une par une — et une grille
        que personne ne remplit ne sert pas à armer une garde."""
        benevole = _membre(create_user, "jour", asso, gironde)

        reponse = _client(benevole).post(
            URL, {"date": demain(), "disponible": True}, format="json")

        assert reponse.status_code == 200, reponse.data
        assert sorted(DisponibiliteOffre.objects.values_list("creneau", flat=True)) == [
            "MATIN", "MIDI", "NUIT", "SOIR"]

    def test_decocher_SUPPRIME_la_ligne(self, create_user, asso, gironde):
        """« Pas de ligne = indisponible » est la règle de ce moteur depuis l'origine : il n'y
        a pas de ligne « indisponible » à écrire."""
        benevole = _membre(create_user, "dec", asso, gironde)
        client = _client(benevole)
        client.post(URL, {"date": demain(), "creneau": "SOIR", "disponible": True},
                    format="json")

        client.post(URL, {"date": demain(), "creneau": "SOIR", "disponible": False},
                    format="json")

        assert not DisponibiliteOffre.objects.exists()

    def test_recocher_deux_fois_ne_duplique_pas(self, create_user, asso, gironde):
        benevole = _membre(create_user, "idem", asso, gironde)
        client = _client(benevole)
        for _ in range(2):
            client.post(URL, {"date": demain(), "creneau": "MIDI", "disponible": True},
                        format="json")

        assert DisponibiliteOffre.objects.count() == 1

    def test_la_grille_personnelle_couvre_quinze_jours_et_quatre_creneaux(
            self, create_user, asso, gironde):
        benevole = _membre(create_user, "quinze", asso, gironde)

        reponse = _client(benevole).get(URL)

        assert reponse.status_code == 200, reponse.data
        assert len(reponse.data["jours"]) == 15
        assert reponse.data["creneaux"] == ["MATIN", "MIDI", "SOIR", "NUIT"]
        assert set(reponse.data["jours"][0]["creneaux"]) == {"MATIN", "MIDI", "SOIR", "NUIT"}

    def test_sans_ressource_on_le_dit(self, create_user, asso):
        """Quelqu'un qui n'a pas encore de fiche n'a pas de ressource, donc rien à déclarer :
        l'écran doit pouvoir le dire plutôt que d'afficher une grille vide inexpliquée."""
        sans = _membre(create_user, "sans", asso, avec_ressource=False)

        lecture = _client(sans).get(URL)
        ecriture = _client(sans).post(URL, {"date": demain(), "disponible": True},
                                      format="json")

        assert lecture.data["ressources"] == []
        assert lecture.data["jours"] == []
        assert ecriture.status_code == 400


@pytest.mark.django_db
class TestLaRessourceEstInterne:

    def test_l_offre_du_benevole_est_interne_et_rattachee(self, create_user, asso):
        benevole = _membre(create_user, "int", asso)

        offre = Offer.objects.get(author=benevole)
        assert offre.visibilite == VisibiliteOffre.INTERNE
        assert offre.institution == asso
        assert offre.offer_type.type == "Bénévolat"

    def test_le_titre_n_ecrit_PAS_l_etat_civil_en_clair(self, create_user, asso):
        """`Offer.title` n'est pas chiffré (champ de recherche et de tri) : y mettre le nom
        complet sortirait en clair ce que les champs voisins chiffrent."""
        benevole = _membre(create_user, "titre", asso)

        offre = Offer.objects.get(author=benevole)
        assert offre.title == "Bénévole — Titre D."
        assert "Durand" not in offre.title

    def test_un_anonyme_ne_voit_PAS_la_ressource(self, create_user, asso):
        """Le point qui compte : `OfferViewSet` est en AllowAny et alimente la carte
        publique."""
        benevole = _membre(create_user, "anon", asso)
        offre = Offer.objects.get(author=benevole)

        reponse = APIClient().get(OFFRES)

        assert str(offre.id) not in _ids(reponse)

    def test_une_autre_institution_ne_la_voit_pas(self, create_user, asso):
        benevole = _membre(create_user, "autre", asso)
        offre = Offer.objects.get(author=benevole)
        type_mairie = InstitutionType.objects.create(code="MAIRIE_OFF", libelle="Mairie")
        mairie = Institution.objects.create(nom="Mairie off", type=type_mairie,
                                            commune_code="29026")
        agent = create_user(username="agent@dispo.test", email="agent@dispo.test",
                            type="AUT_LOCALE")
        agent.institution = mairie
        agent.save(update_fields=["institution"])

        reponse = _client(agent).get(OFFRES)

        assert str(offre.id) not in _ids(reponse)

    def test_son_association_la_voit(self, create_user, asso):
        """C'est la contrepartie : « seule la réserve résilience a le droit de les voir comme
        ressource » — mais elle, elle doit les voir."""
        benevole = _membre(create_user, "vu", asso)
        offre = Offer.objects.get(author=benevole)
        bureau = _membre(create_user, "bureau", asso, bureau=True)

        reponse = _client(bureau).get(OFFRES)

        assert str(offre.id) in _ids(reponse)

    def test_le_titulaire_voit_la_sienne(self, create_user, asso):
        benevole = _membre(create_user, "moi", asso)
        offre = Offer.objects.get(author=benevole)

        assert str(offre.id) in _ids(_client(benevole).get(OFFRES))

    def test_une_offre_citoyenne_reste_publique(self, db):
        """Le défaut est permissif : ce champ ne peut pas réduire par accident ce qui était
        déjà visible."""
        type_offre, _ = OfferType.objects.get_or_create(type="Hébergement")
        citoyenne = Offer.objects.create(
            title="Chambre libre", offer_type=type_offre,
            first_name_offer="Jean", last_name_offer="Citoyen",
            email_offer="jean@exemple.invalide",
        )

        assert citoyenne.visibilite == VisibiliteOffre.PUBLIQUE
        assert str(citoyenne.id) in _ids(APIClient().get(OFFRES))

    def test_l_import_cree_la_ressource(self, create_user, asso, gironde, rf):
        from core.imports import importer_benevoles_association

        requete = rf.post("/api/imports/benevoles/")
        requete.user = create_user(username="imp@dispo.test", email="imp@dispo.test",
                                   type="ADMIN")
        importer_benevoles_association(
            lignes=[{"EMAIL": "nouveau@dispo.test", "NOM": "Durand", "PRENOM": "Marie"}],
            mapping={"email": "EMAIL", "nom": "NOM", "prenom": "PRENOM"},
            institution=asso, request=requete, inviter=False, geolocaliser=False,
        )

        nouveau = User.objects.get(username="nouveau@dispo.test")
        offre = Offer.objects.get(author=nouveau)
        assert offre.visibilite == VisibiliteOffre.INTERNE
        assert offre.institution == asso

    def test_la_ressource_suit_un_changement_de_nom(self, create_user, asso):
        """Sans ça, un bénévole qui corrige son nom resterait cherchable sous l'ancien."""
        from core.fiches_benevoles import ressource_du_benevole

        benevole = _membre(create_user, "nom", asso)
        fiche = FicheBenevole.objects.get(utilisateur=benevole)
        benevole.last_name = "Martin"
        benevole.save(update_fields=["last_name"])

        ressource_du_benevole(fiche, asso)

        assert Offer.objects.filter(author=benevole).count() == 1
        assert Offer.objects.get(author=benevole).title == "Bénévole — Nom M."


@pytest.mark.django_db
class TestLesCreneauxSontCloisonnes:
    """`DisponibiliteOffreViewSet` listait `objects.all()` en `AllowAny`.

    Un visiteur anonyme pouvait énumérer les créneaux de TOUTES les offres — donc, dès qu'on y
    fait entrer les bénévoles, reconstituer qui est mobilisable et quand sans jamais voir une
    seule fiche. Corrigé avant d'y faire entrer quiconque."""

    @pytest.fixture
    def creneau_interne(self, create_user, asso, gironde):
        benevole = _membre(create_user, "cl", asso, gironde)
        _client(benevole).post(URL, {"date": demain(), "creneau": "MATIN",
                                     "disponible": True}, format="json")
        return benevole, DisponibiliteOffre.objects.get()

    def test_un_anonyme_ne_les_enumere_pas(self, creneau_interne):
        _, ligne = creneau_interne

        reponse = APIClient().get("/api/disponibilites-offres/")

        assert str(ligne.id) not in _ids(reponse)

    def test_une_autre_institution_ne_les_voit_pas(self, creneau_interne, create_user):
        _, ligne = creneau_interne
        type_mairie = InstitutionType.objects.create(code="MAIRIE_CRE", libelle="Mairie")
        mairie = Institution.objects.create(nom="Mairie creneaux", type=type_mairie,
                                            commune_code="29026")
        agent = create_user(username="agent2@dispo.test", email="agent2@dispo.test",
                            type="AUT_LOCALE")
        agent.institution = mairie
        agent.save(update_fields=["institution"])

        assert str(ligne.id) not in _ids(_client(agent).get("/api/disponibilites-offres/"))

    def test_son_association_les_voit(self, creneau_interne, create_user, asso):
        """C'est la contrepartie : le planning de /admin/teams doit pouvoir les lire."""
        _, ligne = creneau_interne
        bureau = _membre(create_user, "burc", asso, bureau=True)

        assert str(ligne.id) in _ids(_client(bureau).get("/api/disponibilites-offres/"))

    def test_les_creneaux_d_une_offre_publique_restent_publics(self, db):
        """Pas de régression sur le formulaire citoyen : une offre publique et ses créneaux se
        lisent toujours sans compte."""
        type_offre, _ = OfferType.objects.get_or_create(type="Hébergement")
        citoyenne = Offer.objects.create(
            title="Chambre libre", offer_type=type_offre,
            first_name_offer="Jean", last_name_offer="Citoyen",
            email_offer="jean2@exemple.invalide",
        )
        ligne = DisponibiliteOffre.objects.create(
            offer=citoyenne, date=timezone.localdate(), creneau="MATIN")

        assert str(ligne.id) in _ids(APIClient().get("/api/disponibilites-offres/"))


@pytest.mark.django_db
class TestLaGrilleLitLeMemeMoteur:

    def test_le_creneau_declare_apparait_dans_la_grille_du_bureau(self, create_user, asso,
                                                                  gironde):
        """Le point de tout l'exercice : ce que le bénévole coche est ce que lit la
        constitution d'équipe."""
        benevole = _membre(create_user, "grille", asso, gironde)
        bureau = _membre(create_user, "bur", asso, bureau=True)
        _client(benevole).post(URL, {"date": demain(), "creneau": "MATIN",
                                     "disponible": True}, format="json")

        reponse = _client(bureau).get(GRILLE, {"institution": str(asso.id)})

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["creneaux"] == ["MATIN", "MIDI", "SOIR", "NUIT"]
        ligne = next(m for m in reponse.data["membres"]
                     if str(m["utilisateur"]) == str(benevole.id))
        case = next(j for j in ligne["jours"] if str(j["date"]) == demain())
        assert case["creneaux"]["MATIN"] is True
        assert case["creneaux"]["SOIR"] is False

    def test_la_grille_distingue_le_silence_du_refus(self, create_user, asso, gironde):
        """Ce moteur ne stocke pas de « non renseigné » : une grille vierge et une grille tout
        décochée sont identiques en base. `a_declare` dit qui relancer."""
        muet = _membre(create_user, "muet", asso, gironde)
        parlant = _membre(create_user, "parlant", asso, gironde)
        bureau = _membre(create_user, "bur2", asso, bureau=True)
        _client(parlant).post(URL, {"date": demain(), "disponible": True}, format="json")

        reponse = _client(bureau).get(GRILLE, {"institution": str(asso.id)})
        par_id = {str(m["utilisateur"]): m for m in reponse.data["membres"]}

        assert par_id[str(muet.id)]["a_declare"] is False
        assert par_id[str(parlant.id)]["a_declare"] is True

    def test_la_frequence_d_engagement_ne_remplit_aucune_case(self, create_user, asso,
                                                              gironde):
        """« Environ 10 jours par an » ne dit rien du 5 novembre."""
        benevole = _membre(create_user, "freq", asso, gironde)
        fiche = FicheBenevole.objects.get(utilisateur=benevole)
        fiche.frequence_engagement = "FREQUENTE"
        fiche.save(update_fields=["frequence_engagement"])
        bureau = _membre(create_user, "bur3", asso, bureau=True)

        reponse = _client(bureau).get(GRILLE, {"institution": str(asso.id)})

        ligne = next(m for m in reponse.data["membres"]
                     if str(m["utilisateur"]) == str(benevole.id))
        assert all(not any(j["creneaux"].values()) for j in ligne["jours"])


def _ids(reponse):
    """Les identifiants rendus, que la vue pagine ou non."""
    donnees = reponse.data
    lignes = donnees["results"] if isinstance(donnees, dict) else donnees
    return [str(ligne["id"]) for ligne in lignes]


@pytest.mark.django_db
class TestCloisonnementDuMoteurJournalier:
    """`DisponibiliteOperationnelle` servait `objects.all()` sans permission ni filtrage.

    Ce modèle n'est plus celui des membres, mais il reste exposé et la dette était réelle :
    tout compte connecté lisait les disponibilités de la plateforme entière et **écrivait
    celles de n'importe qui** — `prendre_permanence` et `quitter_permanence` appelaient
    `get_object()` sur une table non filtrée."""

    @pytest.fixture
    def declaration(self, create_user, asso, gironde):
        titulaire = _membre(create_user, "tit", asso, gironde)
        role, _ = RoleOperationnel.objects.get_or_create(
            code="INTERVENANT", defaults={"libelle": "Intervenant"})
        affectation = AffectationRoleOperationnel.objects.create(
            utilisateur=titulaire, institution=asso, role=role)
        return titulaire, DisponibiliteOperationnelle.objects.create(
            affectation=affectation, disponible=True)

    def test_un_inconnu_ne_les_voit_pas(self, declaration, create_user):
        _, ligne = declaration
        etranger = create_user(username="etr@dispo.test", email="etr@dispo.test",
                               type="AUT_LOCALE")

        reponse = _client(etranger).get("/api/disponibilites/")

        assert str(ligne.id) not in _ids(reponse)

    def test_un_inconnu_ne_peut_PAS_declarer_quelqu_un_indisponible(self, declaration,
                                                                    create_user):
        _, ligne = declaration
        etranger = create_user(username="etr2@dispo.test", email="etr2@dispo.test",
                               type="AUT_LOCALE")

        reponse = _client(etranger).post(
            f"/api/disponibilites/{ligne.id}/quitter_permanence/")

        assert reponse.status_code in (403, 404)
        ligne.refresh_from_db()
        assert ligne.disponible is True

    def test_le_titulaire_voit_les_siennes(self, declaration):
        titulaire, ligne = declaration

        assert str(ligne.id) in _ids(_client(titulaire).get("/api/disponibilites/"))

    def test_l_encadrant_de_son_equipe_y_accede(self, declaration, create_user, asso,
                                                gironde):
        _, ligne = declaration
        encadrant = _membre(create_user, "enc", asso, gironde, encadrant=True)

        assert str(ligne.id) in _ids(_client(encadrant).get("/api/disponibilites/"))
