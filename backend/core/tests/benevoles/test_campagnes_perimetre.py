"""Périmètre des campagnes et ciblage large (demandes de Sylvain du 14/11/2026).

1. **Chacun reste dans son institution.** Un membre ne lit ni ne mène les campagnes d'une
   autre, et un simple adhérent ne lit pas celles de la sienne.
2. **L'administrateur choisit son institution** : aucune ne lui est attribuée d'office.
3. **Les mairies aussi** : une campagne n'est pas réservée aux associations.
4. **Taper large** : un dossier incomplet n'écarte pas ; une information contraire, si.
"""
import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.campagnes_disponibilite import constituer_les_cibles, peut_lancer_campagne
from core.models import (
    CampagneDisponibilite, CibleCampagne, Competence, ContactInstitution, EchelonCiblage,
    EchelonEquipe, FicheBenevole, Institution, InstitutionType, MotifCampagne, Offer,
    Qualification, Team,
)

URL = "/api/campagnes-disponibilite/"


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def asso(db):
    itype = InstitutionType.objects.create(code="AASC", libelle="Association agréée")
    return Institution.objects.create(nom="Reserve essai perimetre", type=itype)


@pytest.fixture
def autre_asso(asso):
    return Institution.objects.create(nom="Autre association essai", type=asso.type)


@pytest.fixture
def mairie(db):
    itype = InstitutionType.objects.create(code="MAIRIE_ESSAI", libelle="Mairie")
    return Institution.objects.create(nom="Mairie essai perimetre", type=itype)


def _membre(create_user, nom, institution, *, type="UTIL_SIMPLE", bureau=False, **contact):
    u = create_user(username=f"{nom}@perim.test", email=f"{nom}@perim.test", type=type,
                    first_name=nom.capitalize(), last_name=nom.upper())
    ContactInstitution.objects.create(institution=institution, utilisateur=u, actif=True,
                                      membre_bureau=bureau, **contact)
    return u


def _avec_fiche(u, institution, *, departement="33", competences=()):
    from core.fiches_benevoles import ressource_du_benevole

    fiche = FicheBenevole.objects.create(
        utilisateur=u, adresse="1 rue des Lilas", commune_code="33063",
        departement_code=departement, region_code="75",
    )
    offre, _ = ressource_du_benevole(fiche, institution)
    if competences:
        offre.competences.set(competences)
    return offre


def _campagne(institution, **kwargs):
    defauts = dict(
        institution=institution, intitule="Vigilance", motif=MotifCampagne.CRISE_A_VENIR,
        periode_debut=timezone.localdate() + datetime.timedelta(days=2),
        periode_fin=timezone.localdate() + datetime.timedelta(days=7),
        echelon=EchelonCiblage.NATIONAL, environment="PROD",
    )
    defauts.update(kwargs)
    return CampagneDisponibilite.objects.create(**defauts)


def _corps(institution, **kwargs):
    corps = {
        "institution": str(institution.id), "intitule": "Vigilance", "motif": "CRISE_A_VENIR",
        "periode_debut": str(timezone.localdate() + datetime.timedelta(days=2)),
        "periode_fin": str(timezone.localdate() + datetime.timedelta(days=7)),
        "echelon": "NATIONAL",
    }
    corps.update(kwargs)
    return corps


def _ids(reponse):
    donnees = reponse.json()
    lignes = donnees["results"] if isinstance(donnees, dict) else donnees
    return {ligne["id"] for ligne in lignes}


