"""Annuaire enrichi d'une association, et affectation en masse à une équipe terrain.

Ce que ces tests tiennent, dans l'ordre d'importance :

1. **Les coordonnées ne sont pas de l'annuaire ouvert.** La page des membres est ouverte à tout
   membre d'une AASC, pas seulement à son bureau. Téléphone, commune et métier sont réservés au
   bureau et aux administrateurs, et ABSENTS de la réponse sinon — pas rendus à `null`, qui
   affirmerait qu'il n'y a rien.
2. **L'affectation en masse AJOUTE, elle ne remplace pas.** Un `PATCH member_ids` depuis le
   navigateur envoie la liste entière telle que le navigateur la connaissait : deux régulateurs
   qui affectent en même temps, et le second efface les ajouts du premier.
3. **Un membre sorti est refusé nommément**, et le refus est rendu à l'appelant. Une
   affectation partielle qui se présente comme un succès fait partir une équipe incomplète en
   croyant l'avoir au complet.
4. **On n'affecte que des gens de l'institution de l'équipe** : sans ce test, l'action serait un
   moyen détourné d'ajouter n'importe quel compte de la plateforme à n'importe quelle équipe.
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Competence, ContactInstitution, DisponibiliteOffre, FicheBenevole, Institution,
    InstitutionType, Qualification, QualificationMembre, StatutQualification, Team, UserRole,
)


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="AASC Annuaire Test", type=itype, actif=True)


@pytest.fixture
def autre_aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="AASC Voisine", type=itype, actif=True)


def _membre(create_user, institution, nom, bureau=False,
            statut=ContactInstitution.StatutMembre.ACTIF, telephone="0600000000"):
    user = create_user(username=f"{nom.lower()}-annuaire@test.fr",
                       email=f"{nom.lower()}-annuaire@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name=nom)
    user.phone_number = telephone
    user.save()
    ContactInstitution.objects.create(
        institution=institution, utilisateur=user, fonction="Équipier",
        actif=True, statut=statut, membre_bureau=bureau)
    return user


def _fiche(membre, ville="Rennes", metier="Infirmier"):
    return FicheBenevole.objects.create(
        utilisateur=membre, environment="PROD", ville=ville, metier=metier,
        adresse="1 rue du Test", commune_code="35238", departement_code="35")


def _ressource(membre, institution, competences=()):
    from core.fiches_benevoles import ressource_du_benevole

    fiche, _ = FicheBenevole.objects.get_or_create(
        utilisateur=membre, defaults={"environment": "PROD"})
    offre, _cree = ressource_du_benevole(fiche, institution)
    if competences:
        offre.competences.set(competences)
    return offre


def _annuaire(utilisateur, institution):
    return _client(utilisateur).get(
        reverse("contactinstitution-annuaire-association"),
        {"institution": str(institution.id)})


class TestLesCoordonneesNeSontPasDeLAnnuaireOuvert:
    """LE test de ce module. Un numéro de téléphone n'est pas une information d'arborescence."""

    def test_un_membre_ordinaire_ne_voit_pas_les_coordonnees(self, create_user, aasc):
        lecteur = _membre(create_user, aasc, "ORDINAIRE")
        cible = _membre(create_user, aasc, "CIBLE")
        _fiche(cible)

        reponse = _annuaire(lecteur, aasc)

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert reponse.data["coordonnees_visibles"] is False
        ligne = next(m for m in reponse.data["membres"]
                     if m["utilisateur"] == str(cible.id))
        # Absents, et non rendus à null : « — » affirmerait qu'il n'y a pas de téléphone.
        for champ in ("telephone", "email", "ville", "metier", "commune_code",
                      "aptitude_valide_jusquau"):
            assert champ not in ligne, champ

    def test_le_bureau_voit_les_coordonnees(self, create_user, aasc):
        president = _membre(create_user, aasc, "PRESIDENT", bureau=True)
        cible = _membre(create_user, aasc, "JOIGNABLE", telephone="0612345678")
        _fiche(cible)

        reponse = _annuaire(president, aasc)

        assert reponse.data["coordonnees_visibles"] is True
        ligne = next(m for m in reponse.data["membres"]
                     if m["utilisateur"] == str(cible.id))
        # Enregistré en E.164 depuis le 12/11/2026 : c'est le format que tous les
        # fournisseurs de SMS acceptent (voir core/telephone.py).
        assert ligne["telephone"] == "+33612345678"
        assert ligne["ville"] == "Rennes"
        assert ligne["metier"] == "Infirmier"

    def test_un_administrateur_voit_les_coordonnees_sans_etre_membre(self, create_user, aasc):
        admin = create_user(username="admin-annuaire@test.fr",
                            email="admin-annuaire@test.fr", type=UserRole.ADMINISTRATOR)
        cible = _membre(create_user, aasc, "VU")
        _fiche(cible)

        reponse = _annuaire(admin, aasc)

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["coordonnees_visibles"] is True

    def test_un_etranger_a_lassociation_est_refuse(self, create_user, aasc, autre_aasc):
        intrus = _membre(create_user, autre_aasc, "INTRUS")
        _membre(create_user, aasc, "PROTEGE")

        reponse = _annuaire(intrus, aasc)

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_un_anonyme_est_refuse(self, db, aasc):
        reponse = APIClient().get(
            reverse("contactinstitution-annuaire-association"),
            {"institution": str(aasc.id)})
        assert reponse.status_code in (status.HTTP_401_UNAUTHORIZED,
                                       status.HTTP_403_FORBIDDEN)

    def test_sans_institution_cest_une_erreur_pas_tout_le_monde(self, create_user, aasc):
        """Un paramètre manquant ne doit pas rendre l'annuaire de la plateforme entière."""
        lecteur = _membre(create_user, aasc, "DEMANDEUR")
        reponse = _client(lecteur).get(
            reverse("contactinstitution-annuaire-association"))
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST


