"""Tests de bridge.py — l'ingestion MQTT, et rien d'autre.

    docker run --rm -v "$PWD/meshtastic-bridge":/src -w /src \
      --entrypoint python assista-crise-meshtastic-bridge:prod -m unittest -v test_bridge

`bridge.py` n'avait AUCUN test jusqu'au 10/11/2026, et ça s'est payé : `_observer_liaison_rf`
appelait `HasField("hop_start")` sur un scalaire proto3 sans présence, ce qui lève `ValueError`.
Comme la fonction est appelée en tête de `on_message`, **tout paquet relayé était abandonné en
entier** — ni message, ni position, ni contact, ni liaison. 1 201 fois en production, sans que
rien ne le dise à l'écran : le pont paraissait fonctionner parce que les paquets dont la
passerelle est l'émetteur lui-même sortent à la garde précédente.

Leçon encodée ici : ces tests construisent de **vrais** messages protobuf, jamais des faux
objets avec un `HasField` complaisant. Un faux aurait laissé passer exactement ce défaut.

Importer `bridge` exige les variables d'environnement de l'API (lues au chargement du module).
"""
import os
import unittest

os.environ.setdefault("DJANGO_API_URL", "http://exemple.invalide/api")
os.environ.setdefault("DJANGO_BRIDGE_EMAIL", "pont@exemple.invalide")
os.environ.setdefault("DJANGO_BRIDGE_PASSWORD", "x")

from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2  # noqa: E402

import bridge  # noqa: E402


EMETTEUR = 0x1111
PASSERELLE = 0x22222222


class TamponEspion:
    def __init__(self):
        self.observations = []

    def observer(self, emetteur, recepteur, source, snr=None, rssi=None):
        self.observations.append((emetteur, recepteur, source, snr))


def _paquet(hop_start=None, hop_limit=None, snr=5.0):
    """Vrai MeshPacket. `hop_start=None` laisse le champ à son défaut (0), ce qui est ce qu'un
    firmware ancien produit — et le cas qui faisait lever `HasField`."""
    paquet = mesh_pb2.MeshPacket()
    if hop_start is not None:
        paquet.hop_start = hop_start
    if hop_limit is not None:
        paquet.hop_limit = hop_limit
    paquet.rx_snr = snr
    setattr(paquet, "from", EMETTEUR)
    return paquet


def _enveloppe(gateway_id=f"!{PASSERELLE:08x}"):
    enveloppe = mqtt_pb2.ServiceEnvelope()
    enveloppe.gateway_id = gateway_id
    return enveloppe


