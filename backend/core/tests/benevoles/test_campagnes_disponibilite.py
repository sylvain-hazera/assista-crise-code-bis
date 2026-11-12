"""Campagnes de disponibilité : ciblage, envoi, réponses, rotations.

Demande de Sylvain du 11/11/2026. Ce que ces tests verrouillent, dans l'ordre d'importance :

1. **Un critère qui ne peut pas s'appliquer est une ERREUR.** C'est le test qui compte le plus :
   un filtre silencieusement sans effet n'écarte personne, donc la campagne part à toute
   l'association en croyant viser trente personnes. On ne peut pas « dé-écrire » à 400
   personnes.
2. **Les titres exigés se CUMULENT.** Deux `filter()` sur la même relation inverse se
   satisfont de deux lignes différentes : sans le compte distinct, quelqu'un qui a deux fois le
   permis passerait pour quelqu'un qui a le permis ET le PSE1 — et partirait sans le titre
   requis.
3. **La période est en base**, et c'est elle que voit le bénévole en cliquant le lien. Sinon il
   répond sur ses quinze prochains jours, c'est-à-dire à une autre question.
4. **Zéro créneau est une réponse.** « Je ne suis pas disponible » n'est pas un silence : les
   confondre fait relancer quelqu'un qui a déjà répondu non.
5. **Les rotations ne reprennent pas les mêmes personnes du premier au dernier jour** — c'est
   leur raison d'être — et **rien n'est confirmé par le calcul**.
"""
import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.ciblage_benevoles import CritereInapplicable, cibler
from core.models import (
    AffectationRotation, CampagneDisponibilite, CibleCampagne, Competence, ContactInstitution,
    Crisis, DisponibiliteOffre, EchelonCiblage, EtatCible, FicheBenevole, Institution,
    InstitutionType, MotifCampagne, Qualification, QualificationMembre, StatutAffectationRotation,
    StatutCampagne, StatutQualification, Team, EchelonEquipe,
)

URL = "/api/campagnes-disponibilite/"


@pytest.fixture
def asso(db):
    itype = InstitutionType.objects.create(code="AASC", libelle="Association agréée")
    return Institution.objects.create(nom="Reserve essai campagne", type=itype)


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


def _benevole(create_user, nom, asso, *, departement="33", commune="33063",
              competences=(), bureau=False, equipe=None, point=None):
    """Un membre avec sa fiche et sa ressource, comme en production."""
    from core.fiches_benevoles import ressource_du_benevole

    u = create_user(username=f"{nom}@camp.test", email=f"{nom}@camp.test",
                    type="UTIL_SIMPLE", first_name=nom.capitalize(), last_name=nom.upper())
    ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True,
                                      membre_bureau=bureau)
    fiche = FicheBenevole.objects.create(
        utilisateur=u, adresse="1 rue des Lilas", commune_code=commune,
        departement_code=departement, region_code="75", location=point,
    )
    offre, _ = ressource_du_benevole(fiche, asso)
    if competences:
        offre.competences.set(competences)
    if equipe is not None:
        equipe.members.add(u)
    return u, offre


def _campagne(asso, **kwargs):
    defauts = dict(
        institution=asso, intitule="Vigilance orange", motif=MotifCampagne.CRISE_A_VENIR,
        periode_debut=timezone.localdate() + datetime.timedelta(days=2),
        periode_fin=timezone.localdate() + datetime.timedelta(days=7),
        echelon=EchelonCiblage.NATIONAL, environment="PROD",
    )
    defauts.update(kwargs)
    return CampagneDisponibilite.objects.create(**defauts)