class TestCeQueLArbreDoitPouvoirMontrer:
    def test_les_competences_viennent_de_la_ressource(self, create_user, aasc):
        president = _membre(create_user, aasc, "CHEF", bureau=True)
        membre = _membre(create_user, aasc, "SECOURISTE")
        competence = Competence.objects.create(nom="Secourisme annuaire")
        _ressource(membre, aasc, [competence])

        ligne = next(m for m in _annuaire(president, aasc).data["membres"]
                     if m["utilisateur"] == str(membre.id))

        assert [c["nom"] for c in ligne["competences"]] == ["Secourisme annuaire"]
        assert ligne["a_ressource"] is True

    def test_sans_ressource_aucune_competence_et_cest_dit(self, create_user, aasc):
        """Un membre sans ressource n'est pas mobilisable par les campagnes : l'écran doit
        pouvoir le signaler plutôt que de l'afficher comme quelqu'un sans compétence."""
        president = _membre(create_user, aasc, "BUREAU", bureau=True)

        ligne = next(m for m in _annuaire(president, aasc).data["membres"]
                     if m["utilisateur"] == str(president.id))

        assert ligne["competences"] == []
        assert ligne["a_ressource"] is False

    def test_les_titres_perimes_sont_comptes_a_part(self, create_user, aasc):
        """Un titre périmé vaut un titre absent le jour du départ : le confondre avec un titre
        détenu ferait partir quelqu'un sur une attestation expirée depuis quatre ans."""
        president = _membre(create_user, aasc, "INSTRUCTEUR", bureau=True)
        titre = Qualification.objects.create(nom="PSE1 annuaire", actif=True)
        QualificationMembre.objects.create(
            utilisateur=president, qualification=titre, environment="PROD",
            statut=StatutQualification.VERIFIEE,
            date_expiration=timezone.localdate() - datetime.timedelta(days=1))

        ligne = next(m for m in _annuaire(president, aasc).data["membres"]
                     if m["utilisateur"] == str(president.id))

        assert ligne["titres"] == 1
        assert ligne["titres_verifies"] == 1
        assert ligne["titres_perimes"] == 1

    def test_a_declare_distingue_le_silence(self, create_user, aasc):
        """« Pas de ligne = indisponible » : seul `a_declare` sépare qui a dit non de qui n'a
        pas répondu, et c'est lui qui dit qui relancer."""
        president = _membre(create_user, aasc, "RELANCEUR", bureau=True)
        parlant = _membre(create_user, aasc, "PARLANT")
        muet = _membre(create_user, aasc, "MUET")
        offre = _ressource(parlant, aasc)
        _ressource(muet, aasc)
        DisponibiliteOffre.objects.create(
            offer=offre, creneau="MATIN",
            date=timezone.localdate() + datetime.timedelta(days=2))

        membres = {m["utilisateur"]: m for m in _annuaire(president, aasc).data["membres"]}

        assert membres[str(parlant.id)]["a_declare"] is True
        assert membres[str(muet.id)]["a_declare"] is False

    def test_le_role_dans_lequipe_est_calcule_par_le_serveur(self, create_user, aasc):
        """Chef, régulateur, cadre, intervenant : la même personne peut tenir deux rôles
        différents dans deux équipes, et un rôle déduit côté navigateur finirait par diverger
        de ce que le serveur retient."""
        president = _membre(create_user, aasc, "PRES", bureau=True)
        chef = _membre(create_user, aasc, "LEADER")
        cadre = _membre(create_user, aasc, "ENCADRANT")
        equipier = _membre(create_user, aasc, "EQUIPIER")
        equipe = Team.objects.create(name="Équipe annuaire", institution=aasc, leader=chef)
        equipe.members.add(chef, cadre, equipier)
        equipe.membres_encadrement.add(cadre)

        roles = _annuaire(president, aasc).data["roles_par_equipe"][str(equipe.id)]

        assert roles[str(chef.id)] == "CHEF"
        assert roles[str(cadre.id)] == "CADRE"
        assert roles[str(equipier.id)] == "INTERVENANT"