class TestObservationDesLiaisons(unittest.TestCase):

    def test_une_reception_directe_est_enregistree(self):
        """hop_start == hop_limit : le paquet n'a pas été relayé, donc `rx_snr` mesure bien la
        liaison entre cet émetteur et cette passerelle."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(3, 3), EMETTEUR)
        self.assertEqual(tampon.observations, [(EMETTEUR, PASSERELLE, "RF", 5.0)])

    def test_un_paquet_relaye_n_est_pas_enregistre(self):
        """`rx_snr` est mesuré sur le DERNIER saut : l'enregistrer fabriquerait une liaison
        directe qui n'existe pas, et enverrait quelqu'un sur un point haut pour rien."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(3, 2), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_un_firmware_sans_hop_start_ne_leve_pas(self):
        """**Le test de non-régression du défaut du 10/11/2026.** `hop_start` absent vaut 0 et
        signifie « ce firmware ne renseigne pas ce champ » : on s'abstient de conclure, sans
        lever -- une exception ici faisait abandonner le paquet entier dans `on_message`."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(hop_limit=3), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_un_hop_start_a_zero_explicite_ne_leve_pas_non_plus(self):
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(0, 0), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_une_passerelle_qui_est_l_emetteur_n_est_pas_une_liaison(self):
        """Un nœud qui publie son propre paquet ne prouve aucune liaison radio."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(
            tampon, _enveloppe(f"!{EMETTEUR:08x}"), _paquet(3, 3), EMETTEUR,
        )
        self.assertEqual(tampon.observations, [])

    def test_une_passerelle_illisible_est_ignoree(self):
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe("pas-un-node-id"), _paquet(3, 3), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_un_snr_absent_est_rapporte_comme_inconnu_et_non_comme_zero(self):
        """0 dB est une liaison confortable, « inconnu » n'est pas une valeur : les confondre
        ferait passer un nœud muet pour un nœud correct."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(3, 3, snr=0.0), EMETTEUR)
        self.assertEqual(tampon.observations, [(EMETTEUR, PASSERELLE, "RF", None)])


class FauxDjango:
    def __init__(self):
        self.canal_entrant = []
        self.dm_entrant = []

    def logger_canal_entrant(self, canal_id, node_num, contenu):
        self.canal_entrant.append((canal_id, node_num, contenu))
        return "coroutine-canal"

    def logger_dm_entrant(self, compagnon_id, canal_id, node_num, contenu):
        self.dm_entrant.append((compagnon_id, canal_id, node_num, contenu))
        return "coroutine-dm"


def _texte(contenu="bonjour"):
    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    data.payload = contenu.encode()
    return data.SerializeToString()


class TestMessagesDeCanal(unittest.TestCase):

    COMPAGNON = {"id": "c1", "node_num": 0x9999}

    def _traiter(self, canal_id, to_node=bridge.BROADCAST_NUM):
        django = FauxDjango()
        coro = bridge._traiter_paquet_dechiffre(
            _texte(), EMETTEUR, to_node, canal_id, "Public",
            TamponEspion(), TamponEspion(), django, self.COMPAGNON, boucle=None,
        )
        return django, coro

    def test_un_message_de_canal_connu_est_journalise(self):
        django, coro = self._traiter("canal-1")
        self.assertEqual(coro, "coroutine-canal")
        self.assertEqual(django.canal_entrant, [("canal-1", EMETTEUR, "bonjour")])

    def test_un_message_en_clair_sur_un_canal_inconnu_n_est_pas_journalise(self):
        """Il est lisible, mais il n'appartient à aucun canal de chez nous : le journaliser
        revenait à POSTer `canal: null`, que l'API refuse — 14 erreurs 400 avec trace en
        production. La branche chiffrée avait déjà cette garde, la branche en clair non."""
        django, coro = self._traiter(None)
        self.assertIsNone(coro)
        self.assertEqual(django.canal_entrant, [])

    def test_un_DM_sans_canal_reste_journalise(self):
        """Un DM ne dépend pas d'un canal connu : `canal` est nullable sur MessageMeshtasticLog,
        contrairement à MessageCanalMeshtastic. La garde ne doit donc pas le bloquer."""
        django, coro = self._traiter(None, to_node=self.COMPAGNON["node_num"])
        self.assertEqual(coro, "coroutine-dm")
        self.assertEqual(django.dm_entrant, [("c1", None, EMETTEUR, "bonjour")])


class TestEchecAbonnement(unittest.TestCase):
    """Un abonnement REFUSÉ par le broker était totalement silencieux : on journalisait
    « Connecté », on rapportait CONNECTE, et plus rien n'arrivait jamais — indiscernable d'un
    réseau calme. Or c'est le cas NORMAL sur un broker communautaire, dont l'ACL ne laisse lire
    qu'un préfixe. Constaté le 10/11/2026 sur le broker de La Réunion, qui répond `SUBACK 128`
    à un abonnement sur `#`."""

    def _code(self, identifiant):
        from paho.mqtt.packettypes import PacketTypes
        from paho.mqtt.reasoncodes import ReasonCode

        return ReasonCode(PacketTypes.SUBACK, identifier=identifiant)

    def test_un_abonnement_accorde_ne_signale_rien(self):
        # 0, 1, 2 sont les QoS accordés, pas des erreurs.
        for identifiant in (0, 1, 2):
            self.assertIsNone(bridge.echec_abonnement([self._code(identifiant)]))

    def test_un_refus_est_signale_avec_sa_raison(self):
        # 128 est ce que renvoie un broker MQTT 3.1.1 qui refuse ; 135 est le « not authorized »
        # explicite de MQTT 5.
        self.assertEqual(bridge.echec_abonnement([self._code(128)]), "Unspecified error")
        self.assertEqual(bridge.echec_abonnement([self._code(135)]), "Not authorized")

    def test_un_refus_parmi_plusieurs_topics_suffit(self):
        raison = bridge.echec_abonnement([self._code(0), self._code(135)])
        self.assertEqual(raison, "Not authorized")

    def test_une_liste_vide_ou_absente_ne_signale_rien(self):
        """Ne jamais fabriquer une erreur faute d'information : un faux « refusé » enverrait
        chercher un problème d'ACL qui n'existe pas."""
        self.assertIsNone(bridge.echec_abonnement([]))
        self.assertIsNone(bridge.echec_abonnement(None))


class TestCompteursReception(unittest.TestCase):
    """Le dernier angle mort de la famille des silences : avec un abonnement accepté sur le bon
    topic, l'absence de contacts et de liaisons ne prouvait toujours pas qu'aucun paquet
    n'arrivait. Un contact exige de savoir déchiffrer, une liaison exige un relais
    intermédiaire — un réseau fermé à nos clés et un réseau vide produisaient les mêmes
    journaux."""

    def test_l_extraction_rend_les_compteurs_et_les_remet_a_zero(self):
        """Remis à zéro à la lecture : chaque ligne de bilan porte SA fenêtre, pas un cumul
        depuis le démarrage, sinon on ne verrait jamais l'effet d'un changement."""
        compteurs = bridge.CompteursReception()
        compteurs.recus = 12
        compteurs.canal_inconnu = 5
        compteurs.illisibles = 2
        compteurs.erreurs = 1

        self.assertEqual(compteurs.extraire(), (12, 5, 2, 1))
        self.assertEqual(compteurs.extraire(), (0, 0, 0, 0))

    def test_un_compteur_neuf_est_a_zero(self):
        self.assertEqual(bridge.CompteursReception().extraire(), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()


class FauxCanalLocal:
    def __init__(self, index, nom):
        self.index = index
        self.settings = type("S", (), {"name": nom})()


class FauxNoeudLocal:
    def __init__(self, canaux):
        self._canaux = canaux

    def getChannelByName(self, nom):
        return next((c for c in self._canaux if c.settings.name == nom), None)

    def getChannelByChannelIndex(self, index):
        return next((c for c in self._canaux if c.index == index), None)


class FauxAppareil:
    """Un appareil Meshtastic local, sans radio : ce que la lib officielle expose au pont."""
    myInfo = type("I", (), {"my_node_num": 0x1001})()

    def __init__(self):
        self.localNode = FauxNoeudLocal([FauxCanalLocal(0, ""), FauxCanalLocal(1, "Fr_EMCOM")])

    def getPublicKey(self):
        return None

    def sendText(self, *a, **k):
        pass

    def close(self):
        pass


class FauxDjangoLocal:
    """Enregistre ce que le pont remonte ; tout le reste répond « rien à faire »."""

    def __init__(self):
        self.canal_entrants = []
        self.dm_entrants = []

    async def canaux_avec_cle(self, compagnon_id):
        return [{"id": "canal-emcom", "nom": "Fr_EMCOM"}]

    async def logger_canal_entrant(self, canal_id, node_num, contenu):
        self.canal_entrants.append((canal_id, node_num, contenu))

    async def logger_dm_entrant(self, compagnon_id, canal_id, node_num, contenu):
        self.dm_entrants.append((node_num, contenu))

    def __getattr__(self, nom):
        async def rien(*a, **k):
            return []
        return rien


class CanalEntrantAppareilLocalTest(unittest.IsolatedAsyncioTestCase):
    """Régression du 15/11/2026 : un message de canal reçu par un appareil TCP, série ou
    Bluetooth partait avec `canal: None`, que le serveur refuse — perdu en silence. Le pont
    retrouve désormais le canal par son NOM local, et n'envoie rien pour un canal inconnu."""

    async def _jouer(self, paquets):
        import asyncio
        from pubsub import pub

        django = FauxDjangoLocal()
        appareil = FauxAppareil()
        compagnon = {"id": "c1", "nom": "Test", "node_num": 0x1001}
        ancien = bridge.POLL_INTERVAL_SECONDS
        bridge.POLL_INTERVAL_SECONDS = 0.01
        tache = asyncio.create_task(bridge._executer_compagnon_interface_locale(
            django, compagnon, construire_interface=lambda: appareil, libelle_connexion="test"))
        try:
            await asyncio.sleep(0.15)        # laisse la boucle des canaux remplir la table
            for paquet in paquets:
                pub.sendMessage("meshtastic.receive", packet=paquet, interface=appareil)
            await asyncio.sleep(0.15)
        finally:
            tache.cancel()
            bridge.POLL_INTERVAL_SECONDS = ancien
            try:
                await tache
            except BaseException:
                pass
            pub.unsubAll("meshtastic.receive")
        return django

    def _texte(self, vers, canal, texte):
        return {"from": 0xBEEF, "to": vers, "channel": canal,
                "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": texte}}

    async def test_un_message_de_canal_connu_est_rattache_par_son_nom(self):
        django = await self._jouer([self._texte(bridge.BROADCAST_NUM, 1, "Route coupée")])
        self.assertEqual(django.canal_entrants, [("canal-emcom", 0xBEEF, "Route coupée")])

    async def test_un_canal_inconnu_du_central_n_envoie_rien(self):
        django = await self._jouer([self._texte(bridge.BROADCAST_NUM, 0, "sur le primaire")])
        self.assertEqual(django.canal_entrants, [])

    async def test_un_message_direct_passe_toujours(self):
        django = await self._jouer([self._texte(0x1001, 0, "pour moi")])
        self.assertEqual(django.dm_entrants, [(0xBEEF, "pour moi")])