@pytest.mark.django_db
class TestUnCritereInapplicableEstUneErreur:
    """LE test du module : un filtre sans effet ÉLARGIT la cible."""

    def test_un_rayon_sans_crise_est_refuse(self, asso):
        with pytest.raises(CritereInapplicable):
            cibler(asso, "PROD", echelon=EchelonCiblage.RAYON_CRISE, rayon_km=30)

    def test_un_rayon_sans_distance_est_refuse(self, asso, db):
        from django.contrib.gis.geos import Point

        crise = Crisis.objects.create(name="Crue", environment="PROD",
                                      location=Point(-0.57, 44.84, srid=4326))
        with pytest.raises(CritereInapplicable):
            cibler(asso, "PROD", echelon=EchelonCiblage.RAYON_CRISE, crise=crise)

    def test_un_departement_sans_code_est_refuse(self, asso):
        with pytest.raises(CritereInapplicable):
            cibler(asso, "PROD", echelon=EchelonCiblage.DEPARTEMENT)

    def test_une_zone_de_defense_inconnue_est_refusee(self, asso):
        with pytest.raises(CritereInapplicable):
            cibler(asso, "PROD", echelon=EchelonCiblage.ZONE_DEFENSE,
                   territoire_code="ZD-INEXISTANTE")


@pytest.mark.django_db
class TestCiblageGeographique:

    def test_national_prend_tout_le_monde(self, create_user, asso):
        _benevole(create_user, "a", asso, departement="33")
        _benevole(create_user, "b", asso, departement="74")

        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL).count() == 2

    def test_le_departement_filtre(self, create_user, asso):
        _benevole(create_user, "c", asso, departement="33")
        _benevole(create_user, "d", asso, departement="74")

        retenus = cibler(asso, "PROD", echelon=EchelonCiblage.DEPARTEMENT,
                         territoire_code="33")

        assert [o.departement_code for o in retenus] == ["33"]

    def test_la_zone_de_defense_prend_ses_departements(self, create_user, asso):
        """La zone Sud-Ouest contient la Gironde : c'est `core/zones_defense.py` qui le dit,
        et c'est la table que la commande d'arborescence utilise déjà."""
        _benevole(create_user, "e", asso, departement="33")
        _benevole(create_user, "f", asso, departement="74")

        retenus = cibler(asso, "PROD", echelon=EchelonCiblage.ZONE_DEFENSE,
                         territoire_code="ZD-SUD-OUEST")

        assert [o.departement_code for o in retenus] == ["33"]

    def test_un_membre_sorti_n_est_jamais_cible(self, create_user, asso):
        """Le solliciter serait au mieux inutile, au pire blessant."""
        u, _ = _benevole(create_user, "g", asso)
        ContactInstitution.objects.filter(institution=asso, utilisateur=u).update(
            statut=ContactInstitution.StatutMembre.SORTI)

        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL).count() == 0

    def test_un_membre_en_conge_n_est_pas_cible(self, create_user, asso):
        u, _ = _benevole(create_user, "h", asso)
        ContactInstitution.objects.filter(institution=asso, utilisateur=u).update(
            statut=ContactInstitution.StatutMembre.CONGE)

        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL).count() == 0


