"""Droit d'accès au domaine radio (core/acces_radio.py) et son octroi.

Trois décisions sont verrouillées ici, parce qu'elles ne se devinent pas à la lecture :

1. **Le droit vient du MATÉRIEL avant de venir d'une décision.** Porter un nœud personnel actif
   ouvre le niveau opérateur sans demander la permission à personne : c'est le propriétaire qui
   règle son appareil. Une demande nominative sert aux cas que le matériel ne prouve pas.
2. **La passerelle n'est pas un nœud comme les autres.** Un opérateur écrit sur ses propres
   nœuds, jamais sur la passerelle : elle porte tout un réseau, et un nœud rendu muet par une
   mauvaise région ne peut plus recevoir l'ordre inverse.
3. **Le rôle administrateur est pris au sens RÉEL.** Un `demo_role` prêté le temps d'une
   démonstration ne donne pas la main sur du matériel qui émet, et un nœud de la zone DEMO
   n'ouvre aucun droit — il n'existe pas physiquement.
"""
import pytest
from rest_framework.test import APIClient

from core.acces_radio import (
    etat_acces_radio, niveau_acces_radio, peut_administrer_noeud,
)
from core.models import (
    CompagnonMeshtastic, DemandeAccesRadio, Environment, Institution, InstitutionType,
    MeshtasticConnexionType, NiveauAccesRadio, NoeudUtilisateurMeshtastic,
    StatutDemandeAccesRadio, TacheAdminMeshtastic,
)

URL_DEMANDES = "/api/demandes-acces-radio/"
URL_MON_ACCES = "/api/demandes-acces-radio/mon-acces/"
URL_TACHES = "/api/taches-admin-meshtastic/"


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Acces Radio", type=itype)


@pytest.fixture
def autre_institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Sans Radio", type=itype)