# ── Échange des clés publiques (17/11/2026) ────────────────────────────────────────────────

NOUS = 0x9999
CLE_PRIVEE_NOUS = "11" * 32
CLE_PRIVEE_AUTRE = "22" * 32
PSK = bytes.fromhex("ab" * 16)


def _compagnon(chiffrement=True):
    return {"id": "c1", "nom": "Pont", "node_num": NOUS, "chiffrement_supporte": chiffrement}


class FauxRegistre:
    def __init__(self, canaux=None):
        self._canaux = canaux if canaux is not None else {"Equipe": {"id": "k1", "psk": PSK, "principal": True}}

    def get(self, nom):
        return self._canaux.get(nom)

    def nom_principal(self):
        return next(iter(self._canaux), None)


def _echange(horloge=None, **kw):
    import crypto
    publies = []
    annuaire = bridge.AnnuaireCles(horloge or (lambda: 1000.0))
    echange = bridge.EchangeCles(
        _compagnon(**kw), FauxRegistre(), crypto.cle_publique_depuis_privee_hex(CLE_PRIVEE_NOUS),
        annuaire=annuaire, publier=lambda canal, paquet: publies.append((canal, paquet)),
    )
    return echange, publies


def _identite_d_un_autre(demande=False, par_bitfield=False, cle=b"\x07" * 32):
    user = mesh_pb2.User(id="!00001111", long_name="Autre", short_name="AUT", public_key=cle)
    data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.NODEINFO_APP, payload=user.SerializeToString())
    if demande and par_bitfield:
        data.bitfield = bridge.BITFIELD_WANT_RESPONSE
    elif demande:
        data.want_response = True
    return user, data


