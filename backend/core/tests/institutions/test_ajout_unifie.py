"""Les trois gestes d'ajout, partout les mêmes : `+` à la main, import de fichier, invitation.

Chantier du 28/10/2026. Avant : aucune destination n'offrait les trois, les cinq pages d'import
étaient absentes du menu, et **inviter une institution n'existait nulle part** — on ne pouvait
que la saisir à sa place, c'est-à-dire deviner son type et son orthographe, ce qui est
exactement ce qui fabriquait les doublons.

Deux choses sont vérifiées ici :

1. **Le mappage automatique des en-têtes.** L'étape de correspondance manuelle est le moment où
   un import se perd ; quand la mairie a téléchargé le fichier d'exemple et l'a rempli, elle
   n'apprend rien. On vérifie donc qu'un fichier aux en-têtes d'exemple passe sans mapping, que
   les variantes raisonnables (casse, accents, en-tête raccourci) passent aussi, et qu'un
   en-tête inconnu n'est PAS rapproché au plus proche.
2. **Les deux invitations qui manquaient** : une institution, et un contact dans l'annuaire
   d'une institution.
"""
import io

import pytest
from rest_framework.test import APIClient

from core.imports import (
    CHAMPS_PERSONNEL_COMMUNAL,
    LABELS_INSTITUTIONS,
    LABELS_PERSONNEL_COMMUNAL,
    exemple_csv_personnel_communal,
    mapping_depuis_entetes,
)
from core.crypto_fields import blind_index
from core.models import (
    ContactInstitution,
    Institution,
    InstitutionType,
    User,
    UserRole,
)

COMMUNE_CODE = "33063"


@pytest.fixture
def type_mairie(db):
    return InstitutionType.objects.create(code="MAIRIE_AJOUT_TEST", libelle="Mairie")


@pytest.fixture
def mairie(db, type_mairie):
    return Institution.objects.create(
        nom="Mairie ajout unifie test", type=type_mairie, commune_code=COMMUNE_CODE)


