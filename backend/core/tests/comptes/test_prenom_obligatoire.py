"""Le prénom est exigé partout où quelqu'un s'inscrit (demande du 11/11/2026).

Deux surfaces d'inscription existaient, et chacune n'identifiait la personne que par un
patronyme :

1. **`/api/register/`** — le formulaire public. Le prénom n'était requis que pour un
   particulier ; pour une autorité locale ou un service de secours, le champ était effacé et
   désactivé (`toggleFieldsBasedOnUserType`). Un responsable de mairie s'inscrivait donc sous
   « Dupont », sans prénom, dans une plateforme où l'on se nomme pour se coordonner.
2. **Le rattachement d'une habitation** — un seul champ « Nom complet », et le compte créé à
   l'acceptation était fabriqué en coupant cette chaîne au PREMIER espace. « Jean Pierre
   Dupont » donnait donc le prénom « Jean » et le patronyme « Pierre Dupont », en silence.

Deux décisions à ne pas défaire :

- la règle vit dans `validate()` de `UserSerializer`, à la **création seulement**, et non dans
  `extra_kwargs` : le même sérialiseur sert les mises à jour partielles, où exiger un nom ferait
  échouer la modification d'un numéro de téléphone. C'est aussi ce qui la fait valoir pour les
  DEUX chemins d'inscription, qui partagent ce sérialiseur : `/api/register/` (`auth_register`),
  celui que le formulaire public appelle, et `/api/users/register/` (`user-register`), resté en
  place. Les deux sont testés ici — ils ont déjà divergé une fois, sur l'envoi des emails ;
- elle est **côté serveur**, pas seulement dans le formulaire, parce que `/api/register/` est
  ouvert à tous : une inscription sans prénom passerait par n'importe quel autre client.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.crypto_fields import blind_index
from core.models import (
    Habitation, RattachementHabitation, StatutRattachementHabitation, User,
)

URL_RATTACHEMENTS = "/api/rattachements-habitations/"

# Les deux chemins d'inscription, testés tous les deux : ils partagent `UserSerializer`, mais
# ils ont déjà divergé (le 25/10/2026, sur l'envoi des emails de cycle de vie) et rien dans le
# code n'empêche que cela se reproduise.
CHEMINS_INSCRIPTION = ["auth_register", "user-register"]


@pytest.mark.django_db
class TestInscriptionExigeLePrenom:

    @pytest.mark.parametrize("route", CHEMINS_INSCRIPTION)
    def test_une_inscription_sans_prenom_est_refusee(self, api_client, user_data, route):
        payload = {**user_data, "email": f"sans-prenom-{route}@x.fr",
                   "username": f"sans-prenom-{route}@x.fr"}
        payload.pop("first_name")
        reponse = api_client.post(reverse(route), payload, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "first_name" in reponse.data
        assert not User.objects.filter(
            email_bidx=blind_index(f"sans-prenom-{route}@x.fr")).exists()

    def test_un_prenom_fait_d_espaces_ne_compte_pas(self, api_client, user_data):
        """Sinon la contrainte se contourne sans même le vouloir : un champ laissé à un espace
        par un copier-coller passerait, et le compte serait aussi anonyme qu'avant."""
        payload = {**user_data, "email": "espaces@x.fr", "username": "espaces@x.fr",
                   "first_name": "   "}
        reponse = api_client.post(reverse("auth_register"), payload, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "first_name" in reponse.data

    def test_une_inscription_sans_nom_est_refusee(self, api_client, user_data):
        payload = {**user_data, "email": "sans-nom@x.fr", "username": "sans-nom@x.fr"}
        payload.pop("last_name")
        reponse = api_client.post(reverse("auth_register"), payload, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "last_name" in reponse.data

    @pytest.mark.parametrize("type_compte", ["UTIL_SIMPLE", "AUT_LOCALE", "SECOURS"])
    def test_la_regle_vaut_pour_TOUS_les_types_de_compte(self, api_client, user_data,
                                                         type_compte):
        """Le cœur de la demande. C'est précisément pour les comptes institutionnels que le
        prénom était effacé — ce sont eux qu'on cherche à joindre nommément en crise."""
        payload = {**user_data, "email": f"x-{type_compte}@mairie-exemple.fr",
                   "username": f"x-{type_compte}@mairie-exemple.fr", "type": type_compte,
                   "institution_name": "Mairie Exemple"}
        payload.pop("first_name")
        reponse = api_client.post(reverse("auth_register"), payload, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "first_name" in reponse.data

    @pytest.mark.parametrize("route", CHEMINS_INSCRIPTION)
    def test_une_inscription_complete_passe(self, api_client, user_data, route):
        payload = {**user_data, "email": f"complet-{route}@x.fr",
                   "username": f"complet-{route}@x.fr"}
        reponse = api_client.post(reverse(route), payload, format="json")
        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        cree = User.objects.get(email_bidx=blind_index(f"complet-{route}@x.fr"))
        assert cree.first_name == "Test" and cree.last_name == "User"

    def test_modifier_son_profil_n_exige_pas_de_renvoyer_son_nom(self, create_user):
        """La règle appartient à la création. Si elle vivait sur le champ, changer un numéro de
        téléphone demanderait de renvoyer son identité — et échouerait sans elle."""
        utilisateur = create_user(username="profil@x.fr", email="profil@x.fr",
                                  first_name="Jean", last_name="Dupont")
        client = APIClient()
        client.force_authenticate(user=utilisateur)
        reponse = client.patch(f"/api/users/{utilisateur.id}/",
                               {"phone_number": "0601020304"}, format="json")
        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        utilisateur.refresh_from_db()
        assert utilisateur.first_name == "Jean"


@pytest.mark.django_db
class TestRattachementHabitationExigeLePrenom:

    @pytest.fixture
    def habitation(self, db):
        return Habitation.objects.create(adresse="3 rue des Tests", commune_code="38185",
                                         commune_nom="Grenoble")

    def _demande(self, habitation, **extra):
        charge = {"habitation": str(habitation.id), "nom_demandeur": "Dupont",
                  "email_demandeur": "proprio@x.fr", "type_lien": "PROPRIETAIRE"}
        charge.update(extra)
        return APIClient().post(URL_RATTACHEMENTS, charge, format="json")

    def test_une_demande_sans_prenom_est_refusee(self, habitation):
        reponse = self._demande(habitation)
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "prenom_demandeur" in reponse.data

    def test_une_demande_complete_passe(self, habitation):
        reponse = self._demande(habitation, prenom_demandeur="Jean")
        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        rattachement = RattachementHabitation.objects.get()
        assert rattachement.prenom_demandeur == "Jean"
        assert rattachement.nom_demandeur == "Dupont"

    def test_l_identite_se_compose_au_meme_endroit_pour_tout_le_monde(self, habitation):
        """Quatre endroits affichent cette identité (journal, notification, deux emails). S'ils
        la recomposaient chacun, un écran dirait « Dupont » et un autre « Jean Dupont »."""
        rattachement = RattachementHabitation.objects.create(
            habitation=habitation, prenom_demandeur="Jean", nom_demandeur="Dupont",
            email_demandeur="proprio@x.fr", type_lien="PROPRIETAIRE")
        assert rattachement.identite_demandeur == "Jean Dupont"
        assert rattachement.salutation_demandeur == "Jean"

    def test_le_compte_cree_reprend_les_deux_champs_sans_rien_decouper(self, habitation):
        """Le défaut d'origine : un prénom composé ou un nom en deux mots partait du mauvais
        côté de la coupure, et le compte gardait cette identité fausse pour toujours."""
        rattachement = RattachementHabitation.objects.create(
            habitation=habitation, prenom_demandeur="Jean Pierre", nom_demandeur="Dupont",
            email_demandeur="compose@x.fr", type_lien="PROPRIETAIRE")
        assert rattachement.noms_pour_compte == ("Jean Pierre", "Dupont")

    def test_une_demande_anterieure_est_decoupee_en_dernier_recours(self, habitation):
        """Le repli ne sert QUE les demandes d'avant le 11/11/2026. Il reste faux pour un nom
        composé — c'est pour cela qu'on a séparé le champ au lieu de mieux découper."""
        ancienne = RattachementHabitation.objects.create(
            habitation=habitation, prenom_demandeur="", nom_demandeur="Jean Dupont",
            email_demandeur="ancien-decoupe@x.fr", type_lien="PROPRIETAIRE")
        assert ancienne.noms_pour_compte == ("Jean", "Dupont")

    def test_un_seul_mot_reste_un_patronyme_et_n_invente_pas_de_prenom(self, habitation):
        ancienne = RattachementHabitation.objects.create(
            habitation=habitation, prenom_demandeur="", nom_demandeur="Dupont",
            email_demandeur="un-mot@x.fr", type_lien="LOCATAIRE")
        assert ancienne.noms_pour_compte == ("", "Dupont")

    def test_une_demande_anterieure_sans_prenom_reste_lisible(self, habitation):
        """On ne découpe PAS les lignes existantes : couper au premier espace est exactement ce
        qui produisait l'erreur. Elles retombent donc sur le seul nom."""
        ancienne = RattachementHabitation.objects.create(
            habitation=habitation, prenom_demandeur="", nom_demandeur="Jean Pierre Dupont",
            email_demandeur="ancien@x.fr", type_lien="LOCATAIRE")
        assert ancienne.identite_demandeur == "Jean Pierre Dupont"
        # Saluer par le patronyme est ce que faisaient ces emails faute de prénom séparé.
        assert ancienne.salutation_demandeur == "Jean Pierre Dupont"