@pytest.mark.django_db
class TestChacunDansSonInstitution:

    def test_le_bureau_ne_voit_que_les_campagnes_de_son_institution(
            self, create_user, asso, autre_asso):
        chez_moi, ailleurs = _campagne(asso), _campagne(autre_asso)
        bureau = _membre(create_user, "bureau", asso, bureau=True)
        vus = _ids(_client(bureau).get(URL))
        assert str(chez_moi.id) in vus and str(ailleurs.id) not in vus

    def test_un_simple_adherent_ne_lit_pas_les_campagnes_de_son_association(
            self, create_user, asso):
        campagne = _campagne(asso)
        adherent = _membre(create_user, "adherent", asso)
        client = _client(adherent)
        assert _ids(client.get(URL)) == set()
        assert client.get(f"{URL}{campagne.id}/cibles/").status_code == 404

    def test_le_bureau_ne_cree_pas_chez_une_autre(self, create_user, asso, autre_asso):
        bureau = _membre(create_user, "bureau", asso, bureau=True)
        reponse = _client(bureau).post(URL, _corps(autre_asso), format="json")
        assert reponse.status_code == 403

    def test_une_campagne_ne_change_pas_d_institution(self, create_user, asso, autre_asso):
        """Sinon le droit, jugé sur l'institution d'origine, ouvrait toutes les autres."""
        bureau = _membre(create_user, "bureau", asso, bureau=True)
        campagne = _campagne(asso)
        reponse = _client(bureau).patch(
            f"{URL}{campagne.id}/", {"institution": str(autre_asso.id)}, format="json")
        assert reponse.status_code == 400
        campagne.refresh_from_db()
        assert campagne.institution_id == asso.id

    def test_une_equipe_d_une_autre_institution_est_refusee(
            self, create_user, asso, autre_asso):
        bureau = _membre(create_user, "bureau", asso, bureau=True)
        equipe = Team.objects.create(name="Ailleurs", institution=autre_asso,
                                     echelon=EchelonEquipe.DEPARTEMENTAL, environment="PROD")
        reponse = _client(bureau).post(
            URL, _corps(asso, equipe=str(equipe.id)), format="json")
        assert reponse.status_code in (400, 403)

    def test_un_encadrant_voit_les_campagnes_de_sa_branche_seulement(
            self, create_user, asso):
        gironde = Team.objects.create(name="Gironde", institution=asso,
                                      echelon=EchelonEquipe.DEPARTEMENTAL, environment="PROD")
        encadrant = _membre(create_user, "encadrant", asso)
        gironde.membres_encadrement.add(encadrant)
        la_sienne, nationale = _campagne(asso, equipe=gironde), _campagne(asso)
        vus = _ids(_client(encadrant).get(URL))
        assert str(la_sienne.id) in vus and str(nationale.id) not in vus

    def test_les_institutions_proposees_sont_celles_qu_on_pilote(
            self, create_user, asso, autre_asso):
        bureau = _membre(create_user, "bureau", asso, bureau=True)
        ContactInstitution.objects.create(institution=autre_asso, utilisateur=bureau,
                                          actif=True)   # simple adhérent là-bas
        donnees = _client(bureau).get(f"{URL}institutions/").json()
        assert [i["id"] for i in donnees["institutions"]] == [str(asso.id)]
        assert donnees["institutions"][0]["portee"] == "toute"
        assert donnees["administrateur"] is False


@pytest.mark.django_db
class TestLAdministrateurChoisit:

    def test_il_peut_se_placer_dans_n_importe_quelle_institution(
            self, create_user, asso, autre_asso, mairie):
        admin = create_user(username="admin@perim.test", email="admin@perim.test",
                            type="ADMIN")
        donnees = _client(admin).get(f"{URL}institutions/").json()
        assert donnees["administrateur"] is True
        assert {str(asso.id), str(autre_asso.id), str(mairie.id)} <= {
            i["id"] for i in donnees["institutions"]}

        cherche = _client(admin).get(f"{URL}institutions/?q=mairie essai").json()
        assert [i["id"] for i in cherche["institutions"]] == [str(mairie.id)]

    def test_le_filtre_d_institution_est_applique_par_le_serveur(
            self, create_user, asso, autre_asso):
        admin = create_user(username="admin@perim.test", email="admin@perim.test",
                            type="ADMIN")
        chez_a, chez_b = _campagne(asso), _campagne(autre_asso)
        vus = _ids(_client(admin).get(f"{URL}?institution={asso.id}"))
        assert vus == {str(chez_a.id)} and str(chez_b.id) not in vus

    def test_un_filtre_mal_forme_ne_rend_rien_plutot_que_tout(self, create_user, asso):
        admin = create_user(username="admin@perim.test", email="admin@perim.test",
                            type="ADMIN")
        _campagne(asso)
        assert _ids(_client(admin).get(f"{URL}?institution=nimporte")) == set()


