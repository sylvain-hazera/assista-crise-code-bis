"""Tests de admin_meshtastic.py, avec un faux appareil.

Ils s'exécutent dans l'image du pont (la lib `meshtastic` y est, pas dans l'image Django) :

    docker run --rm -v "$PWD/meshtastic-bridge":/src -w /src \\
      --entrypoint python assista-crise-meshtastic-bridge:prod -m unittest -v test_admin_meshtastic

`unittest` plutôt que pytest : il est dans la bibliothèque standard, l'image du pont n'embarque
pas de dépendance de test et n'a pas à en embarquer pour trois fichiers.

Ce qui est verrouillé ici vient du firmware (`AdminModule::handleReceivedProtobuf`, lu le
06/11/2026) : la voie « canal nommé admin » est volontairement jamais utilisée, les lectures
n'ont pas besoin de clé de session, les écritures oui, et une clé de session expire.
"""
import unittest

from meshtastic.protobuf import admin_pb2, config_pb2, mesh_pb2, portnums_pb2

import admin_meshtastic as mod


class FauxInterface:
    """Imite le strict nécessaire de MeshInterface : le rappel est appelé pendant sendData, donc
    l'attente de admin_meshtastic est déjà satisfaite quand elle commence."""

    def __init__(self, mon_num=0x1000, reponses=None, cle_session_apres_lecture=b"12345678"):
        self.myInfo = type("Info", (), {"my_node_num": mon_num})()
        self.envois = []
        self._noeuds = {}
        # Liste de réponses à servir dans l'ordre : un protobuf AdminMessage, un motif d'erreur
        # de routage (str), ou None pour « aucune réponse ».
        self.reponses = list(reponses or [])
        self.cle_session_apres_lecture = cle_session_apres_lecture

    def _getOrCreateByNum(self, num):
        return self._noeuds.setdefault(num, {})

    def sendData(self, data, destinationId=None, portNum=None, wantAck=False, wantResponse=False,
                 onResponse=None, onResponseAckPermitted=False, channelIndex=0,
                 pkiEncrypted=False, **_):
        self.envois.append({
            "message": data, "destination": destinationId, "portnum": portNum,
            "attend_reponse": wantResponse, "canal": channelIndex, "pki": pkiEncrypted,
            "ack_permis": onResponseAckPermitted,
            "cle_session": bytes(data.session_passkey) if data.session_passkey else None,
        })
        reponse = self.reponses.pop(0) if self.reponses else "__ACK__"
        if reponse is None:                         # silence : on n'appelle pas le rappel
            return
        if isinstance(reponse, str) and reponse != "__ACK__":
            onResponse({"decoded": {"routing": {"errorReason": reponse}}})
            return
        if reponse == "__ACK__":                    # accusé de réception simple
            onResponse({"decoded": {"routing": {"errorReason": "NONE"}}})
            return
        # Réponse d'administration : la vraie lib y récolte la clé de session au passage.
        if self.cle_session_apres_lecture:
            self._getOrCreateByNum(destinationId)["adminSessionPassKey"] = self.cle_session_apres_lecture
        onResponse({"decoded": {"admin": {"raw": reponse}, "portnum": "ADMIN_APP"}})


def reponse_lora(tx_power=22, region=3, hop_limit=3, preset=0):
    return admin_pb2.AdminMessage(get_config_response=config_pb2.Config(
        lora=config_pb2.Config.LoRaConfig(
            region=region, tx_power=tx_power, hop_limit=hop_limit, modem_preset=preset,
            use_preset=True, tx_enabled=True,
        ),
    ))


def reponse_metadata():
    return admin_pb2.AdminMessage(get_device_metadata_response=mesh_pb2.DeviceMetadata(
        firmware_version="2.7.4", hw_model=43, role=2,
    ))


class TestLecturesLocales(unittest.TestCase):
    """La passerelle elle-même : le firmware traite le message comme venant du téléphone
    (`mp.from == 0`), donc ni PKI, ni clé d'administration, ni clé de session."""

    def test_une_lecture_locale_part_sans_pki(self):
        iface = FauxInterface(reponses=[reponse_lora()])
        donnees, config = mod.executer(iface, {"type_tache": "LIRE_CONFIG_LORA", "node_num_cible": None})
        envoi = iface.envois[0]
        self.assertFalse(envoi["pki"])
        self.assertEqual(envoi["destination"], 0x1000)
        self.assertEqual(envoi["portnum"], portnums_pb2.PortNum.ADMIN_APP)
        self.assertTrue(envoi["attend_reponse"])
        self.assertEqual(donnees["puissance_emission_dbm"], 22)
        self.assertEqual(config["region"], "EU_868")

    def test_une_cible_egale_a_la_passerelle_est_traitee_comme_locale(self):
        iface = FauxInterface(mon_num=0x1000, reponses=[reponse_metadata()])
        mod.executer(iface, {"type_tache": "LIRE_METADATA", "node_num_cible": 0x1000})
        self.assertFalse(iface.envois[0]["pki"])

    def test_la_lecture_des_metadonnees_est_decodee(self):
        iface = FauxInterface(reponses=[reponse_metadata()])
        donnees, config = mod.executer(iface, {"type_tache": "LIRE_METADATA"})
        self.assertEqual(donnees["firmware_version"], "2.7.4")
        self.assertEqual(donnees["hardware_model"], "HELTEC_V3")
        self.assertEqual(config["role"], donnees["role"])


