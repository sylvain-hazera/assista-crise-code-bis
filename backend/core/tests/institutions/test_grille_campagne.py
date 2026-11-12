"""La grille de mobilisation vue depuis une campagne, et ce qu'on en fait.

Trois demandes de Sylvain du 12/11/2026, sur l'onglet « Disponibilités » de
`/admin/membres-association` :

1. « on doit pouvoir voir aussi les disponibilités à plus long terme si demandées lors d'une
   campagne » — la grille s'ouvrait sur quinze jours, plafonnés à trente et un, alors qu'une
   campagne interroge une période nommée souvent hors de cette fenêtre. Les réponses étaient
   en base, lues par le planificateur de tours de garde, et **invisibles sur l'écran qui sert
   à mobiliser** ;
2. « en sélectionner plusieurs pour constituer une équipe d'intervention, ou les affecter à
   une équipe déjà en place » ;
3. « avec la précision du créneau horaire sur lequel on le sélectionnait, en cliquant sur les
   créneaux en question » — le geste du modal de recrutement d'un point opérationnel, porté
   sur la grille.

Ce que ces tests tiennent, dans l'ordre d'importance :

- **Zéro créneau déclaré par quelqu'un qui a répondu n'est pas un silence.** C'est « je ne
  suis pas disponible ». Les confondre ferait relancer quelqu'un qui a déjà répondu non, et
  c'est l'erreur que `CibleCampagne.creneaux_declares` existe pour éviter.
- **Un membre non ciblé n'est pas un silencieux non plus** : on ne lui a rien demandé.
- **La campagne d'une autre association n'est pas lisible**, même par un membre légitime de
  celle-ci : son identifiant ouvrirait sa période et le détail de ses cibles.
- **Une équipe ne se crée pas vide**, et les personnes écartées sont nommées.
- **Les créneaux pointés à la main vont dans les tours de garde** quand la campagne en a, en
  `CONFIRMEE` : un humain les a choisis, ce n'est pas une proposition du planificateur.
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AffectationRotation, CampagneDisponibilite, CibleCampagne, ContactInstitution,
    DisponibiliteOffre, EtatCible, FicheBenevole, Institution, InstitutionType,
    MotifCampagne, RotationCampagne, StatutAffectationRotation, StatutCampagne, Team, UserRole,
)


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="AASC Campagne", type=itype, actif=True)


@pytest.fixture
def autre_aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="AASC Voisine", type=itype, actif=True)


def _membre(create_user, institution, nom, bureau=False,
            statut=ContactInstitution.StatutMembre.ACTIF):
    user = create_user(username=f"{nom.lower()}-camp@test.fr",
                       email=f"{nom.lower()}-camp@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name=nom)
    ContactInstitution.objects.create(
        institution=institution, utilisateur=user, fonction="Équipier", actif=True,
        statut=statut, membre_bureau=bureau)
    return user


def _ressource(membre, institution):
    from core.fiches_benevoles import ressource_du_benevole

    fiche, _ = FicheBenevole.objects.get_or_create(
        utilisateur=membre, defaults={"environment": "PROD"})
    offre, _cree = ressource_du_benevole(fiche, institution)
    return offre


#: La période est volontairement LOIN devant : c'est tout l'objet de la demande. Soixante
#: jours, c'est au-delà des trente et un jours que la fenêtre libre sait montrer.
DECALAGE = 60


@pytest.fixture
def campagne(db, aasc):
    debut = timezone.localdate() + datetime.timedelta(days=DECALAGE)
    return CampagneDisponibilite.objects.create(
        institution=aasc, intitule="Renfort hivernal", motif=MotifCampagne.CRISE_A_VENIR,
        periode_debut=debut, periode_fin=debut + datetime.timedelta(days=14),
        creneaux=["MATIN", "SOIR"], statut=StatutCampagne.ENVOYEE,
        tours_de_garde=True, duree_rotation_jours=5, environment="PROD",
    )


def _rotations(campagne):
    """Les tours de garde, découpés comme le fait le planificateur."""
    rotations, numero, jour = [], 1, campagne.periode_debut
    while jour <= campagne.periode_fin:
        fin = min(jour + datetime.timedelta(days=campagne.duree_rotation_jours - 1),
                  campagne.periode_fin)
        rotations.append(RotationCampagne.objects.create(
            campagne=campagne, numero=numero, date_debut=jour, date_fin=fin,
            environment="PROD"))
        numero, jour = numero + 1, fin + datetime.timedelta(days=1)
    return rotations


def _grille(utilisateur, institution, **params):
    return _client(utilisateur).get(
        reverse("disponibiliteoperationnelle-grille"),
        {"institution": str(institution.id), **params})


class TestLaFenetreDUneCampagne:
    def test_la_periode_dune_campagne_est_hors_de_la_fenetre_libre(
            self, create_user, aasc, campagne):
        """Le point de départ : sans campagne, ces jours-là sont inatteignables."""
        membre = _membre(create_user, aasc, "LOINTAIN")
        _ressource(membre, aasc)

        libre = _grille(membre, aasc, jours=31).data
        assert str(libre["fin"]) < campagne.periode_debut.isoformat()

        avec = _grille(membre, aasc, campagne=str(campagne.id)).data
        assert str(avec["debut"]) == campagne.periode_debut.isoformat()
        assert str(avec["fin"]) == campagne.periode_fin.isoformat()

    def test_les_creneaux_servis_sont_ceux_que_la_campagne_a_poses(
            self, create_user, aasc, campagne):
        """Interroger sur quatre créneaux quand la campagne n'en demandait que deux ferait
        lire comme des refus deux colonnes auxquelles personne n'a été invité à répondre."""
        membre = _membre(create_user, aasc, "DEUXCRENEAUX")
        _ressource(membre, aasc)

        data = _grille(membre, aasc, campagne=str(campagne.id)).data

        assert data["creneaux"] == ["MATIN", "SOIR"]
        assert set(data["membres"][0]["jours"][0]["creneaux"]) == {"MATIN", "SOIR"}

    def test_une_declaration_dans_la_periode_est_visible(self, create_user, aasc, campagne):
        membre = _membre(create_user, aasc, "DECLARANT")
        offre = _ressource(membre, aasc)
        DisponibiliteOffre.objects.create(
            offer=offre, date=campagne.periode_debut + datetime.timedelta(days=2),
            creneau="SOIR")

        fiche = _grille(membre, aasc, campagne=str(campagne.id)).data["membres"][0]

        assert fiche["a_declare"] is True
        assert fiche["jours"][2]["creneaux"]["SOIR"] is True
        assert fiche["jours"][2]["creneaux"]["MATIN"] is False

    def test_une_reponse_sans_aucun_creneau_nest_pas_un_silence(
            self, create_user, aasc, campagne):
        """LE test de cet écran. « J'ai répondu que je ne pouvais pas » et « je n'ai pas
        répondu » appellent deux gestes opposés : l'un se respecte, l'autre se relance."""
        membre = _membre(create_user, aasc, "AREPONDUNON")
        CibleCampagne.objects.create(
            campagne=campagne, utilisateur=membre, etat=EtatCible.A_REPONDU,
            creneaux_declares=0, environment="PROD")

        fiche = _grille(membre, aasc, campagne=str(campagne.id)).data["membres"][0]

        assert fiche["a_declare"] is True
        assert fiche["cible"]["etat"] == EtatCible.A_REPONDU
        assert fiche["cible"]["creneaux_declares"] == 0

    def test_un_membre_non_cible_na_pas_de_cible_du_tout(self, create_user, aasc, campagne):
        """On ne lui a rien demandé : le compter parmi les silencieux serait un mensonge."""
        membre = _membre(create_user, aasc, "NONCIBLE")
        _ressource(membre, aasc)

        fiche = _grille(membre, aasc, campagne=str(campagne.id)).data["membres"][0]

        assert fiche["cible"] is None
        assert fiche["a_declare"] is False

    def test_un_silencieux_sollicite_se_distingue(self, create_user, aasc, campagne):
        membre = _membre(create_user, aasc, "SILENCIEUXCIBLE")
        CibleCampagne.objects.create(
            campagne=campagne, utilisateur=membre, etat=EtatCible.CONTACTE,
            environment="PROD")

        fiche = _grille(membre, aasc, campagne=str(campagne.id)).data["membres"][0]

        assert fiche["cible"]["etat"] == EtatCible.CONTACTE
        assert fiche["a_declare"] is False

    def test_hors_campagne_aucune_cible_nest_rendue(self, create_user, aasc, campagne):
        """La clé n'apparaît pas : une colonne « réponse » vide sur une grille libre ferait
        croire que tout le monde est resté muet."""
        membre = _membre(create_user, aasc, "LIBRE")
        _ressource(membre, aasc)

        fiche = _grille(membre, aasc).data["membres"][0]

        assert "cible" not in fiche

    def test_les_campagnes_sont_servies_avec_la_grille(self, create_user, aasc, campagne):
        """Le sélecteur de fenêtre en a besoin dès l'ouverture : un second appel ferait
        clignoter l'écran."""
        membre = _membre(create_user, aasc, "SELECTEUR")
        CibleCampagne.objects.create(
            campagne=campagne, utilisateur=membre, etat=EtatCible.A_REPONDU,
            environment="PROD")

        data = _grille(membre, aasc).data

        assert len(data["campagnes"]) == 1
        resume = data["campagnes"][0]
        assert resume["intitule"] == "Renfort hivernal"
        assert resume["nombre_cibles"] == 1
        assert resume["nombre_reponses"] == 1
        assert resume["creneaux"] == ["MATIN", "SOIR"]

    def test_un_brouillon_nest_pas_proposé(self, create_user, aasc):
        """Personne n'a été sollicité : une fenêtre vide présentée comme une campagne ferait
        croire à un silence général."""
        membre = _membre(create_user, aasc, "BROUILLON")
        debut = timezone.localdate() + datetime.timedelta(days=DECALAGE)
        CampagneDisponibilite.objects.create(
            institution=aasc, intitule="Pas encore envoyée",
            motif=MotifCampagne.EXERCICE, periode_debut=debut,
            periode_fin=debut + datetime.timedelta(days=3),
            statut=StatutCampagne.BROUILLON, environment="PROD")

        assert _grille(membre, aasc).data["campagnes"] == []

    def test_une_periode_tres_longue_est_coupee_et_cest_dit(self, create_user, aasc):
        membre = _membre(create_user, aasc, "LONGUE")
        debut = timezone.localdate()
        longue = CampagneDisponibilite.objects.create(
            institution=aasc, intitule="Rétablissement", motif=MotifCampagne.RETABLISSEMENT,
            periode_debut=debut, periode_fin=debut + datetime.timedelta(days=200),
            statut=StatutCampagne.ENVOYEE, environment="PROD")

        data = _grille(membre, aasc, campagne=str(longue.id)).data

        assert data["tronquee"] is True
        assert len(data["jours"]) == 92

    def test_la_campagne_dune_autre_association_est_refusee(
            self, create_user, aasc, autre_aasc, campagne):
        """Son identifiant ouvrirait sa période ET le détail de ses cibles."""
        intrus = _membre(create_user, autre_aasc, "INTRUS")

        reponse = _grille(intrus, autre_aasc, campagne=str(campagne.id))

        assert reponse.status_code == status.HTTP_404_NOT_FOUND