@pytest.mark.django_db
class TestLesMairiesAussi:

    def test_un_agent_rattache_a_la_mairie_peut_lancer(self, create_user, mairie):
        agent = _membre(create_user, "agent", mairie, type="AUT_LOCALE")
        assert peut_lancer_campagne(agent, mairie)
        reponse = _client(agent).post(URL, _corps(mairie), format="json")
        assert reponse.status_code == 201, reponse.content

    def test_un_habitant_rattache_a_la_mairie_ne_peut_pas(self, create_user, mairie):
        habitant = _membre(create_user, "habitant", mairie)
        assert not peut_lancer_campagne(habitant, mairie)

    def test_un_agent_d_une_autre_mairie_ne_peut_pas(self, create_user, mairie):
        voisine = Institution.objects.create(nom="Mairie voisine essai", type=mairie.type)
        agent = _membre(create_user, "agent", voisine, type="AUT_LOCALE")
        assert not peut_lancer_campagne(agent, mairie)

    def test_dans_une_association_le_type_de_compte_ne_suffit_pas(self, create_user, asso):
        """Un adhérent promu « secours » n'administre pas l'association."""
        secouriste = _membre(create_user, "secouriste", asso, type="SECOURS")
        assert not peut_lancer_campagne(secouriste, asso)

    def test_l_entree_du_menu_suit_le_droit(self, create_user, asso, mairie):
        agent = _membre(create_user, "agent", mairie, type="AUT_LOCALE")
        adherent = _membre(create_user, "adherent", asso)
        assert _client(agent).get("/api/me/").json()["acces_campagnes"] is True
        assert _client(adherent).get("/api/me/").json()["acces_campagnes"] is False