@pytest.fixture
def agent(create_user, mairie):
    user = create_user(username="agent-ajout@test.fr", email="agent-ajout@test.fr",
                       type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class TestMappageAutomatiqueDesEntetes:
    def test_le_fichier_d_exemple_se_mappe_tout_seul(self):
        """Le cas de loin le plus fréquent : télécharger l'exemple, le remplir, le renvoyer."""
        entetes = list(LABELS_PERSONNEL_COMMUNAL.values())

        mapping = mapping_depuis_entetes(entetes, LABELS_PERSONNEL_COMMUNAL)

        assert set(mapping) == set(CHAMPS_PERSONNEL_COMMUNAL)
        assert mapping["prenom"] == "Prénom"

    def test_reconnait_un_entete_tronque_avant_la_parenthese(self):
        """« Fonction (ex: Maire, 1er adjoint...) » raccourci en « Fonction » : c'est ce que
        fait n'importe qui en relisant son fichier."""
        mapping = mapping_depuis_entetes(["Nom", "Email", "Fonction"],
                                         LABELS_PERSONNEL_COMMUNAL)

        assert mapping["fonction"] == "Fonction"

    def test_ignore_casse_accents_et_espaces(self):
        mapping = mapping_depuis_entetes(["  PRENOM ", "telephone", "E-Mail"],
                                         LABELS_PERSONNEL_COMMUNAL)

        assert mapping["prenom"] == "  PRENOM "
        assert mapping["telephone"] == "telephone"
        # « E-Mail » n'est pas « Email » : on ne devine pas, voir le test suivant.
        assert "email" not in mapping

    def test_reconnait_le_nom_technique_du_champ(self):
        """Un export fait depuis un autre outil porte souvent le nom technique."""
        mapping = mapping_depuis_entetes(["prenom", "nom", "email"],
                                         LABELS_PERSONNEL_COMMUNAL)

        assert mapping == {"prenom": "prenom", "nom": "nom", "email": "email"}

    def test_ne_rapproche_pas_au_plus_proche(self):
        """Un en-tête inconnu est laissé de côté, pas rattaché à la louche : un import qui
        devine mal est pire qu'un import qui demande."""
        mapping = mapping_depuis_entetes(["Identite complete", "Coordonnees"],
                                         LABELS_PERSONNEL_COMMUNAL)

        assert mapping == {}

    def test_la_premiere_colonne_reconnue_gagne(self):
        """Un fichier à deux colonnes « Nom » ne doit pas voir la seconde, souvent vide,
        écraser la première."""
        mapping = mapping_depuis_entetes(["Nom", "Prénom", "Nom"], LABELS_PERSONNEL_COMMUNAL)

        assert mapping["nom"] == "Nom"

    def test_chaque_import_a_son_propre_vocabulaire(self):
        """Les champs cibles restent une liste fermée par import : aucune colonne hors de
        `labels` n'est jamais lue (garde-fou du module, qui tient la promesse « jamais de
        donnée de santé »)."""
        mapping = mapping_depuis_entetes(["Nom", "Type", "Prénom"], LABELS_INSTITUTIONS)

        assert "prenom" not in mapping
        assert mapping["nom"] == "Nom"
        assert mapping["type"] == "Type"


@pytest.mark.django_db
class TestImportSansEtapeDeCorrespondance:
    def test_un_fichier_d_exemple_rempli_s_importe_sans_mapping(self, agent, mairie):
        fichier = io.BytesIO(exemple_csv_personnel_communal().encode("utf-8"))
        fichier.name = "personnel.csv"

        response = _client(agent).post(
            "/api/imports/personnel-communal/", {"fichier": fichier}, format="multipart")

        assert response.status_code == 200, response.data
        # Les deux lignes d'exemple sont devenues des comptes rattachés.
        assert ContactInstitution.objects.filter(
            institution=mairie, utilisateur__email_bidx=blind_index("jeanne.martin@mairie-exemple.fr"),
        ).exists()

    def test_un_fichier_aux_entetes_maison_est_refuse_en_nommant_les_colonnes(self, agent):
        """Le refus doit nommer ce qui n'a pas été reconnu et dire quoi faire — « les colonnes
        Email et Nom doivent être associées » ne disait ni laquelle manquait ni comment s'en
        sortir."""
        fichier = io.BytesIO("Identite;Coordonnees\nDupont;0600000000\n".encode("utf-8"))
        fichier.name = "maison.csv"

        response = _client(agent).post(
            "/api/imports/personnel-communal/", {"fichier": fichier}, format="multipart")

        assert response.status_code == 400
        assert "Nom" in response.data["error"]
        assert "Email" in response.data["error"]
        assert "exemple" in response.data["error"]

    def test_une_correspondance_explicite_garde_la_main(self, agent, mairie):
        """L'assistant en deux étapes reste indispensable pour un fichier aux en-têtes maison :
        une correspondance fournie ne doit jamais être écrasée par la déduction."""
        fichier = io.BytesIO(
            "Identite;Courriel\nDurand;paul.durand2@mairie-exemple.fr\n".encode("utf-8"))
        fichier.name = "maison.csv"

        response = _client(agent).post("/api/imports/personnel-communal/", {
            "fichier": fichier, "mapping_nom": "Identite", "mapping_email": "Courriel",
        }, format="multipart")

        assert response.status_code == 200, response.data
        assert ContactInstitution.objects.filter(
            institution=mairie, utilisateur__email_bidx=blind_index("paul.durand2@mairie-exemple.fr"),
        ).exists()


@pytest.mark.django_db
class TestInvitationDInstitution:
    URL = "/api/institutions/inviter/"

    def test_invite_une_institution_qui_se_creera_elle_meme(self, agent, type_mairie):
        response = _client(agent).post(self.URL, {
            "email": "mairie.voisine@exemple.fr",
            "nom": "Mairie de Exemple-sur-Loire",
            "type": "Mairie",
        }, format="json")

        assert response.status_code == 201, response.data
        invite = User.objects.get(email_bidx=blind_index("mairie.voisine@exemple.fr"))
        # Compte inactif, avec le prérempli : il complétera par le chemin d'inscription
        # existant et deviendra contact principal (creer_mon_institution).
        assert invite.is_active is False
        assert invite.pending_institution_name == "Mairie de Exemple-sur-Loire"
        assert invite.pending_institution_type == "Mairie"
        assert invite.institution_id is None
        # L'institution n'est PAS créée par l'invitant : c'est tout l'objet de l'invitation.
        assert not Institution.objects.filter(nom="Mairie de Exemple-sur-Loire").exists()

    def test_le_type_est_facultatif(self, agent):
        """Mieux vaut un type vide que deviné : le destinataire le sait, l'invitant pas
        toujours."""
        response = _client(agent).post(self.URL, {
            "email": "sans-type@exemple.fr", "nom": "Association sans type",
        }, format="json")

        assert response.status_code == 201, response.data
        assert User.objects.get(email_bidx=blind_index("sans-type@exemple.fr")).pending_institution_type is None

    def test_un_type_inconnu_est_refuse_sans_etre_cree(self, agent):
        """Même règle que l'import : un type d'institution structure les permissions, il ne se
        crée pas à la volée depuis une invitation."""
        response = _client(agent).post(self.URL, {
            "email": "type-inconnu@exemple.fr", "nom": "Quelque chose",
            "type": "Confrérie du cassoulet",
        }, format="json")

        assert response.status_code == 400
        assert "inconnu" in response.data["error"]
        assert not InstitutionType.objects.filter(libelle="Confrérie du cassoulet").exists()

    def test_refuse_une_institution_qui_existe_deja(self, agent, mairie):
        """Il n'y a personne à inviter : c'est un CONTACT qu'il faut inviter dans cette
        institution."""
        response = _client(agent).post(self.URL, {
            "email": "doublon@exemple.fr", "nom": mairie.nom.upper(),
        }, format="json")

        assert response.status_code == 400
        assert "existe déjà" in response.data["error"]

    def test_refuse_une_adresse_deja_rattachee(self, agent):
        response = _client(agent).post(self.URL, {
            "email": agent.email, "nom": "Une autre institution",
        }, format="json")

        assert response.status_code == 400
        assert "déjà rattachée" in response.data["error"]

    def test_un_compte_sans_institution_est_reutilise_et_non_recree(self, agent, create_user):
        """Ne pas recréer : un citoyen déjà inscrit qu'on invite comme institution garde son
        compte, on lui pose simplement le prérempli."""
        citoyen = create_user(username="citoyen@exemple.fr", email="citoyen@exemple.fr",
                              type="UTIL_SIMPLE")

        response = _client(agent).post(self.URL, {
            "email": "citoyen@exemple.fr", "nom": "Mairie de Citoyenville",
        }, format="json")

        assert response.status_code == 201, response.data
        assert User.objects.filter(email_bidx=blind_index("citoyen@exemple.fr")).count() == 1
        citoyen.refresh_from_db()
        assert citoyen.pending_institution_name == "Mairie de Citoyenville"


@pytest.mark.django_db
class TestInvitationDUnContactDansLAnnuaire:
    URL = "/api/contacts-institutions/inviter/"

    def test_invite_un_contact_par_son_seul_email(self, agent, mairie):
        """Prénom et nom facultatifs, contrairement à l'invitation d'équipe : on invite souvent
        depuis une adresse seule (dgs@mairie-x.fr), et exiger un nom qu'on ne connaît pas
        conduit à inventer « DGS DGS »."""
        response = _client(agent).post(self.URL, {
            "institution": str(mairie.id), "email": "dgs@mairie-x.fr", "fonction": "DGS",
        }, format="json")

        assert response.status_code == 201, response.data
        contact = ContactInstitution.objects.get(
            institution=mairie, utilisateur__email_bidx=blind_index("dgs@mairie-x.fr"))
        assert contact.fonction == "DGS"
        assert contact.utilisateur.is_active is False
        assert contact.utilisateur.type == UserRole.LOCAL_AUTHORITY

    def test_promeut_un_simple_utilisateur_sans_le_recreer(self, agent, mairie, create_user):
        """L'institution se porte garante de lui : beaucoup d'élus s'inscrivent avec une
        adresse personnelle, la validation de domaine n'a alors plus lieu d'être."""
        citoyen = create_user(username="elu-perso@gmail.com", email="elu-perso@gmail.com",
                              type="UTIL_SIMPLE")

        response = _client(agent).post(self.URL, {
            "institution": str(mairie.id), "email": "elu-perso@gmail.com",
        }, format="json")

        assert response.status_code == 201, response.data
        citoyen.refresh_from_db()
        assert citoyen.type == UserRole.LOCAL_AUTHORITY
        assert User.objects.filter(email_bidx=blind_index("elu-perso@gmail.com")).count() == 1

    def test_ne_retrograde_jamais_un_compte(self, agent, mairie, create_user):
        secouriste = create_user(username="secours@test.fr", email="secours@test.fr",
                                 type="SECOURS")

        response = _client(agent).post(self.URL, {
            "institution": str(mairie.id), "email": "secours@test.fr",
        }, format="json")

        assert response.status_code == 201, response.data
        secouriste.refresh_from_db()
        assert secouriste.type == UserRole.ORGANIZED_RESCUE

    def test_refuse_un_contact_deja_dans_l_annuaire(self, agent, mairie):
        response = _client(agent).post(self.URL, {
            "institution": str(mairie.id), "email": agent.email,
        }, format="json")

        assert response.status_code == 400
        assert "figure déjà" in response.data["error"]

    def test_on_n_invite_que_chez_soi(self, agent, type_mairie):
        """Même limite que pour une équipe : inviter dans l'annuaire d'une institution tierce
        reviendrait à lui imposer des membres."""
        autre = Institution.objects.create(nom="Mairie etrangere ajout", type=type_mairie)

        response = _client(agent).post(self.URL, {
            "institution": str(autre.id), "email": "intrus@exemple.fr",
        }, format="json")

        assert response.status_code == 403
        assert not ContactInstitution.objects.filter(institution=autre).exists()