class TestConstituerUneEquipeDepuisLaGrille:
    def test_le_bureau_cree_une_equipe_avec_la_selection(self, create_user, aasc):
        bureau = _membre(create_user, aasc, "PRESIDENT", bureau=True)
        un = _membre(create_user, aasc, "UN")
        deux = _membre(create_user, aasc, "DEUX")

        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Intervention Nord",
             "utilisateurs": [str(un.id), str(deux.id)],
             "mission_titre": "Reconnaissance des berges"},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert reponse.data["ajoutes"] == 2
        equipe = Team.objects.get(name="Intervention Nord")
        assert set(equipe.members.values_list("id", flat=True)) == {un.id, deux.id}
        assert equipe.institution_id == aasc.id
        # Sans échelon : c'est une équipe opérationnelle, pas un nœud de la hiérarchie
        # territoriale.
        assert equipe.echelon == ""
        assert equipe.mission_active.titre == "Reconnaissance des berges"

    def test_un_membre_ordinaire_ne_peut_pas_constituer_dequipe(self, create_user, aasc):
        """Composer une équipe est un acte de gouvernance : la page est ouverte à tous les
        membres, pas ce geste-là."""
        simple = _membre(create_user, aasc, "SIMPLE")
        autre = _membre(create_user, aasc, "AUTRE")

        reponse = _client(simple).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Équipe sauvage",
             "utilisateurs": [str(autre.id)]},
            format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN
        assert not Team.objects.filter(name="Équipe sauvage").exists()

    def test_une_equipe_ne_se_cree_pas_vide(self, create_user, aasc, autre_aasc):
        """Tous refusés : on ne laisse pas une coquille dans l'arborescence, et on dit
        pourquoi chacun a été écarté."""
        bureau = _membre(create_user, aasc, "BUREAU2", bureau=True)
        etranger = _membre(create_user, autre_aasc, "ETRANGER")

        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Vide",
             "utilisateurs": [str(etranger.id)]},
            format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert reponse.data["refuses"][0]["utilisateur"] == str(etranger.id)
        assert not Team.objects.filter(name="Vide").exists()

    def test_un_membre_sorti_est_ecarte_nommement(self, create_user, aasc):
        bureau = _membre(create_user, aasc, "BUREAU3", bureau=True)
        sorti = _membre(create_user, aasc, "PARTI",
                        statut=ContactInstitution.StatutMembre.SORTI)
        reste = _membre(create_user, aasc, "RESTE")

        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Mixte",
             "utilisateurs": [str(sorti.id), str(reste.id)]},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED
        assert reponse.data["ajoutes"] == 1
        assert "sorti" in reponse.data["refuses"][0]["motif"].lower()