class TestLecturesDistantes(unittest.TestCase):

    def test_une_lecture_distante_est_chiffree_par_cle_publique_sur_le_canal_zero(self):
        """Le canal 0 n'est pas un détail : le firmware ne tente le déchiffrement par clé
        publique que là, et la voie « canal nommé admin » qu'utilise la lib officielle donnerait
        l'administration à quiconque possède la PSK de ce canal."""
        iface = FauxInterface(reponses=[reponse_lora()])
        mod.executer(iface, {"type_tache": "LIRE_CONFIG_LORA", "node_num_cible": 0x2000})
        envoi = iface.envois[0]
        self.assertTrue(envoi["pki"])
        self.assertEqual(envoi["canal"], 0)
        self.assertEqual(envoi["destination"], 0x2000)
        # Une lecture n'a pas besoin de clé de session : on n'en invente pas une.
        self.assertIsNone(envoi["cle_session"])

    def test_une_cle_publique_non_autorisee_dit_quoi_faire(self):
        iface = FauxInterface(reponses=["ADMIN_PUBLIC_KEY_UNAUTHORIZED"])
        with self.assertRaises(mod.ErreurAdmin) as cas:
            mod.executer(iface, {"type_tache": "LIRE_CONFIG_LORA", "node_num_cible": 0x2000})
        self.assertIn("security.admin_key", str(cas.exception))

    def test_un_silence_est_une_erreur_explicite(self):
        iface = FauxInterface(reponses=[None])
        mod.TIMEOUT_REPONSE_S, ancien = 0.2, mod.TIMEOUT_REPONSE_S
        try:
            with self.assertRaises(mod.ErreurAdmin) as cas:
                mod.executer(iface, {"type_tache": "LIRE_METADATA", "node_num_cible": 0x2000})
        finally:
            mod.TIMEOUT_REPONSE_S = ancien
        self.assertIn("Aucune réponse", str(cas.exception))

    def test_une_reponse_sans_message_d_administration_est_refusee(self):
        iface = FauxInterface(reponses=["__ACK__"])
        with self.assertRaises(mod.ErreurAdmin):
            mod.executer(iface, {"type_tache": "LIRE_METADATA", "node_num_cible": 0x2000})