@pytest.mark.django_db
class TestCiblageParTitres:

    def test_les_titres_exiges_se_CUMULENT(self, create_user, asso):
        """Sans le compte distinct, deux lignes du MÊME titre satisferaient deux critères."""
        permis = Qualification.objects.create(nom="Permis C campagne")
        pse1 = Qualification.objects.create(nom="PSE1 campagne")
        complet, _ = _benevole(create_user, "i", asso)
        partiel, _ = _benevole(create_user, "j", asso)
        for titre in (permis, pse1):
            QualificationMembre.objects.create(
                utilisateur=complet, qualification=titre, environment="PROD",
                statut=StatutQualification.VERIFIEE)
        QualificationMembre.objects.create(
            utilisateur=partiel, qualification=permis, environment="PROD",
            statut=StatutQualification.VERIFIEE)

        retenus = cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL,
                         qualifications=[permis, pse1])

        assert [o.author_id for o in retenus] == [complet.id]

    def test_a_jour_ecarte_un_titre_non_verifie(self, create_user, asso):
        """Un PSE1 déclaré mais jamais contrôlé ne vaut pas un PSE1."""
        titre = Qualification.objects.create(nom="PSE1 declare")
        declarant, _ = _benevole(create_user, "k", asso)
        QualificationMembre.objects.create(
            utilisateur=declarant, qualification=titre, environment="PROD",
            statut=StatutQualification.DECLAREE)

        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL,
                      qualifications=[titre], titres_a_jour=True).count() == 0
        # Sans l'exigence « à jour », il est retenu : c'est un choix de l'association.
        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL,
                      qualifications=[titre], titres_a_jour=False).count() == 1

    def test_a_jour_ecarte_un_titre_perime(self, create_user, asso):
        titre = Qualification.objects.create(nom="PSE1 perime")
        porteur, _ = _benevole(create_user, "l", asso)
        QualificationMembre.objects.create(
            utilisateur=porteur, qualification=titre, environment="PROD",
            statut=StatutQualification.VERIFIEE,
            date_expiration=timezone.localdate() - datetime.timedelta(days=1))

        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL,
                      qualifications=[titre]).count() == 0

    def test_un_titre_sans_echeance_est_a_jour(self, create_user, asso):
        """Sans péremption = permanent : l'écarter écarterait tous les permis."""
        titre = Qualification.objects.create(nom="Permis B campagne")
        porteur, _ = _benevole(create_user, "m", asso)
        QualificationMembre.objects.create(
            utilisateur=porteur, qualification=titre, environment="PROD",
            statut=StatutQualification.VERIFIEE)

        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL,
                      qualifications=[titre]).count() == 1

    def test_a_jour_ecarte_une_aptitude_echue(self, create_user, asso):
        porteur, _ = _benevole(create_user, "n", asso)
        ContactInstitution.objects.filter(institution=asso, utilisateur=porteur).update(
            aptitude_valide_jusquau=timezone.localdate() - datetime.timedelta(days=5))

        assert cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL,
                      titres_a_jour=True).count() == 0


@pytest.mark.django_db
class TestCiblageParCompetences:

    def test_au_moins_une_competence_suffit(self, create_user, asso):
        """« Ou » et non « et » : « électricien ET infirmier » ne décrit personne."""
        elec = Competence.objects.create(nom="Electricien campagne")
        infi = Competence.objects.create(nom="Infirmier campagne")
        un, _ = _benevole(create_user, "o", asso, competences=[elec])
        deux, _ = _benevole(create_user, "p", asso, competences=[infi])
        _benevole(create_user, "q", asso)

        retenus = cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL,
                         competences=[elec, infi])

        assert {o.author_id for o in retenus} == {un.id, deux.id}


@pytest.mark.django_db
class TestCiblageParEquipe:

    def test_une_branche_limite_la_sollicitation(self, create_user, asso):
        """C'est ce qui permet à un coordinateur départemental de ne pas écrire à la France
        entière."""
        nationale = Team.objects.create(name="Nationale", institution=asso,
                                        echelon=EchelonEquipe.NATIONAL)
        gironde = Team.objects.create(name="Gironde", institution=asso,
                                      echelon=EchelonEquipe.DEPARTEMENTAL,
                                      territoire_code="33", equipe_parente=nationale)
        savoie = Team.objects.create(name="Savoie", institution=asso,
                                     echelon=EchelonEquipe.DEPARTEMENTAL,
                                     territoire_code="74", equipe_parente=nationale)
        girondin, _ = _benevole(create_user, "r", asso, equipe=gironde)
        _benevole(create_user, "s", asso, equipe=savoie)

        retenus = cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL, equipe=gironde)

        assert [o.author_id for o in retenus] == [girondin.id]

    def test_une_equipe_de_tete_prend_les_equipes_du_dessous(self, create_user, asso):
        nationale = Team.objects.create(name="Nationale2", institution=asso,
                                        echelon=EchelonEquipe.NATIONAL)
        gironde = Team.objects.create(name="Gironde2", institution=asso,
                                      echelon=EchelonEquipe.DEPARTEMENTAL,
                                      territoire_code="33", equipe_parente=nationale)
        girondin, _ = _benevole(create_user, "t", asso, equipe=gironde)

        retenus = cibler(asso, "PROD", echelon=EchelonCiblage.NATIONAL, equipe=nationale)

        assert [o.author_id for o in retenus] == [girondin.id]


