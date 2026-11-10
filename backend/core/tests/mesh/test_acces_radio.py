"""Droit d'accès au domaine radio (core/acces_radio.py) et son octroi.

Trois décisions sont verrouillées ici, parce qu'elles ne se devinent pas à la lecture :

1. **Le droit vient du MATÉRIEL avant de venir d'une décision.** Porter un nœud personnel actif
   ouvre le niveau opérateur sans demander la permission à personne : c'est le propriétaire qui
   règle son appareil. Une demande nominative sert aux cas que le matériel ne prouve pas.
2. **Le droit d'écrire suit la PROPRIÉTÉ du matériel**, pas un grade (précisé le 10/11/2026).
   Un particulier répond de ses nœuds ; une institution répond des nœuds de ses membres et des
   passerelles qu'elle a déployées — passerelle comprise, c'est elle qui ira la rechercher si un
   réglage la rend muette. Personne ne répond du matériel d'un autre, sauf l'administrateur de
   la plateforme, qui est le recours.
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

    def test_une_institution_qui_n_a_que_des_noeuds_a_l_acces(self, create_user, institution):
        """Une commune dont trois agents portent un nœud *a* un réseau radio, même sans
        passerelle : elle doit pouvoir le voir et le régler."""
        agent = _utilisateur(create_user, "agent-sans-passerelle@x.fr", "SECOURS", institution)
        assert niveau_acces_radio(agent) == NiveauAccesRadio.AUCUN

        porteur = _utilisateur(create_user, "porteur-de-l-equipe@x.fr", "SECOURS", institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xB020)
        assert niveau_acces_radio(agent) == NiveauAccesRadio.OPERATEUR

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

    def test_une_institution_regle_la_passerelle_qu_elle_a_deployee(self, create_user, institution):
        """Règle du 10/11/2026 : la passerelle est de la responsabilité de l'institution qui l'a
        posée. Faire dépendre son réglage d'un administrateur de plateforme n'ajoute aucune
        sécurité -- il ne sait même pas où elle est."""
        agent = _utilisateur(create_user, "agent-passerelle@x.fr", "SECOURS", institution)
        passerelle = CompagnonMeshtastic.objects.create(
            nom="Passerelle", node_num=0xB004, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM3",
        )
        assert niveau_acces_radio(agent) == NiveauAccesRadio.OPERATEUR
        # Comme exécutante de la tâche (node_num_cible vide)...
        assert peut_administrer_noeud(agent, None, passerelle) is True
        # ... et visée par son node_num, ce qui est le même matériel.
        assert peut_administrer_noeud(agent, 0xB004) is True

    def test_une_institution_ne_regle_pas_la_passerelle_d_une_autre(self, create_user,
                                                                    institution,
                                                                    autre_institution):
        """Le voisin ne répond pas de ce matériel, et il ne saura pas qu'il l'a cassé."""
        agent = _utilisateur(create_user, "agent-voisin-passerelle@x.fr", "SECOURS", autre_institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=agent, node_num=0xB010)
        passerelle = CompagnonMeshtastic.objects.create(
            nom="Passerelle d'a cote", node_num=0xB005, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM6",
        )
        assert niveau_acces_radio(agent) == NiveauAccesRadio.OPERATEUR
        assert peut_administrer_noeud(agent, None, passerelle) is False
        assert peut_administrer_noeud(agent, 0xB005) is False

    def test_une_passerelle_sans_institution_reste_a_l_administrateur(self, create_user):
        """Personne n'en répond : c'est précisément le cas où le recours sert."""
        porteur = _utilisateur(create_user, "porteur-sans-inst@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xB011)
        passerelle = CompagnonMeshtastic.objects.create(
            nom="Passerelle centrale", node_num=0xB006, institution=None,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM7",
        )
        assert peut_administrer_noeud(porteur, None, passerelle) is False

    def test_une_ecriture_sur_la_passerelle_sans_savoir_laquelle_est_refusee(self, create_user,
                                                                            institution):
        """Sans le companion, le droit n'est pas vérifiable : on refuse plutôt que de supposer."""
        agent = _utilisateur(create_user, "agent-sans-compagnon@x.fr", "SECOURS", institution)
        CompagnonMeshtastic.objects.create(
            nom="Passerelle", node_num=0xB007, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM8",
        )
        assert peut_administrer_noeud(agent, None) is False

    def test_une_institution_regle_le_noeud_de_ses_membres(self, create_user, institution):
        """« Les institutions qui ont des nœuds doivent avoir les droits dessus. » Le nœud remis
        par une collectivité à un agent n'est pas sa propriété privée, et l'agent parti en
        congés ne doit pas emporter avec lui la possibilité de le reconfigurer."""
        porteur = _utilisateur(create_user, "porteur-de-la-mairie@x.fr", "SECOURS", institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xB008)
        collegue = _utilisateur(create_user, "collegue-mairie@x.fr", "SECOURS", institution)

        assert niveau_acces_radio(collegue) == NiveauAccesRadio.OPERATEUR
        assert peut_administrer_noeud(collegue, 0xB008) is True

    def test_un_noeud_sans_rapport_reste_hors_de_portee(self, create_user, institution,
                                                        autre_institution):
        porteur = _utilisateur(create_user, "porteur-ailleurs@x.fr", "SECOURS", autre_institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xB009)
        agent = _utilisateur(create_user, "agent-curieux@x.fr", "SECOURS", institution)
        CompagnonMeshtastic.objects.create(
            nom="Passerelle", node_num=0xB00A, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM9",
        )
        assert peut_administrer_noeud(agent, 0xB009) is False

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
        # Le message dit les DEUX périmètres possibles : sinon le porteur croit qu'il lui
        # manque un droit alors qu'il lui manque un rattachement.
        assert "ni l'un des vôtres ni l'un de ceux de votre institution" in str(reponse.data)
        assert TacheAdminMeshtastic.objects.count() == 0

    def test_un_porteur_etranger_a_l_institution_ne_regle_pas_sa_passerelle(self, create_user,
                                                                            passerelle):
        """Le porteur n'appartient pas à l'institution qui a déployé cette passerelle : il n'en
        répond pas, et il ne saura pas qu'il l'a rendue muette."""
        porteur = _utilisateur(create_user, "porteur-api-3@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xD013)

        reponse = _client(porteur).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 403
        assert "institution" in str(reponse.data).lower()

    def test_un_agent_de_l_institution_regle_sa_passerelle(self, create_user, institution,
                                                           passerelle):
        """Le cas normal demandé le 10/11/2026 : la collectivité règle son propre matériel sans
        passer par un administrateur de plateforme."""
        agent = _utilisateur(create_user, "agent-api@x.fr", "SECOURS", institution)

        reponse = _client(agent).post(URL_TACHES, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 201, reponse.data
        tache = TacheAdminMeshtastic.objects.get()
        assert tache.node_num_cible is None       # la passerelle elle-même
        assert tache.demande_par == agent         # et l'acte reste imputable

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

    def test_accorder_la_portee_reseau_exige_une_confirmation(self, create_user):
        """« L'administrateur d'une passerelle est admin de SA passerelle et de SES nœuds »
        (10/11/2026). ADMINISTRATEUR ne répond pas à ce besoin-là : il donne la main sur le
        matériel des AUTRES institutions. Pour que quelqu'un administre son propre matériel, on
        le rattache à son institution et OPERATEUR suffit.

        La confirmation existe pour qu'on ne puisse pas accorder le réseau entier d'un clic en
        croyant répondre à « je veux gérer ma passerelle »."""
        demandeur = _utilisateur(create_user, "demandeur-portee@x.fr")
        demande = DemandeAccesRadio.objects.create(
            utilisateur=demandeur, motif="Je veux administrer ma passerelle.",
            niveau_demande=NiveauAccesRadio.ADMINISTRATEUR,
        )
        admin = _utilisateur(create_user, "admin-portee@x.fr", "ADMIN")
        client = _client(admin)

        reponse = client.post(f"{URL_DEMANDES}{demande.id}/instruire/", {
            "decision": "ACCORDEE", "niveau_accorde": "ADMINISTRATEUR",
        }, format="json")
        assert reponse.status_code == 400
        assert "tout le réseau" in str(reponse.data).lower()
        demande.refresh_from_db()
        assert demande.statut == StatutDemandeAccesRadio.EN_ATTENTE
        assert niveau_acces_radio(demandeur) == NiveauAccesRadio.AUCUN

        # OPERATEUR, en revanche, s'accorde sans cérémonie : il ne porte que sur le matériel du
        # demandeur et celui de son institution.
        reponse = client.post(f"{URL_DEMANDES}{demande.id}/instruire/", {
            "decision": "ACCORDEE", "niveau_accorde": "OPERATEUR",
        }, format="json")
        assert reponse.status_code == 200
        assert niveau_acces_radio(demandeur) == NiveauAccesRadio.OPERATEUR

    def test_la_portee_reseau_s_accorde_quand_c_est_l_intention(self, create_user):
        demandeur = _utilisateur(create_user, "demandeur-portee-2@x.fr")
        demande = DemandeAccesRadio.objects.create(
            utilisateur=demandeur, motif="Je depanne les passerelles sans institution.",
            niveau_demande=NiveauAccesRadio.ADMINISTRATEUR,
        )
        admin = _utilisateur(create_user, "admin-portee-2@x.fr", "ADMIN")

        reponse = _client(admin).post(f"{URL_DEMANDES}{demande.id}/instruire/", {
            "decision": "ACCORDEE", "niveau_accorde": "ADMINISTRATEUR",
            "confirmation_portee_reseau": True,
        }, format="json")
        assert reponse.status_code == 200
        assert niveau_acces_radio(demandeur) == NiveauAccesRadio.ADMINISTRATEUR

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
        # Ce qu'il faut pour entrer, servi par le serveur et non réinventé par l'interface :
        # son propre nœud, le nœud d'un membre de son institution, la passerelle de celle-ci.
        assert len(reponse.data["titres_possibles"]) == 3
        # Aucun périmètre d'écriture tant qu'il n'y a aucun droit : il n'y a rien à annoncer.
        assert reponse.data["perimetre_ecriture"] == []

    def test_mon_acces_dit_a_quel_titre(self, create_user):
        """Un compte qui a l'accès doit savoir à quel titre, donc ce qu'il perdrait en
        désactivant son nœud."""
        porteur = _utilisateur(create_user, "mon-acces-2@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xE001)

        reponse = _client(porteur).get(URL_MON_ACCES)
        assert reponse.data["niveau"] == NiveauAccesRadio.OPERATEUR
        assert reponse.data["nombre_noeuds_personnels"] == 1
        assert any("nœud personnel" in motif for motif in reponse.data["motifs"])

    def test_mon_acces_annonce_le_perimetre_d_ecriture(self, create_user, institution):
        """Le périmètre est rédigé par le serveur : la règle est déjà difficile à tenir à un
        endroit, et une interface qui promet une écriture que le serveur refuse se découvre par
        un 403."""
        agent = _utilisateur(create_user, "mon-acces-perimetre@x.fr", "SECOURS", institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=agent, node_num=0xE010)
        CompagnonMeshtastic.objects.create(
            nom="Passerelle", node_num=0xE011, institution=institution,
            connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACMA",
        )

        reponse = _client(agent).get(URL_MON_ACCES)
        portees = " ".join(reponse.data["perimetre_ecriture"])
        assert "Vos propres nœuds" in portees
        assert institution.nom in portees
        # Et la responsabilité est dite, parce que c'est elle qui ira rechercher la passerelle.
        assert "responsabilité de l'institution qui l'a déployée" in portees
        assert reponse.data["nombre_passerelles_institution"] == 1

    def test_un_administrateur_voit_que_son_perimetre_est_le_reseau_entier(self, create_user):
        admin = _utilisateur(create_user, "mon-acces-admin@x.fr", "ADMIN")
        reponse = _client(admin).get(URL_MON_ACCES)
        portees = " ".join(reponse.data["perimetre_ecriture"])
        assert "passerelles comprises" in portees

    def test_un_droit_accorde_sans_materiel_le_dit(self, create_user):
        """Cas ingrat : le droit est ouvert, mais aucune écriture n'aboutira. Mieux vaut
        l'annoncer que de le laisser découvrir par un 403."""
        beneficiaire = _utilisateur(create_user, "mon-acces-sans-materiel@x.fr")
        DemandeAccesRadio.objects.create(
            utilisateur=beneficiaire, motif="Je recois mon materiel la semaine prochaine.",
            statut=StatutDemandeAccesRadio.ACCORDEE, niveau_accorde=NiveauAccesRadio.OPERATEUR,
        )
        reponse = _client(beneficiaire).get(URL_MON_ACCES)
        portees = " ".join(reponse.data["perimetre_ecriture"])
        assert "Aucun matériel ne vous est rattaché" in portees

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


@pytest.mark.django_db
class TestRattachementDesRepeteurs:
    """« Il faut pouvoir les rattacher à un compte ou une institution » (10/11/2026).

    Avant cette table, un répéteur sur un point haut n'était le nœud personnel de personne,
    donc seul un administrateur de la plateforme pouvait le régler — alors que c'est la commune
    qui est allée l'installer."""

    URL = "/api/rattachements-noeuds-radio/"

    def test_un_repeteur_rattache_a_l_institution_devient_reglable_par_elle(self, create_user,
                                                                            institution):
        from core.models import RattachementNoeudRadio

        agent = _utilisateur(create_user, "agent-repeteur@x.fr", "SECOURS", institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=agent, node_num=0xF100)
        assert peut_administrer_noeud(agent, 0xF200) is False

        RattachementNoeudRadio.objects.create(
            node_num=0xF200, institution=institution, libelle="Repeteur du chateau d'eau",
        )
        assert peut_administrer_noeud(agent, 0xF200) is True

    def test_un_rattachement_au_compte_suffit_sans_institution(self, create_user):
        """Le radioamateur qui a posé un répéteur chez lui n'a pas d'institution."""
        from core.models import RattachementNoeudRadio

        particulier = _utilisateur(create_user, "radioamateur@x.fr")
        assert niveau_acces_radio(particulier) == NiveauAccesRadio.AUCUN

        RattachementNoeudRadio.objects.create(
            node_num=0xF201, utilisateur=particulier, libelle="Repeteur du toit",
        )
        assert niveau_acces_radio(particulier) == NiveauAccesRadio.OPERATEUR
        assert peut_administrer_noeud(particulier, 0xF201) is True

    def test_le_rattachement_d_une_autre_institution_n_ouvre_rien(self, create_user, institution,
                                                                  autre_institution):
        from core.models import RattachementNoeudRadio

        agent = _utilisateur(create_user, "agent-voisin-repeteur@x.fr", "SECOURS", autre_institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=agent, node_num=0xF101)
        RattachementNoeudRadio.objects.create(node_num=0xF202, institution=institution)
        assert peut_administrer_noeud(agent, 0xF202) is False

    def test_on_ne_rattache_qu_a_soi_ou_a_son_institution(self, create_user, institution,
                                                          autre_institution):
        """Rattacher un nœud à autrui lui donnerait un droit d'écriture dessus."""
        agent = _utilisateur(create_user, "agent-rattache@x.fr", "SECOURS", institution)
        client = _client(agent)

        reponse = client.post(self.URL, {
            "node_num": 0xF203, "institution": str(autre_institution.id),
        }, format="json")
        assert reponse.status_code == 403

        reponse = client.post(self.URL, {
            "node_num": 0xF203, "institution": str(institution.id), "libelle": "Le notre",
        }, format="json")
        assert reponse.status_code == 201, reponse.data

    def test_un_noeud_deja_rattache_ne_se_vole_pas(self, create_user, institution,
                                                   autre_institution):
        """L'unicité rend le conflit visible et arbitrable, au lieu de le régler au dernier
        arrivé."""
        from core.models import RattachementNoeudRadio

        RattachementNoeudRadio.objects.create(node_num=0xF204, institution=institution)
        agent = _utilisateur(create_user, "agent-voleur@x.fr", "SECOURS", autre_institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=agent, node_num=0xF102)

        reponse = _client(agent).post(self.URL, {
            "node_num": 0xF204, "institution": str(autre_institution.id),
        }, format="json")
        assert reponse.status_code == 400

    def test_on_ne_detache_pas_le_noeud_d_un_autre(self, create_user, institution,
                                                   autre_institution):
        """Sinon l'unicité ne protège plus rien : on libère, puis on s'attribue."""
        from core.models import RattachementNoeudRadio

        rattachement = RattachementNoeudRadio.objects.create(
            node_num=0xF205, institution=institution,
        )
        agent = _utilisateur(create_user, "agent-detacheur@x.fr", "SECOURS", autre_institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=agent, node_num=0xF103)

        reponse = _client(agent).delete(f"{self.URL}{rattachement.id}/")
        assert reponse.status_code == 403
        assert RattachementNoeudRadio.objects.filter(id=rattachement.id).exists()

    def test_une_institution_corrige_son_propre_rattachement(self, create_user, institution):
        from core.models import RattachementNoeudRadio

        rattachement = RattachementNoeudRadio.objects.create(
            node_num=0xF206, institution=institution,
        )
        agent = _utilisateur(create_user, "agent-correcteur@x.fr", "SECOURS", institution)

        reponse = _client(agent).delete(f"{self.URL}{rattachement.id}/")
        assert reponse.status_code == 204
        assert not RattachementNoeudRadio.objects.filter(id=rattachement.id).exists()

    def test_un_rattachement_sans_cible_est_refuse(self, create_user, institution):
        agent = _utilisateur(create_user, "agent-sans-cible@x.fr", "SECOURS", institution)
        reponse = _client(agent).post(self.URL, {"node_num": 0xF207}, format="json")
        assert reponse.status_code == 400

    def test_deux_cibles_a_la_fois_sont_refusees(self, create_user, institution):
        """« Qui en répond ? » doit avoir UNE réponse."""
        agent = _utilisateur(create_user, "agent-deux-cibles@x.fr", "SECOURS", institution)
        reponse = _client(agent).post(self.URL, {
            "node_num": 0xF208, "institution": str(institution.id), "utilisateur": str(agent.id),
        }, format="json")
        assert reponse.status_code == 400

    def test_un_administrateur_rattache_pour_le_compte_d_autrui(self, create_user, institution):
        """Le recours : une commune qui ne peut pas le faire elle-même."""
        admin = _utilisateur(create_user, "admin-rattachement@x.fr", "ADMIN")
        reponse = _client(admin).post(self.URL, {
            "node_num": 0xF209, "institution": str(institution.id), "libelle": "Pose par l'admin",
        }, format="json")
        assert reponse.status_code == 201

    def test_le_responsable_est_servi_en_un_seul_libelle(self, create_user, institution):
        """L'interface n'a pas à savoir laquelle des deux cibles est renseignée."""
        from core.models import RattachementNoeudRadio

        RattachementNoeudRadio.objects.create(
            node_num=0xF20A, institution=institution, libelle="Pylone",
        )
        agent = _utilisateur(create_user, "agent-lecture-rattachement@x.fr", "SECOURS", institution)
        reponse = _client(agent).get(self.URL)
        assert reponse.status_code == 200
        assert reponse.data[0]["responsable"] == institution.nom

    def test_un_compte_sans_acces_radio_ne_rattache_rien(self, create_user):
        citoyen = _utilisateur(create_user, "citoyen-rattachement@x.fr")
        reponse = _client(citoyen).post(self.URL, {
            "node_num": 0xF20B, "utilisateur": str(citoyen.id),
        }, format="json")
        # Poule et oeuf assumé : sans aucun matériel, on n'a pas accès au domaine radio, donc
        # pas même de quoi s'y rattacher un premier nœud. C'est la page /admin/radio qui sert
        # de porte d'entrée (un administrateur rattache, ou accorde le droit).
        assert reponse.status_code == 403


@pytest.mark.django_db
class TestRacineDeTopic:
    """La racine de topic d'une passerelle MQTT.

    Toute la documentation des réseaux Meshtastic montre le **chemin d'abonnement complet**
    (`msh/EU_868/2/e/#`), alors que ce champ attend la **racine seule** : le pont ajoute
    `/2/e/#`. Coller le chemin complet donnait `msh/EU_868/2/e/#/2/e/#`, et le symptôme était
    une connexion réussie sans jamais un paquet — constaté en production le 10/11/2026.
    """

    URL = "/api/compagnons-meshtastic/"

    @pytest.fixture
    def client_admin(self, create_user):
        return _client(_utilisateur(create_user, "admin-topic@x.fr", "ADMIN"))

    def _creer(self, client, racine, node_num=0xAB01):
        return client.post(self.URL, {
            "nom": "Passerelle topic", "node_num": node_num,
            "connexion_type": "MQTT", "broker_host": "mqtt-mt.exemple.re",
            "topic_racine": racine,
        }, format="json")

    @pytest.mark.parametrize("saisi", [
        "msh/EU_868/2/e/#",
        "msh/EU_868/2/e",
        "msh/EU_868/#",
        "msh/EU_868/",
        "  msh/EU_868  ",
        "/msh/EU_868/2/e/#/",
    ])
    def test_le_chemin_d_abonnement_colle_est_ramene_a_la_racine(self, client_admin, saisi):
        reponse = self._creer(client_admin, saisi)
        assert reponse.status_code == 201, reponse.data
        assert reponse.data["topic_racine"] == "msh/EU_868"

    def test_la_racine_de_gaulix_passe_telle_quelle(self, client_admin):
        """Le défaut historique du modèle ne doit pas être abîmé par la normalisation."""
        reponse = self._creer(client_admin, "Traitement/msh/EU_868")
        assert reponse.status_code == 201
        assert reponse.data["topic_racine"] == "Traitement/msh/EU_868"

    def test_un_joker_au_milieu_est_refuse_avec_la_raison(self, client_admin):
        """Pas rattrapable par devinette : on refuse en disant quoi faire, plutôt que de
        fabriquer une racine qui ne correspondrait à rien."""
        reponse = self._creer(client_admin, "msh/+/2/e")
        assert reponse.status_code == 400
        assert "joker" in str(reponse.data).lower()

    def test_une_racine_vide_est_refusee(self, client_admin):
        """Sans racine, le pont s'abonnerait à « /2/e/# » : un topic qui n'existe sur aucun
        broker, et le même silence qu'on vient de corriger."""
        reponse = self._creer(client_admin, "/#")
        assert reponse.status_code == 400
        assert "racine" in str(reponse.data).lower()


@pytest.mark.django_db
class TestReclamationRepeteurMeshCore:
    """« Il faut peut-être simplement remplir un formulaire quand on réclame un répéteur : soit
    login / mot de passe, soit le répéteur contient la clé de xxx » (10/11/2026).

    Ce que MeshCore change par rapport à Meshtastic : **les deux moyens sont vérifiables**. Un
    mot de passe d'administration se teste avec `send_login`, une entrée d'ACL avec
    `req_status`. Le droit d'écrire ne s'accorde donc pas sur déclaration — et il n'y a ici
    aucun filet côté firmware, contrairement à `security.admin_key` sur Meshtastic.
    """

    URL = "/api/rattachements-noeuds-radio/"
    CLE = "ab" * 32

    @pytest.fixture
    def compagnon_meshcore(self, institution):
        from core.models import CompagnonMeshCore, MeshCoreConnexionType

        return CompagnonMeshCore.objects.create(
            nom="Companion mairie", institution=institution,
            connexion_type=MeshCoreConnexionType.TCP, tcp_host="172.16.1.50",
        )

    @pytest.fixture
    def agent(self, create_user, institution, compagnon_meshcore):
        utilisateur = _utilisateur(create_user, "agent-meshcore@x.fr", "SECOURS", institution)
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=utilisateur, node_num=0x7001)
        return utilisateur

    def test_reclamer_par_mot_de_passe(self, agent, institution, compagnon_meshcore):
        reponse = _client(agent).post(self.URL, {
            "pubkey_hex": self.CLE, "institution": str(institution.id),
            "libelle": "Repeteur du piton", "moyen_admin": "MOT_DE_PASSE",
            "mot_de_passe": "secret-du-repeteur",
            "compagnon_meshcore": str(compagnon_meshcore.id),
        }, format="json")
        assert reponse.status_code == 201, reponse.data
        assert reponse.data["protocole"] == "MESHCORE"
        # Le mot de passe part, il ne revient jamais.
        assert "mot_de_passe" not in reponse.data
        # Et il n'ouvre encore AUCUNE écriture : la preuve n'est pas faite.
        assert reponse.data["statut_preuve"] == "NON_VERIFIE"
        assert reponse.data["preuve_faite"] is False
        from core.acces_radio import peut_administrer_noeud_meshcore
        assert peut_administrer_noeud_meshcore(agent, self.CLE) is False

    def test_reclamer_par_acl(self, agent, institution, compagnon_meshcore):
        """« Le répéteur contient la clé de xxx » : pas de mot de passe, c'est la clé publique du
        companion que l'ACL reconnaît (firmware : un mot de passe vide fait vérifier l'ACL)."""
        reponse = _client(agent).post(self.URL, {
            "pubkey_hex": self.CLE, "institution": str(institution.id),
            "moyen_admin": "ACL", "compagnon_meshcore": str(compagnon_meshcore.id),
        }, format="json")
        assert reponse.status_code == 201, reponse.data
        assert reponse.data["moyen_admin"] == "ACL"

    def test_un_mot_de_passe_avec_la_voie_acl_est_refuse(self, agent, institution,
                                                         compagnon_meshcore):
        """Les deux à la fois ne décrivent aucun mécanisme du firmware."""
        reponse = _client(agent).post(self.URL, {
            "pubkey_hex": self.CLE, "institution": str(institution.id),
            "moyen_admin": "ACL", "mot_de_passe": "pourquoi",
            "compagnon_meshcore": str(compagnon_meshcore.id),
        }, format="json")
        assert reponse.status_code == 400
        assert "acl" in str(reponse.data).lower()

    def test_la_voie_mot_de_passe_exige_un_mot_de_passe(self, agent, institution,
                                                        compagnon_meshcore):
        reponse = _client(agent).post(self.URL, {
            "pubkey_hex": self.CLE, "institution": str(institution.id),
            "moyen_admin": "MOT_DE_PASSE", "compagnon_meshcore": str(compagnon_meshcore.id),
        }, format="json")
        assert reponse.status_code == 400

    def test_un_moyen_sans_companion_est_refuse(self, agent, institution):
        """Sans companion, la vérification n'a pas d'émetteur : c'est lui qui ouvre la session,
        et c'est sa clé que l'ACL doit contenir."""
        reponse = _client(agent).post(self.URL, {
            "pubkey_hex": self.CLE, "institution": str(institution.id),
            "moyen_admin": "MOT_DE_PASSE", "mot_de_passe": "x",
        }, format="json")
        assert reponse.status_code == 400
        assert "companion" in str(reponse.data).lower()

    def test_le_companion_d_une_autre_institution_est_refuse(self, create_user, institution,
                                                             autre_institution, agent):
        """Sinon on emprunterait la passerelle d'autrui pour ouvrir une session en son nom."""
        from core.models import CompagnonMeshCore, MeshCoreConnexionType

        etranger = CompagnonMeshCore.objects.create(
            nom="Companion voisin", institution=autre_institution,
            connexion_type=MeshCoreConnexionType.TCP, tcp_host="172.16.9.9",
        )
        reponse = _client(agent).post(self.URL, {
            "pubkey_hex": self.CLE, "institution": str(institution.id),
            "moyen_admin": "ACL", "compagnon_meshcore": str(etranger.id),
        }, format="json")
        assert reponse.status_code == 403

    def test_une_cle_tronquee_est_refusee(self, agent, institution, compagnon_meshcore):
        """Piège courant : les applications MeshCore affichent un préfixe de 6 ou 12
        caractères, qui ne désigne pas un nœud de façon unique."""
        reponse = _client(agent).post(self.URL, {
            "pubkey_hex": "ab12cd", "institution": str(institution.id),
            "moyen_admin": "ACL", "compagnon_meshcore": str(compagnon_meshcore.id),
        }, format="json")
        assert reponse.status_code == 400
        assert "64" in str(reponse.data)

    def test_deux_identites_a_la_fois_sont_refusees(self, agent, institution):
        reponse = _client(agent).post(self.URL, {
            "node_num": 0x7010, "pubkey_hex": self.CLE,
            "institution": str(institution.id),
        }, format="json")
        assert reponse.status_code == 400
        assert "une identité et une seule" in str(reponse.data).lower()

    def test_aucune_identite_est_refusee(self, agent, institution):
        reponse = _client(agent).post(self.URL, {"institution": str(institution.id)},
                                      format="json")
        assert reponse.status_code == 400

    def test_un_noeud_meshtastic_ne_s_administre_pas_par_mot_de_passe(self, agent, institution,
                                                                      compagnon_meshcore):
        """Accepter un mot de passe sur un nœud Meshtastic ferait croire à une autorisation qui
        n'existe pas : là, c'est `security.admin_key` qui fait foi."""
        reponse = _client(agent).post(self.URL, {
            "node_num": 0x7011, "institution": str(institution.id),
            "moyen_admin": "MOT_DE_PASSE", "mot_de_passe": "x",
            "compagnon_meshcore": str(compagnon_meshcore.id),
        }, format="json")
        assert reponse.status_code == 400
        assert "admin_key" in str(reponse.data)

    def test_la_preuve_faite_ouvre_l_ecriture(self, agent, institution, compagnon_meshcore):
        from core.acces_radio import peut_administrer_noeud_meshcore
        from core.models import MoyenAdminRadio, RattachementNoeudRadio, StatutPreuveRadio

        rattachement = RattachementNoeudRadio.objects.create(
            pubkey_hex=self.CLE, institution=institution,
            moyen_admin=MoyenAdminRadio.MOT_DE_PASSE, mot_de_passe="secret",
            compagnon_meshcore=compagnon_meshcore,
        )
        assert peut_administrer_noeud_meshcore(agent, self.CLE) is False

        rattachement.statut_preuve = StatutPreuveRadio.VERIFIEE
        rattachement.save(update_fields=["statut_preuve"])
        assert peut_administrer_noeud_meshcore(agent, self.CLE) is True

    def test_un_administrateur_passe_sans_preuve(self, create_user, institution):
        """Le recours : une institution qui a perdu la main sur son propre matériel."""
        from core.acces_radio import peut_administrer_noeud_meshcore

        admin = _utilisateur(create_user, "admin-meshcore@x.fr", "ADMIN")
        assert peut_administrer_noeud_meshcore(admin, self.CLE) is True

    def test_le_mot_de_passe_n_est_pas_stocke_en_clair(self, agent, institution,
                                                       compagnon_meshcore):
        """« On ne stocke rien en clair. » Vérifié en SQL brut, pas par l'ORM, qui déchiffre."""
        from django.db import connection
        from core.models import RattachementNoeudRadio

        _client(agent).post(self.URL, {
            "pubkey_hex": self.CLE, "institution": str(institution.id),
            "moyen_admin": "MOT_DE_PASSE", "mot_de_passe": "mot-de-passe-tres-reconnaissable",
            "compagnon_meshcore": str(compagnon_meshcore.id),
        }, format="json")
        rattachement = RattachementNoeudRadio.objects.get(pubkey_hex=self.CLE)
        assert rattachement.mot_de_passe == "mot-de-passe-tres-reconnaissable"

        with connection.cursor() as curseur:
            curseur.execute(
                "SELECT mot_de_passe FROM core_rattachementnoeudradio WHERE id = %s",
                [str(rattachement.id)],
            )
            brut = curseur.fetchone()[0]
        assert "mot-de-passe-tres-reconnaissable" not in (brut or "")