class TestEcritures(unittest.TestCase):

    def test_un_redemarrage_distant_obtient_d_abord_une_cle_de_session(self):
        """Le firmware exige une clé de session pour toute écriture ; elle n'est fournie que
        dans la réponse d'une lecture."""
        iface = FauxInterface(reponses=[reponse_metadata(), "__ACK__"])
        donnees, _ = mod.executer(iface, {
            "type_tache": "REDEMARRER", "node_num_cible": 0x2000, "parametres": {"delai_s": 5},
        })
        self.assertEqual(len(iface.envois), 2)
        self.assertIsNone(iface.envois[0]["cle_session"])        # la lecture qui récolte la clé
        self.assertEqual(iface.envois[1]["cle_session"], b"12345678")
        self.assertEqual(iface.envois[1]["message"].reboot_seconds, 5)
        # Pas de réponse applicative attendue : l'accusé suffit, et il faut l'autoriser.
        self.assertFalse(iface.envois[1]["attend_reponse"])
        self.assertTrue(iface.envois[1]["ack_permis"])
        self.assertEqual(donnees["redemarrage_dans_s"], 5)

    def test_une_ecriture_locale_n_a_besoin_d_aucune_cle(self):
        iface = FauxInterface(reponses=["__ACK__"])
        mod.executer(iface, {"type_tache": "REDEMARRER", "node_num_cible": None})
        self.assertEqual(len(iface.envois), 1)
        self.assertIsNone(iface.envois[0]["cle_session"])

    def test_une_cle_perimee_est_reprise_et_l_ecriture_reessayee_une_fois(self):
        """Le firmware renouvelle la clé dès qu'une réponse est construite plus de 150 s après
        la précédente : un refus de session n'est pas une erreur définitive."""
        iface = FauxInterface(reponses=[
            reponse_lora(), "ADMIN_BAD_SESSION_KEY",      # première tentative : clé périmée
            reponse_lora(), "__ACK__",                    # seconde : nouvelle clé, ça passe
        ])
        mod.executer(iface, {
            "type_tache": "DEFINIR_PUISSANCE", "node_num_cible": 0x2000,
            "parametres": {"puissance_dbm": 20},
        })
        # Quatre envois : lecture, écriture refusée, nouvelle lecture, écriture acceptée. La
        # configuration est RELUE avant la seconde écriture -- réécrire une configuration
        # périmée serait pire que l'échec.
        self.assertEqual(len(iface.envois), 4)
        self.assertEqual(iface.envois[3]["message"].set_config.lora.tx_power, 20)

    def test_un_refus_de_session_persistant_finit_par_echouer(self):
        iface = FauxInterface(reponses=[
            reponse_metadata(), "ADMIN_BAD_SESSION_KEY",
            reponse_metadata(), "ADMIN_BAD_SESSION_KEY",
        ])
        with self.assertRaises(mod.ErreurAdmin):
            mod.executer(iface, {"type_tache": "REDEMARRER", "node_num_cible": 0x2000})

    def test_la_puissance_est_ecrite_avec_tout_le_bloc_lora(self):
        """`set_config.lora` REMPLACE tout le bloc côté firmware : n'envoyer que tx_power
        effacerait la région, et un nœud sans région ne transmet plus du tout."""
        iface = FauxInterface(reponses=[reponse_lora(tx_power=14, region=3, hop_limit=4), "__ACK__"])
        donnees, config = mod.executer(iface, {
            "type_tache": "DEFINIR_PUISSANCE", "node_num_cible": 0x2000,
            "parametres": {"puissance_dbm": 27},
        })
        ecrit = iface.envois[1]["message"].set_config.lora
        self.assertEqual(ecrit.tx_power, 27)
        self.assertEqual(ecrit.region, 3)          # conservée
        self.assertEqual(ecrit.hop_limit, 4)       # conservée
        self.assertTrue(ecrit.use_preset)
        self.assertEqual(config["puissance_emission_dbm"], 27)
        self.assertTrue(donnees["redemarrage_declenche"])

    def test_une_puissance_hors_bornes_n_est_meme_pas_envoyee(self):
        for puissance in (0, 28, -1, 100):
            iface = FauxInterface(reponses=[reponse_lora()])
            with self.assertRaises(mod.ErreurAdmin):
                mod.executer(iface, {
                    "type_tache": "DEFINIR_PUISSANCE", "node_num_cible": 0x2000,
                    "parametres": {"puissance_dbm": puissance},
                })
            self.assertEqual(iface.envois, [])

    def test_une_puissance_absente_est_refusee(self):
        iface = FauxInterface()
        with self.assertRaises(mod.ErreurAdmin):
            mod.executer(iface, {"type_tache": "DEFINIR_PUISSANCE", "node_num_cible": 0x2000,
                                 "parametres": {}})

    def test_une_configuration_lora_vide_n_est_pas_reecrite(self):
        """Réécrire à l'aveugle une configuration qu'on n'a pas vraiment lue mettrait le nœud
        hors d'usage."""
        vide = admin_pb2.AdminMessage(get_config_response=config_pb2.Config(
            lora=config_pb2.Config.LoRaConfig(),
        ))
        iface = FauxInterface(reponses=[vide])
        with self.assertRaises(mod.ErreurAdmin):
            mod.executer(iface, {
                "type_tache": "DEFINIR_PUISSANCE", "node_num_cible": 0x2000,
                "parametres": {"puissance_dbm": 20},
            })


class TestDivers(unittest.TestCase):

    def test_une_operation_inconnue_est_refusee(self):
        with self.assertRaises(mod.ErreurAdmin):
            mod.executer(FauxInterface(), {"type_tache": "FORMATER_TOUT"})

    def test_le_nom_du_noeud_n_alimente_aucune_table_en_clair(self):
        """Un nom est une donnée nominative : il reste dans la réponse chiffrée côté Django."""
        iface = FauxInterface(reponses=[admin_pb2.AdminMessage(
            get_owner_response=mesh_pb2.User(long_name="Jean Dupont", short_name="JD"),
        )])
        donnees, config = mod.executer(iface, {"type_tache": "LIRE_PROPRIETAIRE"})
        self.assertEqual(donnees["long_name"], "Jean Dupont")
        self.assertIsNone(config)

    def test_une_valeur_d_enumeration_inconnue_ne_fait_pas_tomber_la_lecture(self):
        """Un firmware plus récent que nos protos ne doit pas casser un relevé."""
        iface = FauxInterface(reponses=[reponse_lora(region=250)])
        donnees, _ = mod.executer(iface, {"type_tache": "LIRE_CONFIG_LORA"})
        self.assertEqual(donnees["region"], "250")

    def test_sans_numero_de_noeud_connu_l_operation_est_refusee(self):
        iface = FauxInterface()
        iface.myInfo = None
        with self.assertRaises(mod.ErreurAdmin):
            mod.executer(iface, {"type_tache": "LIRE_METADATA", "node_num_cible": None})


if __name__ == "__main__":
    unittest.main()