def _utilisateur(create_user, email, type_role="UTIL_SIMPLE", institution=None, **extra):
    return create_user(username=email, email=email, type=type_role, institution=institution, **extra)


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.mark.django_db
class TestNiveauDAcces:

    def test_un_compte_sans_rien_n_a_aucun_acces(self, create_user):
        """Et c'est le cas qui compte : c'est lui qui voit la page /admin/radio et le bouton de
        demande. Si ce cas donnait l'accès, la porte d'entrée n'aurait aucune raison d'exister."""
        citoyen = _utilisateur(create_user, "citoyen-radio@x.fr")
        assert niveau_acces_radio(citoyen) == NiveauAccesRadio.AUCUN

    def test_porter_un_noeud_personnel_ouvre_le_niveau_operateur(self, create_user):
        """Sans demande, sans institution, sans rôle : le droit vient de l'appareil."""
        porteur = _utilisateur(create_user, "porteur-radio@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xAA01)
        assert niveau_acces_radio(porteur) == NiveauAccesRadio.OPERATEUR

    def test_un_noeud_desactive_n_ouvre_rien(self, create_user):
        porteur = _utilisateur(create_user, "porteur-inactif@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xAA02, actif=False)
        assert niveau_acces_radio(porteur) == NiveauAccesRadio.AUCUN

    def test_un_noeud_de_la_zone_demo_n_ouvre_rien(self, create_user):
        """La démonstration ne contient aucun matériel réel. Un nœud de démonstration qui
        ouvrirait le droit donnerait la main sur les vrais appareils de la zone PROD."""
        porteur = _utilisateur(create_user, "porteur-demo@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(
            utilisateur=porteur, node_num=0xAA03, environment=Environment.DEMO,
        )
        assert niveau_acces_radio(porteur) == NiveauAccesRadio.AUCUN

    def test_une_passerelle_de_l_institution_ouvre_le_niveau_operateur(self, create_user, institution):
        agent = _utilisateur(create_user, "agent-radio@x.fr", "SECOURS", institution)
        assert niveau_acces_radio(agent) == NiveauAccesRadio.AUCUN

        CompagnonMeshtastic.objects.create(
            nom="Passerelle mairie", node_num=0xB001, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM0",
        )
        assert niveau_acces_radio(agent) == NiveauAccesRadio.OPERATEUR

    def test_une_passerelle_sans_institution_n_ouvre_rien(self, create_user, institution):
        """« Quelqu'un, quelque part, a une passerelle » n'est pas un titre à administrer un
        réseau. Conséquence en exploitation : renseigner l'institution des companions existants
        est ce qui rend le menu radio visible aux agents de cette collectivité."""
        agent = _utilisateur(create_user, "agent-orphelin@x.fr", "SECOURS", institution)
        CompagnonMeshtastic.objects.create(
            nom="Passerelle centrale", node_num=0xB002, institution=None,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM1",
        )
        assert niveau_acces_radio(agent) == NiveauAccesRadio.AUCUN

    def test_une_passerelle_d_une_AUTRE_institution_n_ouvre_rien(self, create_user, institution,
                                                                 autre_institution):
        agent = _utilisateur(create_user, "agent-voisin@x.fr", "SECOURS", autre_institution)
        CompagnonMeshtastic.objects.create(
            nom="Passerelle d'a cote", node_num=0xB003, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM2",
        )
        assert niveau_acces_radio(agent) == NiveauAccesRadio.AUCUN

    def test_un_administrateur_reel_a_tout(self, create_user):
        admin = _utilisateur(create_user, "admin-radio@x.fr", "ADMIN")
        assert niveau_acces_radio(admin) == NiveauAccesRadio.ADMINISTRATEUR

    def test_un_role_de_demonstration_ne_donne_pas_l_administration(self, create_user):
        """Même raisonnement que les secrets radio (permissions.EstComptePont) : un rôle prêté
        pour une démonstration ne doit pas donner la main sur du matériel qui émet."""
        emprunteur = _utilisateur(create_user, "demo-admin-radio@x.fr", "UTIL_SIMPLE",
                                  demo_role="ADMIN")
        assert niveau_acces_radio(emprunteur) == NiveauAccesRadio.AUCUN

    def test_un_droit_accorde_ouvre_le_niveau_accorde(self, create_user):
        beneficiaire = _utilisateur(create_user, "beneficiaire-radio@x.fr")
        DemandeAccesRadio.objects.create(
            utilisateur=beneficiaire, motif="J'exploite le repeteur du chateau d'eau.",
            niveau_demande=NiveauAccesRadio.ADMINISTRATEUR,
            statut=StatutDemandeAccesRadio.ACCORDEE,
            niveau_accorde=NiveauAccesRadio.ADMINISTRATEUR,
        )
        assert niveau_acces_radio(beneficiaire) == NiveauAccesRadio.ADMINISTRATEUR

    def test_une_demande_en_attente_n_ouvre_rien(self, create_user):
        demandeur = _utilisateur(create_user, "demandeur-radio@x.fr")
        DemandeAccesRadio.objects.create(utilisateur=demandeur, motif="Je voudrais essayer.")
        assert niveau_acces_radio(demandeur) == NiveauAccesRadio.AUCUN

    def test_un_droit_retire_ferme_l_acces(self, create_user):
        ancien = _utilisateur(create_user, "ancien-radio@x.fr")
        demande = DemandeAccesRadio.objects.create(
            utilisateur=ancien, motif="Operateur du reseau.",
            statut=StatutDemandeAccesRadio.ACCORDEE, niveau_accorde=NiveauAccesRadio.OPERATEUR,
        )
        assert niveau_acces_radio(ancien) == NiveauAccesRadio.OPERATEUR

        demande.statut = StatutDemandeAccesRadio.RETIREE
        demande.niveau_accorde = None
        demande.save()
        assert niveau_acces_radio(ancien) == NiveauAccesRadio.AUCUN
        # La ligne survit : « qui avait ce droit en novembre ? » reste une question à laquelle
        # on peut répondre.
        assert DemandeAccesRadio.objects.filter(utilisateur=ancien).count() == 1


@pytest.mark.django_db
class TestDroitSurUnNoeud:

    def test_un_operateur_ecrit_sur_SON_noeud(self, create_user):
        porteur = _utilisateur(create_user, "porteur-ecriture@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xC001)
        assert peut_administrer_noeud(porteur, 0xC001) is True

    def test_un_operateur_n_ecrit_pas_sur_le_noeud_d_un_autre(self, create_user):
        porteur = _utilisateur(create_user, "porteur-indiscret@x.fr")
        voisin = _utilisateur(create_user, "voisin-noeud@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xC002)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=voisin, node_num=0xC003)
        assert peut_administrer_noeud(porteur, 0xC003) is False

    def test_un_operateur_n_ecrit_pas_sur_la_passerelle(self, create_user, institution):
        """Infrastructure partagée : une région ou un rapport cyclique faux la rend muette, et
        il faut alors aller la chercher à la main."""
        agent = _utilisateur(create_user, "agent-passerelle@x.fr", "SECOURS", institution)
        CompagnonMeshtastic.objects.create(
            nom="Passerelle", node_num=0xB004, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM3",
        )
        assert niveau_acces_radio(agent) == NiveauAccesRadio.OPERATEUR
        assert peut_administrer_noeud(agent, None) is False

    def test_un_administrateur_ecrit_partout_passerelle_comprise(self, create_user):
        admin = _utilisateur(create_user, "admin-ecriture@x.fr", "ADMIN")
        assert peut_administrer_noeud(admin, None) is True
        assert peut_administrer_noeud(admin, 0xC004) is True

    def test_un_compte_sans_acces_n_ecrit_nulle_part(self, create_user):
        citoyen = _utilisateur(create_user, "citoyen-ecriture@x.fr")
        assert peut_administrer_noeud(citoyen, 0xC005) is False
        assert peut_administrer_noeud(citoyen, None) is False


@pytest.mark.django_db
class TestEcritureParLAPI:
    """Le bout du fil : ce que l'API accepte réellement de créer comme tâche d'écriture."""

    @pytest.fixture
    def passerelle(self, institution):
        return CompagnonMeshtastic.objects.create(
            nom="Passerelle API", node_num=0xD001, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM4",
        )

    def test_un_porteur_reconfigure_son_propre_noeud(self, create_user, passerelle):
        porteur = _utilisateur(create_user, "porteur-api@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xD010)

        reponse = _client(porteur).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "node_num_cible": 0xD010,
            "type_tache": "DEFINIR_PUISSANCE", "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 201, reponse.data
        assert TacheAdminMeshtastic.objects.get().node_num_cible == 0xD010

    def test_un_porteur_ne_reconfigure_pas_le_noeud_d_un_autre(self, create_user, passerelle):
        porteur = _utilisateur(create_user, "porteur-api-2@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xD011)

        reponse = _client(porteur).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "node_num_cible": 0xD012,
            "type_tache": "DEFINIR_PUISSANCE", "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 403
        assert "vos propres" in str(reponse.data).lower()
        assert TacheAdminMeshtastic.objects.count() == 0

    def test_un_porteur_ne_reconfigure_pas_la_passerelle(self, create_user, passerelle):
        porteur = _utilisateur(create_user, "porteur-api-3@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xD013)

        reponse = _client(porteur).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 403
        assert "administrateurs" in str(reponse.data).lower()

    def test_un_porteur_peut_lire_la_configuration(self, create_user, passerelle):
        """Une lecture reste une lecture : relever une puissance n'est pas un acte matériel.
        C'est aussi la seule façon pour l'opérateur de savoir ce que son nœud fait."""
        porteur = _utilisateur(create_user, "porteur-api-4@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xD014)

        reponse = _client(porteur).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "node_num_cible": 0xD014,
            "type_tache": "LIRE_CONFIG_LORA",
        }, format="json")
        assert reponse.status_code == 201, reponse.data

    def test_un_compte_sans_acces_radio_ne_voit_meme_pas_la_file(self, create_user, passerelle):
        citoyen = _utilisateur(create_user, "citoyen-file@x.fr")
        reponse = _client(citoyen).get(URL_TACHES)
        assert reponse.status_code == 403


@pytest.mark.django_db
class TestDemandeEtInstruction:

    def test_tout_compte_authentifie_peut_demander(self, create_user):
        """La porte d'entrée : un bénévole qui porte un nœud n'est pas une institution, et une
        commune sans radio doit pouvoir en demander une."""
        citoyen = _utilisateur(create_user, "demandeur-1@x.fr")
        reponse = _client(citoyen).post(URL_DEMANDES, {
            "niveau_demande": "OPERATEUR", "motif": "Je porte un T-Beam pour l'equipe.",
        }, format="json")
        assert reponse.status_code == 201
        demande = DemandeAccesRadio.objects.get()
        assert demande.utilisateur == citoyen
        assert demande.statut == StatutDemandeAccesRadio.EN_ATTENTE

    def test_un_motif_vide_est_refuse(self, create_user):
        """La seule pièce du dossier. L'instructeur ne peut pas inventer le matériel détenu."""
        citoyen = _utilisateur(create_user, "demandeur-2@x.fr")
        reponse = _client(citoyen).post(URL_DEMANDES, {
            "niveau_demande": "OPERATEUR", "motif": "   ",
        }, format="json")
        assert reponse.status_code == 400

    def test_une_seconde_demande_en_attente_est_refusee(self, create_user):
        citoyen = _utilisateur(create_user, "demandeur-3@x.fr")
        client = _client(citoyen)
        client.post(URL_DEMANDES, {"niveau_demande": "OPERATEUR", "motif": "Un noeud."},
                    format="json")
        reponse = client.post(URL_DEMANDES, {"niveau_demande": "OPERATEUR", "motif": "Encore."},
                              format="json")
        assert reponse.status_code == 400
        assert DemandeAccesRadio.objects.count() == 1

    def test_demander_aucun_acces_n_a_pas_de_sens(self, create_user):
        citoyen = _utilisateur(create_user, "demandeur-4@x.fr")
        reponse = _client(citoyen).post(URL_DEMANDES, {
            "niveau_demande": "AUCUN", "motif": "Rien du tout.",
        }, format="json")
        assert reponse.status_code == 400

    def test_chacun_ne_voit_que_ses_demandes(self, create_user):
        """Le motif déclare du matériel détenu et un rattachement : ce n'est pas public."""
        un = _utilisateur(create_user, "demandeur-5@x.fr")
        deux = _utilisateur(create_user, "demandeur-6@x.fr")
        DemandeAccesRadio.objects.create(utilisateur=un, motif="Mon noeud.")
        DemandeAccesRadio.objects.create(utilisateur=deux, motif="Le sien.")

        reponse = _client(un).get(URL_DEMANDES)
        assert reponse.status_code == 200
        assert len(reponse.data) == 1
        assert reponse.data[0]["motif"] == "Mon noeud."

    def test_un_administrateur_voit_tout(self, create_user):
        un = _utilisateur(create_user, "demandeur-7@x.fr")
        DemandeAccesRadio.objects.create(utilisateur=un, motif="Mon noeud.")
        admin = _utilisateur(create_user, "admin-instruction@x.fr", "ADMIN")

        reponse = _client(admin).get(URL_DEMANDES)
        assert len(reponse.data) == 1

    def test_seul_un_administrateur_instruit(self, create_user, institution):
        """Et pas un acteur institutionnel : accorder le droit d'écrire sur du matériel radio
        n'est pas une opération de conduite de crise."""
        demandeur = _utilisateur(create_user, "demandeur-8@x.fr")
        demande = DemandeAccesRadio.objects.create(utilisateur=demandeur, motif="Mon noeud.")
        agent = _utilisateur(create_user, "agent-instruction@x.fr", "SECOURS", institution)

        reponse = _client(agent).post(f"{URL_DEMANDES}{demande.id}/instruire/", {
            "decision": "ACCORDEE", "niveau_accorde": "ADMINISTRATEUR",
        }, format="json")
        assert reponse.status_code == 403
        demande.refresh_from_db()
        assert demande.statut == StatutDemandeAccesRadio.EN_ATTENTE

    def test_un_administrateur_accorde_et_le_droit_s_ouvre(self, create_user):
        demandeur = _utilisateur(create_user, "demandeur-9@x.fr")
        demande = DemandeAccesRadio.objects.create(
            utilisateur=demandeur, motif="J'exploite le repeteur.",
            niveau_demande=NiveauAccesRadio.ADMINISTRATEUR,
        )
        admin = _utilisateur(create_user, "admin-instruction-2@x.fr", "ADMIN")

        reponse = _client(admin).post(f"{URL_DEMANDES}{demande.id}/instruire/", {
            "decision": "ACCORDEE", "niveau_accorde": "OPERATEUR",
            "commentaire": "Operateur suffit pour ce besoin.",
        }, format="json")
        assert reponse.status_code == 200
        demande.refresh_from_db()
        # Accorder MOINS que demandé est une décision, pas un refus.
        assert demande.niveau_accorde == NiveauAccesRadio.OPERATEUR
        assert demande.instruite_par == admin
        assert demande.date_decision is not None
        assert niveau_acces_radio(demandeur) == NiveauAccesRadio.OPERATEUR

    def test_un_refus_n_accorde_aucun_niveau(self, create_user):
        """Une ligne refusée qui garderait un niveau se relit comme un droit."""
        demandeur = _utilisateur(create_user, "demandeur-10@x.fr")
        demande = DemandeAccesRadio.objects.create(
            utilisateur=demandeur, motif="Je voudrais bien.",
            niveau_demande=NiveauAccesRadio.ADMINISTRATEUR,
        )
        admin = _utilisateur(create_user, "admin-instruction-3@x.fr", "ADMIN")

        reponse = _client(admin).post(f"{URL_DEMANDES}{demande.id}/instruire/", {
            "decision": "REFUSEE", "niveau_accorde": "ADMINISTRATEUR",
        }, format="json")
        assert reponse.status_code == 200
        demande.refresh_from_db()
        assert demande.niveau_accorde is None
        assert niveau_acces_radio(demandeur) == NiveauAccesRadio.AUCUN

    def test_accorder_sans_niveau_est_refuse(self, create_user):
        """Le niveau n'est jamais déduit du niveau demandé en silence."""
        demandeur = _utilisateur(create_user, "demandeur-11@x.fr")
        demande = DemandeAccesRadio.objects.create(utilisateur=demandeur, motif="Mon noeud.")
        admin = _utilisateur(create_user, "admin-instruction-4@x.fr", "ADMIN")

        reponse = _client(admin).post(f"{URL_DEMANDES}{demande.id}/instruire/", {
            "decision": "ACCORDEE",
        }, format="json")
        assert reponse.status_code == 400

    def test_un_demandeur_ne_peut_pas_s_accorder_le_droit(self, create_user):
        """Pas de PATCH sur la ressource : sinon le statut se modifierait tout seul."""
        demandeur = _utilisateur(create_user, "demandeur-12@x.fr")
        demande = DemandeAccesRadio.objects.create(utilisateur=demandeur, motif="Mon noeud.")

        reponse = _client(demandeur).patch(f"{URL_DEMANDES}{demande.id}/", {
            "statut": "ACCORDEE", "niveau_accorde": "ADMINISTRATEUR",
        }, format="json")
        assert reponse.status_code == 405
        demande.refresh_from_db()
        assert demande.statut == StatutDemandeAccesRadio.EN_ATTENTE


@pytest.mark.django_db
class TestMonAcces:

    def test_mon_acces_est_ouvert_meme_sans_aucun_droit(self, create_user):
        """C'est là que se trouvent l'explication et le bouton de demande : le fermer aux
        comptes sans droit fermerait la porte d'entrée du domaine."""
        citoyen = _utilisateur(create_user, "mon-acces-1@x.fr")
        reponse = _client(citoyen).get(URL_MON_ACCES)
        assert reponse.status_code == 200
        assert reponse.data["niveau"] == NiveauAccesRadio.AUCUN
        assert reponse.data["motifs"] == []
        # Ce qu'il faut pour entrer, servi par le serveur et non réinventé par l'interface.
        assert len(reponse.data["titres_possibles"]) == 2

    def test_mon_acces_dit_a_quel_titre(self, create_user):
        """Un compte qui a l'accès doit savoir à quel titre, donc ce qu'il perdrait en
        désactivant son nœud."""
        porteur = _utilisateur(create_user, "mon-acces-2@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xE001)

        reponse = _client(porteur).get(URL_MON_ACCES)
        assert reponse.data["niveau"] == NiveauAccesRadio.OPERATEUR
        assert reponse.data["nombre_noeuds_personnels"] == 1
        assert any("nœud personnel" in motif for motif in reponse.data["motifs"])

    def test_mon_acces_rend_la_derniere_demande(self, create_user):
        demandeur = _utilisateur(create_user, "mon-acces-3@x.fr")
        DemandeAccesRadio.objects.create(utilisateur=demandeur, motif="Mon noeud.")

        reponse = _client(demandeur).get(URL_MON_ACCES)
        assert reponse.data["demande"]["statut"] == StatutDemandeAccesRadio.EN_ATTENTE

    def test_etat_acces_radio_compte_les_deux_protocoles(self, create_user, institution):
        """MeshCore et Meshtastic comptent tous les deux : c'est du matériel radio dans les deux
        cas, et l'opérateur n'a pas à savoir lequel ouvre son droit."""
        from core.models import NoeudMeshUtilisateur

        porteur = _utilisateur(create_user, "mon-acces-4@x.fr", "SECOURS", institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xE002)
        NoeudMeshUtilisateur.objects.create(utilisateur=porteur, pubkey_hex="ab" * 32)

        etat = etat_acces_radio(porteur)
        assert etat["nombre_noeuds_personnels"] == 2
        assert etat["niveau"] == NiveauAccesRadio.OPERATEUR


@pytest.mark.django_db
class TestZoneDemo:

    def test_le_demandeur_est_pseudonymise_en_zone_demo(self, create_user):
        """`User` est partagé entre les deux zones, contrairement au contenu : sans masquage,
        une démonstration afficherait le nom et l'adresse d'une vraie personne (voir
        permissions.nom_affichable et test_anonymisation_demo.py)."""
        demandeur = create_user(
            username="demo-masque@x.fr", email="demo-masque@x.fr", type="UTIL_SIMPLE",
            first_name="Jean", last_name="Dupont",
        )
        DemandeAccesRadio.objects.create(utilisateur=demandeur, motif="Mon noeud.")
        admin = _utilisateur(create_user, "admin-demo-radio@x.fr", "ADMIN")

        client = _client(admin)
        reponse = client.get(URL_DEMANDES, HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 200
        ligne = reponse.data[0]
        assert "Dupont" not in str(ligne)
        assert ligne["utilisateur_email"].endswith("@zone.demo")

        # En PROD, l'instructeur voit bien de qui il s'agit : deux bénévoles peuvent porter le
        # même nom, et un droit radio s'accorde nominativement.
        reponse = client.get(URL_DEMANDES)
        assert reponse.data[0]["utilisateur_nom"] == "Jean Dupont"
        assert reponse.data[0]["utilisateur_email"] == "demo-masque@x.fr"


@pytest.mark.django_db
class TestChampServiAuMenu:

    def test_le_profil_ne_calcule_le_niveau_que_pour_son_propre_compte(self, create_user):
        """Quatre requêtes par ligne sur la liste de /admin/utilisateurs serait un N+1 pour une
        information dont cette page ne fait rien. Les autres comptes rendent donc `null`."""
        porteur = _utilisateur(create_user, "profil-radio@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xF001)
        admin = _utilisateur(create_user, "admin-profil-radio@x.fr", "ADMIN")

        mien = _client(porteur).get("/api/me/")
        assert mien.status_code == 200
        assert mien.data["acces_radio"] is True
        assert mien.data["niveau_acces_radio"] == NiveauAccesRadio.OPERATEUR

        liste = _client(admin).get("/api/users/")
        assert liste.status_code == 200
        lignes = liste.data["results"] if isinstance(liste.data, dict) else liste.data
        autres = [l for l in lignes if l["email"] != "admin-profil-radio@x.fr"]
        assert autres, "la liste doit contenir au moins un autre compte"
        assert all(l["acces_radio"] is None for l in autres)