@pytest.mark.django_db
class TestEnvoiEtReponses:

    def test_l_apercu_compte_avant_d_ecrire_a_qui_que_ce_soit(self, create_user, asso,
                                                              mailoutbox):
        """« 87 bénévoles retenus » est la seule chose qui permet de s'apercevoir qu'un critère
        ne filtre pas ce qu'on croyait."""
        bureau, _ = _benevole(create_user, "bur", asso, bureau=True)
        _benevole(create_user, "u", asso)
        campagne = _campagne(asso)

        reponse = _client(bureau).post(f"{URL}{campagne.id}/apercu/")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["total"] == 2
        assert mailoutbox == []

    def test_l_envoi_ecrit_a_chaque_cible_et_annonce_la_periode(self, create_user, asso,
                                                                mailoutbox):
        bureau, _ = _benevole(create_user, "bur2", asso, bureau=True)
        campagne = _campagne(asso, texte="Vigilance orange annoncée sur le département.")

        reponse = _client(bureau).post(f"{URL}{campagne.id}/envoyer/")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["envoyes"] == 1
        corps = mailoutbox[0].body
        # Le lien emmène sur la grille de CETTE période : son `next` porte l'identifiant de
        # campagne. Vérifié sur l'identifiant et non sur « campagne= », parce que `next` est
        # encodé dans l'URL (`campagne%3D`) — tester la forme littérale casserait au premier
        # changement d'encodage sans rien dire du comportement.
        assert str(campagne.id) in corps
        assert "Vigilance orange annoncée" in corps
        # Et la période est annoncée en clair, lisible par un humain.
        assert "au" in mailoutbox[0].subject
        campagne.refresh_from_db()
        assert campagne.statut == StatutCampagne.ENVOYEE

    def test_renvoyer_n_ecrit_pas_deux_fois_aux_memes(self, create_user, asso, mailoutbox):
        bureau, _ = _benevole(create_user, "bur3", asso, bureau=True)
        campagne = _campagne(asso)
        client = _client(bureau)
        client.post(f"{URL}{campagne.id}/envoyer/")
        premier_compte = len(mailoutbox)

        client.post(f"{URL}{campagne.id}/envoyer/")

        assert len(mailoutbox) == premier_compte

    def test_la_grille_du_benevole_s_ouvre_sur_la_periode(self, create_user, asso):
        """Sans ça, il répond sur ses quinze prochains jours — à une autre question."""
        benevole, _ = _benevole(create_user, "v", asso)
        campagne = _campagne(asso)
        CibleCampagne.objects.create(campagne=campagne, utilisateur=benevole,
                                     environment="PROD")

        reponse = _client(benevole).get(
            f"/api/mes-disponibilites/?campagne={campagne.id}")

        assert reponse.status_code == 200, reponse.data
        assert str(reponse.data["jours"][0]["date"]) == str(campagne.periode_debut)
        assert len(reponse.data["jours"]) == campagne.nombre_de_jours
        assert reponse.data["campagne"]["intitule"] == "Vigilance orange"

    def test_un_etranger_ne_lit_PAS_la_campagne_en_devinant_son_id(self, create_user, asso):
        """Son texte décrit parfois une situation avant qu'elle soit publique."""
        etranger, _ = _benevole(create_user, "w", asso)
        campagne = _campagne(asso, texte="Dispositif préfectoral en préparation.")

        reponse = _client(etranger).get(
            f"/api/mes-disponibilites/?campagne={campagne.id}")

        assert reponse.data["campagne"] is None
        # Et il retombe sur SA grille ordinaire, pas sur une erreur.
        assert len(reponse.data["jours"]) == 15

    def test_declarer_un_creneau_vaut_reponse(self, create_user, asso):
        benevole, _ = _benevole(create_user, "x", asso)
        campagne = _campagne(asso)
        cible = CibleCampagne.objects.create(campagne=campagne, utilisateur=benevole,
                                             etat=EtatCible.CONTACTE, environment="PROD")

        _client(benevole).post("/api/mes-disponibilites/", {
            "date": str(campagne.periode_debut), "creneau": "MATIN", "disponible": True,
            "campagne": str(campagne.id),
        }, format="json")

        cible.refresh_from_db()
        assert cible.etat == EtatCible.A_REPONDU
        assert cible.creneaux_declares == 1

    def test_la_relance_epargne_ceux_qui_ont_repondu(self, create_user, asso, mailoutbox):
        """Relancer quelqu'un qui a répondu « non » est le meilleur moyen de ne plus être
        lu."""
        bureau, _ = _benevole(create_user, "bur4", asso, bureau=True)
        repondant, _ = _benevole(create_user, "y", asso)
        silencieux, _ = _benevole(create_user, "z", asso)
        campagne = _campagne(asso)
        _client(bureau).post(f"{URL}{campagne.id}/envoyer/")
        mailoutbox.clear()
        CibleCampagne.objects.filter(campagne=campagne, utilisateur=repondant).update(
            etat=EtatCible.A_REPONDU)

        reponse = _client(bureau).post(f"{URL}{campagne.id}/relancer/")

        destinataires = [m.to[0] for m in mailoutbox]
        assert repondant.email not in destinataires
        assert silencieux.email in destinataires
        assert reponse.data["relances"] >= 1


