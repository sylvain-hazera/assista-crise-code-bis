"""Registre des modèles de messages, placeholders, et l'invariant de sécurité sur les liens.

**L'invariant qui porte tout le reste** : un placeholder de lien n'est jamais résolu ailleurs
qu'à l'instant de l'envoi. Onze points d'envoi utilisent `build_magic_link`, et un lien magique
est un porteur d'identité — qui l'a peut agir comme la personne.

Le cas qui le prouve : `UserViewSet.send_password_reset`, où un administrateur déclenche une
réinitialisation POUR QUELQU'UN D'AUTRE. Si la fenêtre de relecture affichait ce lien,
l'administrateur pourrait prendre la main sur le compte du bénévole. D'où le défaut sûr :
`rendre()` masque les liens SAUF si on lui passe explicitement `pour_envoi=True`.
"""
import pytest

from core.modeles_messages import (
    CATALOGUE, CanalMessage, est_secret, modele, modeles_personnalisables,
    placeholders_du_texte, rendre, segments_sms,
)


class TestInvariantDeSecuriteSurLesLiens:

    def test_un_lien_n_est_PAS_resolu_par_defaut(self):
        """Le défaut est le mode sûr, délibérément : un appelant qui oublie l'argument ne fait
        pas fuiter un lien."""
        rendu = rendre("Activez : [LIEN_ACTIVATION]",
                       {"LIEN_ACTIVATION": "https://exemple.fr/magique/secret"})
        assert rendu == "Activez : [LIEN_ACTIVATION]"
        assert "secret" not in rendu

    def test_un_lien_est_resolu_seulement_pour_l_envoi(self):
        rendu = rendre("Activez : [LIEN_ACTIVATION]",
                       {"LIEN_ACTIVATION": "https://exemple.fr/magique/secret"},
                       pour_envoi=True)
        assert rendu == "Activez : https://exemple.fr/magique/secret"

    @pytest.mark.parametrize("nom", [
        "LIEN", "LIEN_ACTIVATION", "LIEN_CONNEXION", "LIEN_REINITIALISATION", "LIEN_SUIVI",
        "LIEN_EQUIPE", "LIEN_ACCUSE_RECEPTION",
    ])
    def test_tous_les_placeholders_de_lien_sont_reconnus_comme_secrets(self, nom):
        """Reconnus par leur PRÉFIXE et non par une liste nommée : ajouter un nouveau lien ne
        doit pas demander de penser à l'inscrire quelque part pour qu'il soit protégé —
        l'oubli irait dans le mauvais sens."""
        assert est_secret(nom) is True

    def test_un_placeholder_ordinaire_n_est_pas_secret(self):
        for nom in ("PRENOM", "NOM", "INSTITUTION", "MOTIF", "SIGNATURE"):
            assert est_secret(nom) is False

    def test_aucun_corps_relisible_ne_laisse_fuiter_un_lien(self):
        """Garde structurel sur TOUT le catalogue : pour chaque modèle relisible, le rendu
        d'aperçu ne doit contenir aucune des valeurs de lien fournies. C'est ce test qui
        protège l'ajout d'un futur modèle par quelqu'un qui n'aurait pas lu la règle."""
        valeurs = {nom: f"https://exemple.fr/SECRET-{nom}"
                   for m in CATALOGUE.values() for nom in m.placeholders if est_secret(nom)}
        valeurs.update({nom: f"valeur-{nom}"
                        for m in CATALOGUE.values() for nom in m.placeholders
                        if not est_secret(nom)})

        for cle, m in CATALOGUE.items():
            if not m.relisible:
                continue
            apercu = rendre(m.sujet, valeurs) + "\n" + rendre(m.corps, valeurs)
            assert "SECRET-" not in apercu, (
                f"le modèle relisible « {cle} » laisse apparaître un lien dans son aperçu"
            )


class TestPlaceholders:

    def test_un_placeholder_sans_valeur_reste_visible(self):
        """Laissé tel quel et non remplacé par du vide : un mail qui dit « Bonjour [PRENOM] »
        se remarque et se corrige, un mail qui dit « Bonjour  » passe inaperçu."""
        assert rendre("Bonjour [PRENOM],", {}) == "Bonjour [PRENOM],"

    def test_les_placeholders_employes_sont_listes_dans_l_ordre(self):
        assert placeholders_du_texte("[NOM] puis [PRENOM] puis [NOM]") == ["NOM", "PRENOM"]

    def test_un_mot_en_minuscules_entre_crochets_n_est_pas_un_placeholder(self):
        """Sinon une adresse ou une note entre crochets dans un texte réécrit par une
        institution serait traitée comme un champ à remplir."""
        assert placeholders_du_texte("[voir ci-dessous]") == []
        assert rendre("[voir ci-dessous]", {}) == "[voir ci-dessous]"