class TestAffectationEnMasse:
    def _affecter(self, utilisateur, equipe, membres, **corps):
        return _client(utilisateur).post(
            reverse("team-ajouter-membres", args=[str(equipe.id)]),
            {"utilisateurs": [str(m.id) for m in membres], **corps}, format="json")

    def test_elle_ajoute_sans_effacer_les_presents(self, create_user, aasc):
        """LE test de cette action. Un PATCH de la liste entière aurait effacé `DEJA_LA`."""
        president = _membre(create_user, aasc, "REGUL", bureau=True)
        deja = _membre(create_user, aasc, "DEJALA")
        nouveau = _membre(create_user, aasc, "NOUVEAU")
        equipe = Team.objects.create(name="Terrain 1", institution=aasc)
        equipe.members.add(deja)

        reponse = self._affecter(president, equipe, [nouveau])

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert reponse.data["ajoutes"] == 1
        assert set(equipe.members.values_list("id", flat=True)) == {deja.id, nouveau.id}

    def test_affecter_deux_fois_ne_duplique_rien(self, create_user, aasc):
        president = _membre(create_user, aasc, "REGUL2", bureau=True)
        membre = _membre(create_user, aasc, "UNIQUE")
        equipe = Team.objects.create(name="Terrain 2", institution=aasc)

        self._affecter(president, equipe, [membre])
        reponse = self._affecter(president, equipe, [membre])

        assert reponse.data["ajoutes"] == 0
        assert reponse.data["deja_presents"] == 1
        assert equipe.members.count() == 1

    def test_un_membre_sorti_est_refuse_et_le_refus_est_dit(self, create_user, aasc):
        president = _membre(create_user, aasc, "REGUL3", bureau=True)
        sorti = _membre(create_user, aasc, "PARTI",
                        statut=ContactInstitution.StatutMembre.SORTI)
        equipe = Team.objects.create(name="Terrain 3", institution=aasc)

        reponse = self._affecter(president, equipe, [sorti])

        assert reponse.data["ajoutes"] == 0
        assert len(reponse.data["refuses"]) == 1
        assert "sorti" in reponse.data["refuses"][0]["motif"].lower()
        assert equipe.members.count() == 0

    def test_on_ne_peut_pas_affecter_un_etranger_a_linstitution(
            self, create_user, aasc, autre_aasc):
        president = _membre(create_user, aasc, "REGUL4", bureau=True)
        etranger = _membre(create_user, autre_aasc, "AILLEURS")
        equipe = Team.objects.create(name="Terrain 4", institution=aasc)

        reponse = self._affecter(president, equipe, [etranger])

        assert reponse.data["ajoutes"] == 0
        assert len(reponse.data["refuses"]) == 1
        assert equipe.members.count() == 0

    def test_une_equipe_dune_autre_institution_est_refusee(
            self, create_user, aasc, autre_aasc):
        president = _membre(create_user, aasc, "REGUL5", bureau=True)
        membre = _membre(create_user, aasc, "DISPO")
        equipe = Team.objects.create(name="Terrain voisin", institution=autre_aasc)

        reponse = self._affecter(president, equipe, [membre])

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_la_mission_part_avec_laffectation(self, create_user, aasc):
        """Définir la mission ici évite de rouvrir la page Équipes juste après."""
        president = _membre(create_user, aasc, "REGUL6", bureau=True)
        membre = _membre(create_user, aasc, "ENVOYE")
        equipe = Team.objects.create(name="Terrain 6", institution=aasc)

        reponse = self._affecter(president, equipe, [membre],
                                 mission_titre="Reconnaissance berges")

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        equipe.refresh_from_db()
        assert equipe.mission_active is not None
        assert equipe.mission_active.titre == "Reconnaissance berges"

    def test_une_liste_vide_est_une_erreur(self, create_user, aasc):
        president = _membre(create_user, aasc, "REGUL7", bureau=True)
        equipe = Team.objects.create(name="Terrain 7", institution=aasc)

        reponse = _client(president).post(
            reverse("team-ajouter-membres", args=[str(equipe.id)]),
            {"utilisateurs": []}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