class TestLesCreneauxPointesALaMain:
    def test_un_creneau_pointe_devient_un_tour_de_garde_confirme(
            self, create_user, aasc, campagne):
        """La demande : sélectionner quelqu'un AVEC le créneau sur lequel on le prend."""
        bureau = _membre(create_user, aasc, "CHEF", bureau=True)
        equipier = _membre(create_user, aasc, "EQUIPIER")
        rotations = _rotations(campagne)

        jour = campagne.periode_debut + datetime.timedelta(days=1)
        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Garde hivernale",
             "utilisateurs": [str(equipier.id)],
             "campagne": str(campagne.id),
             "creneaux": [{"utilisateur": str(equipier.id), "date": jour.isoformat(),
                           "creneau": "SOIR"}]},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert reponse.data["creneaux_pointes"] == 1
        assert reponse.data["creneaux_enregistres"] == 1
        affectation = AffectationRotation.objects.get(utilisateur=equipier)
        assert affectation.rotation_id == rotations[0].id
        assert affectation.creneau == "SOIR"
        # CONFIRMÉE et non PROPOSÉE : un humain l'a choisi, ce n'est pas une proposition du
        # planificateur — et une régénération efface les proposées.
        assert affectation.statut == StatutAffectationRotation.CONFIRMEE

    def test_deux_jours_de_la_meme_rotation_font_une_seule_affectation(
            self, create_user, aasc, campagne):
        """La maille du modèle est la rotation, pas le jour : à savoir, pas à découvrir."""
        bureau = _membre(create_user, aasc, "CHEF2", bureau=True)
        equipier = _membre(create_user, aasc, "EQUIPIER2")
        _rotations(campagne)

        jours = [campagne.periode_debut + datetime.timedelta(days=i) for i in (0, 1)]
        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Garde 2",
             "utilisateurs": [str(equipier.id)], "campagne": str(campagne.id),
             "creneaux": [{"utilisateur": str(equipier.id), "date": j.isoformat(),
                           "creneau": "MATIN"} for j in jours]},
            format="json")

        assert reponse.data["creneaux_pointes"] == 2
        assert reponse.data["creneaux_enregistres"] == 1
        assert AffectationRotation.objects.filter(utilisateur=equipier).count() == 1

    def test_un_creneau_pointe_pour_quelquun_de_refuse_est_ecarte_nommement(
            self, create_user, aasc, autre_aasc, campagne):
        """Sinon on croirait avoir couvert une garde qui ne l'est pas."""
        bureau = _membre(create_user, aasc, "CHEF3", bureau=True)
        dedans = _membre(create_user, aasc, "DEDANS")
        dehors = _membre(create_user, autre_aasc, "DEHORS")
        _rotations(campagne)

        jour = campagne.periode_debut
        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Garde 3",
             "utilisateurs": [str(dedans.id), str(dehors.id)],
             "campagne": str(campagne.id),
             "creneaux": [
                 {"utilisateur": str(dedans.id), "date": jour.isoformat(),
                  "creneau": "MATIN"},
                 {"utilisateur": str(dehors.id), "date": jour.isoformat(),
                  "creneau": "MATIN"}]},
            format="json")

        assert reponse.data["creneaux_enregistres"] == 1
        motifs = [i["motif"] for i in reponse.data["creneaux_ignores"]]
        assert any("non affectée" in m for m in motifs)

    def test_sans_tours_de_garde_rien_nest_ecrit_et_cest_dit(
            self, create_user, aasc, campagne):
        """Aucune table ne stocke « cette équipe tient le soir du 14 » hors tours de garde :
        le taire laisserait croire à un planning qui n'existe pas."""
        bureau = _membre(create_user, aasc, "CHEF4", bureau=True)
        equipier = _membre(create_user, aasc, "EQUIPIER4")

        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Sans rotation",
             "utilisateurs": [str(equipier.id)], "campagne": str(campagne.id),
             "creneaux": [{"utilisateur": str(equipier.id),
                           "date": campagne.periode_debut.isoformat(),
                           "creneau": "MATIN"}]},
            format="json")

        assert reponse.data["creneaux_enregistres"] == 0
        assert reponse.data["creneaux_ignores"]
        assert not AffectationRotation.objects.filter(utilisateur=equipier).exists()

    def test_un_creneau_hors_periode_est_ecarte(self, create_user, aasc, campagne):
        bureau = _membre(create_user, aasc, "CHEF5", bureau=True)
        equipier = _membre(create_user, aasc, "EQUIPIER5")
        _rotations(campagne)

        hors = campagne.periode_fin + datetime.timedelta(days=10)
        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Hors période",
             "utilisateurs": [str(equipier.id)], "campagne": str(campagne.id),
             "creneaux": [{"utilisateur": str(equipier.id), "date": hors.isoformat(),
                           "creneau": "NUIT"}]},
            format="json")

        assert reponse.data["creneaux_enregistres"] == 0
        assert "Hors des tours de garde" in reponse.data["creneaux_ignores"][0]["motif"]

    def test_une_date_illisible_est_ecartee_sans_faire_echouer_laffectation(
            self, create_user, aasc, campagne):
        bureau = _membre(create_user, aasc, "CHEF6", bureau=True)
        equipier = _membre(create_user, aasc, "EQUIPIER6")
        _rotations(campagne)

        reponse = _client(bureau).post(
            reverse("team-creer-avec-membres"),
            {"institution": str(aasc.id), "nom": "Date cassée",
             "utilisateurs": [str(equipier.id)], "campagne": str(campagne.id),
             "creneaux": [{"utilisateur": str(equipier.id), "date": "la semaine prochaine",
                           "creneau": "MATIN"}]},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED
        assert reponse.data["ajoutes"] == 1
        assert reponse.data["creneaux_ignores"][0]["motif"] == "Date illisible."

    def test_les_creneaux_marchent_aussi_sur_une_equipe_existante(
            self, create_user, aasc, campagne):
        """Même geste, autre cible : « ou les affecter à une équipe déjà en place »."""
        bureau = _membre(create_user, aasc, "CHEF7", bureau=True)
        equipier = _membre(create_user, aasc, "EQUIPIER7")
        _rotations(campagne)
        equipe = Team.objects.create(name="Déjà là", institution=aasc, environment="PROD")

        jour = campagne.periode_debut
        reponse = _client(bureau).post(
            reverse("team-ajouter-membres", args=[str(equipe.id)]),
            {"utilisateurs": [str(equipier.id)], "campagne": str(campagne.id),
             "creneaux": [{"utilisateur": str(equipier.id), "date": jour.isoformat(),
                           "creneau": "SOIR"}]},
            format="json")

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert reponse.data["ajoutes"] == 1
        assert reponse.data["creneaux_enregistres"] == 1