def _relire(paquet):
    """Ce qu'un appareil lirait de ce paquet : (Data, User)."""
    import crypto
    if paquet.HasField("decoded"):
        data = paquet.decoded
    else:
        data = mesh_pb2.Data()
        data.ParseFromString(crypto.dechiffrer(PSK, paquet.id, getattr(paquet, "from"), bytes(paquet.encrypted)))
    user = mesh_pb2.User()
    user.ParseFromString(data.payload)
    return data, user


class TestIdentiteConstruite(unittest.TestCase):

    def test_l_annonce_porte_la_cle_et_le_drapeau_du_firmware(self):
        echange, _ = _echange()
        paquet = bridge.construire_identite(_compagnon(), "Equipe", {"psk": PSK}, echange.cle_publique_hex)
        data, user = _relire(paquet)
        self.assertEqual(paquet.to, bridge.BROADCAST_NUM)
        self.assertEqual(bytes(user.public_key).hex(), echange.cle_publique_hex)
        self.assertEqual(data.bitfield, bridge.BITFIELD_OK_TO_MQTT)
        self.assertFalse(data.want_response)
        self.assertFalse(paquet.HasField("decoded"))             # chiffrée par la clé du canal

    def test_un_companion_sans_chiffrement_annonce_en_clair(self):
        """Le défaut du 17/11/2026 : les messages partaient en clair et l'identité chiffrée.
        Sur un broker qui ne relaie que le clair, la clé publique n'arrivait à personne."""
        echange, _ = _echange()
        paquet = bridge.construire_identite(_compagnon(chiffrement=False), "Equipe", {"psk": PSK}, echange.cle_publique_hex)
        self.assertTrue(paquet.HasField("decoded"))
        self.assertEqual(paquet.decoded.portnum, portnums_pb2.PortNum.NODEINFO_APP)

    def test_une_demande_est_adressee_et_marquee_des_deux_facons(self):
        echange, _ = _echange()
        paquet = bridge.construire_identite(
            _compagnon(), "Equipe", {"psk": PSK}, echange.cle_publique_hex,
            destinataire=EMETTEUR, demander_reponse=True,
        )
        data, _ = _relire(paquet)
        self.assertEqual(paquet.to, EMETTEUR)
        self.assertTrue(data.want_response)
        self.assertTrue(data.bitfield & bridge.BITFIELD_WANT_RESPONSE)