@pytest.mark.django_db
class TestQuiPeutLancer:

    def test_le_bureau_peut(self, create_user, asso):
        bureau, _ = _benevole(create_user, "bb", asso, bureau=True)
        campagne = _campagne(asso)

        assert _client(bureau).post(f"{URL}{campagne.id}/apercu/").status_code == 200

    def test_un_simple_membre_ne_peut_pas(self, create_user, asso):
        simple, _ = _benevole(create_user, "cc", asso)
        campagne = _campagne(asso)

        assert _client(simple).post(f"{URL}{campagne.id}/apercu/").status_code == 403

    def test_un_encadrant_peut_sur_SA_branche(self, create_user, asso):
        """Sinon la coordination nationale est le seul goulot pour une crise locale."""
        gironde = Team.objects.create(name="Gironde3", institution=asso,
                                      echelon=EchelonEquipe.DEPARTEMENTAL,
                                      territoire_code="33")
        encadrant, _ = _benevole(create_user, "dd", asso, equipe=gironde)
        gironde.membres_encadrement.add(encadrant)
        campagne = _campagne(asso, equipe=gironde)

        assert _client(encadrant).post(f"{URL}{campagne.id}/apercu/").status_code == 200

    def test_un_encadrant_ne_peut_PAS_lancer_une_campagne_nationale(self, create_user, asso):
        """Il écrirait à des gens dont il n'a pas la charge."""
        gironde = Team.objects.create(name="Gironde4", institution=asso,
                                      echelon=EchelonEquipe.DEPARTEMENTAL,
                                      territoire_code="33")
        encadrant, _ = _benevole(create_user, "ee", asso, equipe=gironde)
        gironde.membres_encadrement.add(encadrant)
        campagne = _campagne(asso)  # sans équipe = toute l'association

        assert _client(encadrant).post(f"{URL}{campagne.id}/apercu/").status_code == 403

    def test_une_campagne_envoyee_ne_se_modifie_plus(self, create_user, asso):
        """Changer la période ferait répondre à une question que personne n'a posée."""
        bureau, _ = _benevole(create_user, "ff", asso, bureau=True)
        campagne = _campagne(asso, statut=StatutCampagne.ENVOYEE)

        reponse = _client(bureau).patch(f"{URL}{campagne.id}/",
                                        {"intitule": "Autre"}, format="json")

        assert reponse.status_code == 400