class TestCrochetsLitteraux:

    def test_les_crochets_doubles_rendent_des_crochets_simples(self):
        """Besoin réel : le sujet de l'alerte PCS commence par `[PCS]`, préfixe sur lequel des
        filtres de boîte mail peuvent porter."""
        assert rendre("[[PCS]] Alerte", {}) == "[PCS] Alerte"

    def test_le_sujet_de_l_alerte_pcs_garde_son_prefixe(self):
        rendu = rendre(CATALOGUE["ALERTE_PCS"].sujet, {"CRISE": "Inondation"})
        assert rendu.startswith("[PCS] ")
        assert "Inondation" in rendu

    def test_l_echappement_prime_sur_la_resolution_d_un_lien(self):
        """`[[LIEN_ACTIVATION]]` est du TEXTE : il ne doit pas être résolu, même à l'envoi.
        L'ordre de traitement compte — traiter les deux ensemble laisserait un texte échappé
        passer pour un placeholder secret."""
        assert rendre("[[LIEN_ACTIVATION]]", {"LIEN_ACTIVATION": "https://secret"},
                      pour_envoi=True) == "[LIEN_ACTIVATION]"


class TestCatalogue:

    def test_tout_placeholder_employe_est_declare(self):
        """Un modèle qui emploie un placeholder non déclaré partirait avec « [PRENOM] » en clair
        dans le mail : l'appelant ne saurait pas qu'il doit fournir cette valeur."""
        for cle, m in CATALOGUE.items():
            employes = set(placeholders_du_texte(m.sujet) + placeholders_du_texte(m.corps))
            non_declares = employes - set(m.placeholders)
            assert not non_declares, f"{cle} emploie {non_declares} sans les déclarer"

    def test_tout_placeholder_declare_est_employe(self):
        """L'inverse compte aussi : un placeholder déclaré et inutilisé fait croire à l'écran de
        personnalisation qu'une valeur est attendue alors qu'elle ne sert à rien."""
        for cle, m in CATALOGUE.items():
            employes = set(placeholders_du_texte(m.sujet) + placeholders_du_texte(m.corps))
            inutiles = set(m.placeholders) - employes
            assert not inutiles, f"{cle} déclare {inutiles} sans les employer"

    def test_les_messages_internes_ne_sont_pas_personnalisables(self):
        """Ils vont aux administrateurs de la plateforme, pas au public d'une institution. Les
        laisser réécrire permettrait de casser le texte d'une alerte de panne."""
        interne = CATALOGUE["INTERNE_ALERTE_ADMINISTRATEURS"]
        assert interne.personnalisable is False
        assert interne not in modeles_personnalisables()

    def test_un_accuse_que_l_on_s_envoie_a_soi_meme_n_est_pas_relisible(self):
        """Y ouvrir un éditeur montrerait à quelqu'un le mail qu'il est en train de recevoir,
        avec son propre lien de connexion dedans."""
        for cle in ("COMPTE_ACTIVATION_INSTITUTIONNEL", "MOT_DE_PASSE_OUBLIE",
                    "DEMANDE_ACCUSE_DEPOT", "OFFRE_ACCUSE_DEPOT"):
            assert CATALOGUE[cle].relisible is False, cle

    def test_un_message_qui_part_vers_un_tiers_est_relisible(self):
        for cle in ("COMPTE_VALIDE", "COMPTE_REFUSE", "MOT_DE_PASSE_ENVOYE_PAR_UN_TIERS",
                    "DOSSIER_CLOTURE", "RATTACHEMENT_HABITATION_REFUSE"):
            assert CATALOGUE[cle].relisible is True, cle

    def test_chaque_modele_dit_quand_il_part(self):
        """Une institution qui réécrit un texte doit savoir quand il part et à qui, sinon elle
        réécrit à l'aveugle."""
        for cle, m in CATALOGUE.items():
            assert m.quand.strip(), f"{cle} ne dit pas quand il est envoyé"

    def test_une_cle_inconnue_rend_None_sans_lever(self):
        """L'appelant doit pouvoir retomber sur son texte en dur plutôt que de faire échouer
        l'action que le mail accompagne."""
        assert modele("CLE_QUI_N_EXISTE_PAS") is None


class TestSegmentsSms:

    @pytest.mark.parametrize("longueur,segments", [
        (0, 0), (1, 1), (160, 1),
        # 161 caractères coûtent DEUX segments : c'est ce que personne ne devine, et c'est
        # pourquoi le compteur est affiché à la saisie.
        (161, 2), (306, 2), (307, 3),
    ])
    def test_le_compte_de_segments_suit_la_facturation(self, longueur, segments):
        assert segments_sms("x" * longueur)["segments"] == segments

    def test_le_nombre_de_caracteres_restants_est_donne(self):
        assert segments_sms("x" * 150)["restants"] == 10

    def test_le_modele_sms_tient_dans_un_segment_sans_son_message(self):
        """Le gabarit lui-même doit laisser de la place au texte : s'il consomme déjà
        160 caractères, toute alerte coûtera deux segments."""
        gabarit = CATALOGUE["SMS_ALERTE_PCS"]
        assert gabarit.canal == CanalMessage.SMS
        sans_message = rendre(gabarit.corps, {"INSTITUTION": "Reserve Resilience",
                                              "MESSAGE": ""})
        assert len(sans_message) < 120, "le gabarit SMS ne laisse pas assez de place au message"