class TestEchangeDesCles(unittest.IsolatedAsyncioTestCase):

    async def test_une_identite_entendue_est_rangee_sans_reponse(self):
        echange, publies = _echange()
        user, data = _identite_d_un_autre()
        coro = echange.identite_recue(EMETTEUR, bridge.BROADCAST_NUM, "Equipe", user, data, 42)
        self.assertIsNone(coro)
        self.assertEqual(echange.annuaire.cle(EMETTEUR), "07" * 32)
        self.assertEqual(publies, [])

    async def test_une_demande_qui_nous_est_adressee_recoit_notre_identite(self):
        for par_bitfield in (False, True):
            echange, publies = _echange()
            user, data = _identite_d_un_autre(demande=True, par_bitfield=par_bitfield)
            await echange.identite_recue(EMETTEUR, NOUS, "Equipe", user, data, 42)
            (canal, paquet), = publies
            reponse, identite = _relire(paquet)
            self.assertEqual((canal, paquet.to, reponse.request_id), ("Equipe", EMETTEUR, 42))
            self.assertEqual(bytes(identite.public_key).hex(), echange.cle_publique_hex)
            self.assertFalse(reponse.want_response)               # pas de ping-pong

    async def test_une_identite_qui_nous_est_adressee_vaut_confirmation(self):
        echange, _ = _echange()
        echange.annuaire.charger({"cles": [], "prioritaires": [EMETTEUR]})
        user, data = _identite_d_un_autre()
        echange.identite_recue(EMETTEUR, NOUS, "Equipe", user, data, 42)
        self.assertIsNone(echange.annuaire.prochain_a_demander())

    async def test_une_demande_adressee_a_un_autre_ne_nous_regarde_pas(self):
        echange, publies = _echange()
        user, data = _identite_d_un_autre(demande=True)
        self.assertIsNone(echange.identite_recue(EMETTEUR, 0x5555, "Equipe", user, data, 42))

    async def test_un_demandeur_insistant_n_a_qu_une_reponse(self):
        echange, publies = _echange()
        user, data = _identite_d_un_autre(demande=True)
        await echange.identite_recue(EMETTEUR, NOUS, "Equipe", user, data, 42)
        self.assertIsNone(echange.identite_recue(EMETTEUR, NOUS, "Equipe", user, data, 43))
        self.assertEqual(len(publies), 1)

    async def test_notre_propre_annonce_revenue_du_broker_est_ignoree(self):
        echange, publies = _echange()
        user, data = _identite_d_un_autre(demande=True)
        self.assertIsNone(echange.identite_recue(NOUS, NOUS, "Equipe", user, data, 42))
        self.assertIsNone(echange.annuaire.cle(NOUS))

    async def test_la_cle_manquante_d_un_correspondant_lui_est_demandee(self):
        echange, publies = _echange()
        echange.annuaire.charger({"cles": [], "prioritaires": [EMETTEUR]})
        self.assertTrue(await echange.demander(echange.annuaire.prochain_a_demander()))
        (canal, paquet), = publies
        data, _ = _relire(paquet)
        self.assertEqual((canal, paquet.to), ("Equipe", EMETTEUR))
        self.assertTrue(data.want_response)