@pytest.mark.django_db
class TestToursDeGardeEnOption:
    """Demande de Sylvain du 12/11/2026 : « tour de garde est une option activable ».

    La première version s'en remettait à `effectif_cible = 0`, donc une décision
    d'organisation portée par un nombre laissé à zéro — personne ne lit un formulaire comme
    ça. Beaucoup de campagnes ne veulent d'ailleurs que recueillir des disponibilités."""

    def test_desactive_par_defaut(self, asso):
        """Le défaut va vers le moins d'effet : c'est une option qui propose d'affecter des
        gens."""
        assert _campagne(asso).tours_de_garde is False

    def test_aucun_tour_n_est_cree_quand_l_option_est_fermee(self, create_user, asso):
        from core.rotations_campagne import generer_rotations
        from core.models import RotationCampagne

        campagne = _campagne(asso)

        bilan = generer_rotations(campagne)

        assert bilan["desactive"] is True
        assert bilan["rotations"] == 0
        assert not RotationCampagne.objects.filter(campagne=campagne).exists()

    def test_desactiver_l_option_SUPPRIME_les_tours_existants(self, create_user, asso):
        """Une grille de garde orpheline, que plus rien n'alimente, est pire qu'aucune
        grille : quelqu'un la lira un jour en croyant qu'elle vaut encore."""
        from core.models import RotationCampagne
        from core.rotations_campagne import generer_rotations

        campagne = _campagne(asso, tours_de_garde=True, effectif_cible=1,
                             duree_rotation_jours=3)
        generer_rotations(campagne)
        assert RotationCampagne.objects.filter(campagne=campagne).exists()

        campagne.tours_de_garde = False
        campagne.save(update_fields=["tours_de_garde"])
        bilan = generer_rotations(campagne)

        assert bilan["supprimees"] >= 1
        assert not RotationCampagne.objects.filter(campagne=campagne).exists()

    def test_l_API_refuse_de_generer_quand_l_option_est_fermee(self, create_user, asso):
        """Dit, plutôt que de rendre un bilan vide qu'on prendrait pour « aucun volontaire
        disponible » : ce sont deux situations opposées."""
        bureau, _ = _benevole(create_user, "opt1", asso, bureau=True)
        campagne = _campagne(asso)

        reponse = _client(bureau).post(f"{URL}{campagne.id}/rotations/")

        assert reponse.status_code == 400
        assert "pas activ" in reponse.data["error"]

    def test_l_API_refuse_une_campagne_a_tours_sans_effectif(self, create_user, asso):
        """Refusé à la saisie plutôt que découvert à la génération, qui créerait des tours
        vides — et le message, lui, aurait promis une organisation."""
        bureau, _ = _benevole(create_user, "opt2", asso, bureau=True)

        reponse = _client(bureau).post(URL, {
            "institution": str(asso.id), "intitule": "Garde", "motif": "CRISE_EN_COURS",
            "periode_debut": str(timezone.localdate() + datetime.timedelta(days=1)),
            "periode_fin": str(timezone.localdate() + datetime.timedelta(days=4)),
            "tours_de_garde": True, "effectif_cible": 0,
        }, format="json")

        assert reponse.status_code == 400
        assert "effectif_cible" in reponse.data

    def test_le_message_n_annonce_aucun_tour_sans_l_option(self, asso):
        """« par tranches de 0 jour » n'informe personne : la phrase change de nature."""
        from core.campagnes_disponibilite import _phrase_rotation

        sans = _phrase_rotation(_campagne(asso))
        avec = _phrase_rotation(_campagne(asso, tours_de_garde=True, effectif_cible=2,
                                          duree_rotation_jours=3, repos_min_jours=2))

        assert "n'engage" in sans or "engageons à rien" in sans
        assert "3 jour" in avec