@pytest.mark.django_db
class TestTaperLarge:

    def test_un_membre_sans_fiche_est_retenu_et_recoit_une_ressource(
            self, create_user, asso):
        avec = _membre(create_user, "avec", asso)
        _avec_fiche(avec, asso)
        sans = _membre(create_user, "sans", asso)

        strict = _campagne(asso)
        constituer_les_cibles(strict)
        assert set(CibleCampagne.objects.filter(campagne=strict).values_list(
            "utilisateur_id", flat=True)) == {avec.id}

        large = _campagne(asso, ciblage_large=True)
        bilan = constituer_les_cibles(large)
        assert set(CibleCampagne.objects.filter(campagne=large).values_list(
            "utilisateur_id", flat=True)) == {avec.id, sans.id}
        assert bilan["a_completer"] == 1
        # Sans ressource il ne pourrait pas répondre : elle est créée, interne et vide.
        cible = CibleCampagne.objects.get(campagne=large, utilisateur=sans)
        assert cible.ressource is not None
        assert cible.ressource.visibilite == "INTERNE"
        assert Offer.objects.filter(author=sans, institution=asso).count() == 1

    def test_toutes_les_competences_cochees_n_ecartent_pas_un_dossier_vide(
            self, create_user, asso):
        pompage = Competence.objects.create(nom="Pompage essai")
        bucheron = Competence.objects.create(nom="Bucheronnage essai")
        saisi = _membre(create_user, "saisi", asso)
        _avec_fiche(saisi, asso, competences=[pompage])
        vide = _membre(create_user, "vide", asso)
        _avec_fiche(vide, asso)

        strict = _campagne(asso)
        strict.competences.set([pompage, bucheron])
        constituer_les_cibles(strict)
        assert CibleCampagne.objects.filter(campagne=strict).count() == 1

        large = _campagne(asso, ciblage_large=True)
        large.competences.set([pompage, bucheron])
        constituer_les_cibles(large)
        assert CibleCampagne.objects.filter(campagne=large).count() == 2

    def test_une_competence_declaree_qui_ne_correspond_pas_ecarte_toujours(
            self, create_user, asso):
        pompage = Competence.objects.create(nom="Pompage essai")
        bucheron = Competence.objects.create(nom="Bucheronnage essai")
        autre = _membre(create_user, "autre", asso)
        _avec_fiche(autre, asso, competences=[bucheron])

        large = _campagne(asso, ciblage_large=True)
        large.competences.set([pompage])
        constituer_les_cibles(large)
        assert CibleCampagne.objects.filter(campagne=large).count() == 0

    def test_un_titre_non_enregistre_n_ecarte_pas(self, create_user, asso):
        pse1 = Qualification.objects.create(nom="PSE1 essai")
        membre = _membre(create_user, "papier", asso)
        _avec_fiche(membre, asso)

        strict = _campagne(asso)
        strict.qualifications.set([pse1])
        constituer_les_cibles(strict)
        assert CibleCampagne.objects.filter(campagne=strict).count() == 0

        large = _campagne(asso, ciblage_large=True)
        large.qualifications.set([pse1])
        bilan = constituer_les_cibles(large)
        assert CibleCampagne.objects.filter(campagne=large).count() == 1
        assert bilan["a_completer"] == 1

    def test_une_adresse_hors_du_territoire_ecarte_une_adresse_absente_non(
            self, create_user, asso):
        gironde = _membre(create_user, "gironde", asso)
        _avec_fiche(gironde, asso, departement="33")
        landes = _membre(create_user, "landes", asso)
        _avec_fiche(landes, asso, departement="40")
        sans_adresse = _membre(create_user, "sansadresse", asso)

        large = _campagne(asso, ciblage_large=True, echelon=EchelonCiblage.DEPARTEMENT,
                          territoire_code="33")
        constituer_les_cibles(large)
        assert set(CibleCampagne.objects.filter(campagne=large).values_list(
            "utilisateur_id", flat=True)) == {gironde.id, sans_adresse.id}

    def test_conge_et_sorti_restent_ecartes(self, create_user, asso):
        _membre(create_user, "conge", asso, statut="CONGE")
        _membre(create_user, "sorti", asso, statut="SORTI")
        large = _campagne(asso, ciblage_large=True)
        constituer_les_cibles(large)
        assert CibleCampagne.objects.filter(campagne=large).count() == 0

    def test_personne_hors_de_l_institution_meme_membre_d_une_de_ses_equipes(
            self, create_user, mairie):
        """« Pourquoi choisir du personnel hors de son institution ? Non. »"""
        renfort = create_user(username="renfort@perim.test", email="renfort@perim.test",
                              type="UTIL_SIMPLE")
        reserviste = _membre(create_user, "reserviste", mairie)
        reserve = Team.objects.create(name="Reserve communale essai", institution=mairie,
                                      echelon=EchelonEquipe.DEPARTEMENTAL, environment="PROD")
        reserve.members.add(renfort, reserviste)

        for equipe in (None, reserve):
            large = _campagne(mairie, ciblage_large=True, equipe=equipe)
            constituer_les_cibles(large)
            assert set(CibleCampagne.objects.filter(campagne=large).values_list(
                "utilisateur_id", flat=True)) == {reserviste.id}
        assert not Offer.objects.filter(author=renfort).exists()

    def test_un_critere_inapplicable_reste_une_erreur(self, create_user, asso):
        from core.ciblage_benevoles import CritereInapplicable

        _membre(create_user, "quelquun", asso)
        large = _campagne(asso, ciblage_large=True, echelon=EchelonCiblage.RAYON_CRISE,
                          rayon_km=30)
        with pytest.raises(CritereInapplicable):
            constituer_les_cibles(large)