class TestAnnuaire(unittest.TestCase):

    def test_on_ne_redemande_pas_avant_la_fenetre_du_firmware(self):
        temps = [1000.0]
        annuaire = bridge.AnnuaireCles(lambda: temps[0])
        annuaire.charger({"cles": [], "prioritaires": [EMETTEUR]})
        self.assertEqual(annuaire.prochain_a_demander(), EMETTEUR)
        self.assertIsNone(annuaire.prochain_a_demander())
        temps[0] += bridge.CLES_DEMANDE_PAR_NOEUD_S + 1
        self.assertEqual(annuaire.prochain_a_demander(), EMETTEUR)

    def test_avoir_sa_cle_ne_dit_pas_qu_il_a_la_notre(self):
        """Le constat du 17/11/2026 sur Gaulix : on avait la clé du nœud, lui n'avait pas la
        nôtre, et rien ne se passait. On se présente jusqu'à ce qu'il réponde."""
        annuaire = bridge.AnnuaireCles()
        annuaire.charger({"cles": [{"node_num": EMETTEUR, "public_key_hex": "0a" * 32}], "prioritaires": [EMETTEUR]})
        self.assertEqual(annuaire.cle(EMETTEUR), "0a" * 32)
        self.assertEqual(annuaire.prochain_a_demander(), EMETTEUR)

    def test_un_correspondant_qui_a_repondu_n_est_plus_sollicite(self):
        temps = [1000.0]
        annuaire = bridge.AnnuaireCles(lambda: temps[0])
        annuaire.charger({"cles": [{"node_num": EMETTEUR, "public_key_hex": "0a" * 32}], "prioritaires": [EMETTEUR]})
        annuaire.confirmer(EMETTEUR)
        temps[0] += bridge.CLES_DEMANDE_PAR_NOEUD_S + 1
        self.assertIsNone(annuaire.prochain_a_demander())

    def test_un_appareil_reel_ne_demande_que_les_cles_qui_manquent(self):
        """Il se présente déjà tout seul sur la radio : inutile d'en rajouter."""
        annuaire = bridge.AnnuaireCles()
        annuaire.charger({"cles": [{"node_num": EMETTEUR, "public_key_hex": "0a" * 32}], "prioritaires": [EMETTEUR, 0x3333]})
        self.assertEqual(annuaire.prochain_a_demander(seulement_sans_cle=True), 0x3333)
        self.assertIsNone(annuaire.prochain_a_demander(seulement_sans_cle=True))

    def test_une_cle_qui_change_est_signalee(self):
        annuaire = bridge.AnnuaireCles()
        self.assertEqual(annuaire.apprendre(EMETTEUR, "0a" * 32), "nouvelle")
        self.assertIsNone(annuaire.apprendre(EMETTEUR, "0A" * 32))
        self.assertEqual(annuaire.apprendre(EMETTEUR, "0b" * 32), "changee")

    def test_un_noeud_qui_nous_ecrit_sans_cle_connue_passe_devant(self):
        temps = [1000.0]
        annuaire = bridge.AnnuaireCles(lambda: temps[0])
        annuaire.charger({"cles": [], "prioritaires": [EMETTEUR]})
        annuaire.prochain_a_demander()
        annuaire.reclamer(EMETTEUR)                 # son message vient d'arriver, illisible
        self.assertEqual(annuaire.prochain_a_demander(), EMETTEUR)


class TestDejaVus(unittest.TestCase):

    def test_le_meme_paquet_par_deux_passerelles_n_est_traite_qu_une_fois(self):
        vus = bridge.DejaVus()
        self.assertFalse(vus.deja_vu(EMETTEUR, 7))
        self.assertTrue(vus.deja_vu(EMETTEUR, 7))
        self.assertFalse(vus.deja_vu(EMETTEUR, 8))
        self.assertFalse(vus.deja_vu(0x3333, 7))

    def test_la_memoire_est_bornee_et_un_paquet_illisible_se_retente(self):
        vus = bridge.DejaVus(taille=2)
        for identifiant in (1, 2, 3):
            vus.deja_vu(EMETTEUR, identifiant)
        self.assertFalse(vus.deja_vu(EMETTEUR, 1))  # sorti de la mémoire
        vus.oublier(EMETTEUR, 3)
        self.assertFalse(vus.deja_vu(EMETTEUR, 3))