@pytest.mark.django_db
class TestRotations:

    @pytest.fixture
    def campagne_six_jours(self, asso):
        return _campagne(
            asso,
            periode_debut=timezone.localdate() + datetime.timedelta(days=1),
            periode_fin=timezone.localdate() + datetime.timedelta(days=6),
            tours_de_garde=True,
            duree_rotation_jours=3, repos_min_jours=0, effectif_cible=1,
            creneaux=["MATIN"],
        )

    def _declarer_toute_la_periode(self, campagne, offre):
        jour = campagne.periode_debut
        while jour <= campagne.periode_fin:
            DisponibiliteOffre.objects.create(offer=offre, date=jour, creneau="MATIN",
                                              environment="PROD")
            jour += datetime.timedelta(days=1)

    def test_la_periode_est_decoupee_en_tranches(self, create_user, asso,
                                                 campagne_six_jours):
        from core.rotations_campagne import generer_rotations

        bilan = generer_rotations(campagne_six_jours)

        # Six jours par tranches de trois : deux tours.
        assert bilan["rotations"] == 2

    def test_la_derniere_tranche_peut_etre_plus_courte(self, asso):
        """Refuser le dernier jour laisserait un trou de garde."""
        from core.rotations_campagne import generer_rotations

        campagne = _campagne(
            asso, periode_debut=timezone.localdate(),
            periode_fin=timezone.localdate() + datetime.timedelta(days=3),
            tours_de_garde=True, duree_rotation_jours=3, effectif_cible=0)

        bilan = generer_rotations(campagne)

        assert bilan["rotations"] == 2

    def test_les_tours_ne_reprennent_PAS_la_meme_personne(self, create_user, asso,
                                                          campagne_six_jours):
        """La raison d'être des rotations : sans ce critère, le planificateur reprendrait les
        mêmes du premier au dernier jour."""
        from core.rotations_campagne import generer_rotations

        premier, offre1 = _benevole(create_user, "gg", asso)
        second, offre2 = _benevole(create_user, "hh", asso)
        for u, o in ((premier, offre1), (second, offre2)):
            CibleCampagne.objects.create(campagne=campagne_six_jours, utilisateur=u,
                                         ressource=o, environment="PROD")
            self._declarer_toute_la_periode(campagne_six_jours, o)

        generer_rotations(campagne_six_jours)

        affectes = list(AffectationRotation.objects.filter(
            rotation__campagne=campagne_six_jours).values_list(
                "rotation__numero", "utilisateur_id"))
        assert len(affectes) == 2
        # Deux tours, deux personnes différentes.
        assert len({u for _n, u in affectes}) == 2

    def test_personne_n_est_affecte_sans_s_etre_declare(self, create_user, asso,
                                                        campagne_six_jours):
        """Une garde armée avec quelqu'un qui n'a rien promis n'est pas armée."""
        from core.rotations_campagne import generer_rotations

        muet, offre = _benevole(create_user, "ii", asso)
        CibleCampagne.objects.create(campagne=campagne_six_jours, utilisateur=muet,
                                     ressource=offre, environment="PROD")

        bilan = generer_rotations(campagne_six_jours)

        assert bilan["proposees"] == 0
        assert len(bilan["manques"]) == 2

    def test_le_sous_effectif_est_DIT(self, create_user, asso, campagne_six_jours):
        """Une grille qui paraît complète parce qu'on a caché les trous est pire que pas de
        grille."""
        from core.rotations_campagne import generer_rotations

        campagne_six_jours.effectif_cible = 3
        campagne_six_jours.save(update_fields=["effectif_cible"])
        seul, offre = _benevole(create_user, "jj", asso)
        CibleCampagne.objects.create(campagne=campagne_six_jours, utilisateur=seul,
                                     ressource=offre, environment="PROD")
        self._declarer_toute_la_periode(campagne_six_jours, offre)

        bilan = generer_rotations(campagne_six_jours)

        manque = bilan["manques"][0]
        assert manque["attendus"] == 3
        assert manque["trouves"] == 1

    def test_rien_n_est_confirme_par_le_calcul(self, create_user, asso, campagne_six_jours):
        """Une affectation générée et présentée comme acquise ferait partir une garde sur un
        calcul que personne n'a relu."""
        from core.rotations_campagne import generer_rotations

        u, offre = _benevole(create_user, "kk", asso)
        CibleCampagne.objects.create(campagne=campagne_six_jours, utilisateur=u,
                                     ressource=offre, environment="PROD")
        self._declarer_toute_la_periode(campagne_six_jours, offre)

        generer_rotations(campagne_six_jours)

        statuts = set(AffectationRotation.objects.values_list("statut", flat=True))
        assert statuts == {StatutAffectationRotation.PROPOSEE}

    def test_regenerer_garde_les_affectations_confirmees(self, create_user, asso,
                                                         campagne_six_jours):
        """Sinon chaque recalcul détruirait les décisions prises."""
        from core.rotations_campagne import generer_rotations

        u, offre = _benevole(create_user, "ll", asso)
        CibleCampagne.objects.create(campagne=campagne_six_jours, utilisateur=u,
                                     ressource=offre, environment="PROD")
        self._declarer_toute_la_periode(campagne_six_jours, offre)
        generer_rotations(campagne_six_jours)
        premiere = AffectationRotation.objects.first()
        premiere.statut = StatutAffectationRotation.CONFIRMEE
        premiere.save(update_fields=["statut"])

        bilan = generer_rotations(campagne_six_jours)

        assert bilan["conservees"] == 1
        premiere.refresh_from_db()
        assert premiere.statut == StatutAffectationRotation.CONFIRMEE

    def test_le_repos_minimum_est_respecte(self, create_user, asso, asso_repos=None):
        """Sans ce garde-fou, le critère « le moins mobilisé » étalerait la charge mais
        n'empêcherait pas deux tours collés."""
        from core.rotations_campagne import generer_rotations

        campagne = _campagne(
            asso, periode_debut=timezone.localdate(),
            periode_fin=timezone.localdate() + datetime.timedelta(days=5),
            tours_de_garde=True, duree_rotation_jours=3, repos_min_jours=5,
            effectif_cible=1, creneaux=["MATIN"])
        seul, offre = _benevole(create_user, "mm", asso)
        CibleCampagne.objects.create(campagne=campagne, utilisateur=seul, ressource=offre,
                                     environment="PROD")
        jour = campagne.periode_debut
        while jour <= campagne.periode_fin:
            DisponibiliteOffre.objects.create(offer=offre, date=jour, creneau="MATIN",
                                              environment="PROD")
            jour += datetime.timedelta(days=1)

        bilan = generer_rotations(campagne)

        # Il tient le premier tour, pas le second : cinq jours de repos ne tiennent pas dans
        # la période.
        assert bilan["proposees"] == 1
        assert len(bilan["manques"]) == 1

    def test_la_couverture_compte_par_jour_et_par_creneau(self, create_user, asso,
                                                          campagne_six_jours):
        """Un taux de réponse de 80 % ne dit rien si tous les répondants sont disponibles le
        même jour."""
        from core.campagnes_disponibilite import couverture

        u, offre = _benevole(create_user, "nn", asso)
        CibleCampagne.objects.create(campagne=campagne_six_jours, utilisateur=u,
                                     ressource=offre, environment="PROD")
        DisponibiliteOffre.objects.create(
            offer=offre, date=campagne_six_jours.periode_debut, creneau="MATIN",
            environment="PROD")

        resultat = couverture(campagne_six_jours)

        assert resultat["jours"][0]["creneaux"]["MATIN"] == 1
        assert resultat["jours"][1]["creneaux"]["MATIN"] == 0