class TestMessageChiffreParClePublique(unittest.TestCase):

    def _paquet(self, avec_cle=False):
        import crypto
        data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.TEXT_MESSAGE_APP, payload=b"secret")
        paquet = mesh_pb2.MeshPacket()
        setattr(paquet, "from", EMETTEUR)
        paquet.to, paquet.id = NOUS, 77
        paquet.encrypted = crypto.chiffrer_pkc(
            CLE_PRIVEE_AUTRE, crypto.cle_publique_depuis_privee_hex(CLE_PRIVEE_NOUS), 77, EMETTEUR,
            data.SerializeToString(),
        )
        if avec_cle:
            paquet.public_key = bytes.fromhex(crypto.cle_publique_depuis_privee_hex(CLE_PRIVEE_AUTRE))
        return paquet

    def test_un_appareil_ne_joint_pas_sa_cle_et_le_message_se_lit_quand_meme(self):
        """Le défaut : le pont exigeait la clé DANS le paquet, qu'un vrai appareil ne met pas."""
        import crypto
        annuaire = bridge.AnnuaireCles()
        annuaire.apprendre(EMETTEUR, crypto.cle_publique_depuis_privee_hex(CLE_PRIVEE_AUTRE))
        clair = bridge._dechiffrer_message_pki(self._paquet(), EMETTEUR, 77, CLE_PRIVEE_NOUS, annuaire)
        data = mesh_pb2.Data()
        data.ParseFromString(clair)
        self.assertEqual(data.payload, b"secret")

    def test_sans_cle_connue_le_message_reste_illisible(self):
        self.assertIsNone(
            bridge._dechiffrer_message_pki(self._paquet(), EMETTEUR, 77, CLE_PRIVEE_NOUS, bridge.AnnuaireCles())
        )

    def test_une_cle_perimee_dans_l_annuaire_n_empeche_pas_de_lire_celle_du_paquet(self):
        annuaire = bridge.AnnuaireCles()
        annuaire.apprendre(EMETTEUR, "0c" * 32)
        clair = bridge._dechiffrer_message_pki(self._paquet(avec_cle=True), EMETTEUR, 77, CLE_PRIVEE_NOUS, annuaire)
        self.assertIsNotNone(clair)


class FauxAppareilAvecRepertoire:
    """Le répertoire tel que la lib officielle le rend (clés en base64, noms en camelCase)."""

    def __init__(self):
        import base64
        self.envois = []
        self._cle = base64.b64encode(b"\x05" * 32).decode()
        self.nodes = {
            "!00009999": {"num": NOUS, "user": {"longName": "Nous"}},
            "!00001111": {
                "num": EMETTEUR, "lastHeard": 1700000000,
                "user": {"longName": "Autre", "shortName": "AUT", "hwModel": "HELTEC_V3",
                         "publicKey": base64.b64encode(b"\x07" * 32).decode()},
                "position": {"latitude": 45.5, "longitude": 4.2},
            },
            "!00003333": {"num": 0x3333, "user": {"longName": "Sans clé"}},
        }

    def getMyUser(self):
        return {"id": "!00009999", "longName": "Nous", "shortName": "NOUS", "hwModel": "HELTEC_V3",
                "role": "ROUTER"}

    def getPublicKey(self):
        return self._cle

    def sendData(self, data, destinationId=None, portNum=None, wantResponse=False, **kw):
        self.envois.append((data, destinationId, portNum, wantResponse))


class TestRepertoireDeLAppareil(unittest.TestCase):

    def test_le_repertoire_est_remonte_avec_les_cles_sans_nous_meme(self):
        contacts = {c["node_num"]: c for c in bridge.contacts_depuis_appareil(FauxAppareilAvecRepertoire(), NOUS)}
        self.assertEqual(set(contacts), {EMETTEUR, 0x3333})
        self.assertEqual(contacts[EMETTEUR]["public_key_hex"], "07" * 32)
        self.assertEqual(contacts[EMETTEUR]["latitude"], 45.5)
        self.assertNotIn("public_key_hex", contacts[0x3333])

    def test_la_demande_part_par_l_appareil_avec_notre_identite_complete(self):
        appareil = FauxAppareilAvecRepertoire()
        bridge.demander_identite_locale(appareil, 0x3333)
        (user, destinataire, port, reponse), = appareil.envois
        self.assertEqual((destinataire, port, reponse), (0x3333, portnums_pb2.PortNum.NODEINFO_APP, True))
        self.assertEqual(bytes(user.public_key), b"\x05" * 32)
        self.assertEqual(user.hw_model, mesh_pb2.HardwareModel.HELTEC_V3)
        self.assertEqual(user.long_name, "Nous")
        self.assertNotEqual(user.role, 0)                         # ROUTER, pas le défaut
