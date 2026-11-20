package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.AdresseReseau.Companion.Lecture
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

/** Le cadrage TCP tel que les firmwares l'écrivent (voir LiaisonReseau.kt). */
class LiaisonReseauTest {

    @Test fun meshcoreEncadreCommeLaLiaisonSerie() {
        val cadrage = CadrageFlux.pour(Protocole.MESHCORE)
        assertEquals(5000, cadrage.portParDefaut)
        assertEquals("3c02001603", cadrage.encadrer(MeshCore.requeteAppareil()).enHex())
        assertEquals(0, cadrage.reveil().size)
    }

    @Test fun meshcoreDecoupeLeFluxQuelleQueSoitLaTailleDesMorceaux() {
        val d = CadrageFlux.MeshCoreTcp.decoupeur()
        // Deux trames de la radio (« > », longueur petit-boutiste), coupées n'importe où.
        val flux = "3e03000102033e0200aabb".depuisHex()
        val recues = mutableListOf<ByteArray>()
        for (octet in flux) recues += d.pousser(byteArrayOf(octet))
        assertEquals(listOf("010203", "aabb"), recues.map { it.enHex() })
    }

    @Test fun meshcoreSeRecaleApresUnFauxDepart() {
        val d = CadrageFlux.MeshCoreTcp.decoupeur()
        // Du bruit, un « > » suivi d'une longueur absurde, puis une vraie trame.
        val trames = d.pousser("00113effff" .depuisHex() + "3e01000c".depuisHex())
        assertEquals(listOf("0c"), trames.map { it.enHex() })
    }

    @Test fun meshtasticEncadreEnGrosBoutiste() {
        val cadrage = CadrageFlux.pour(Protocole.MESHTASTIC)
        assertEquals(4403, cadrage.portParDefaut)
        val config = Meshtastic.veutConfig(Meshtastic.NONCE_CONFIG)
        val trame = cadrage.encadrer(config)
        assertEquals("94c3", trame.copyOfRange(0, 2).enHex())
        assertEquals(config.size, ((trame[2].toInt() and 0xff) shl 8) or (trame[3].toInt() and 0xff))
        assertContentEquals(config, trame.copyOfRange(4, trame.size))
        assertEquals(32, cadrage.reveil().size)
        assertTrue(cadrage.reveil().all { (it.toInt() and 0xff) == 0xc3 })
    }

    @Test fun meshtasticIgnoreLeJournalEtLesMorceaux() {
        val d = CadrageFlux.MeshtasticTcp.decoupeur()
        val longue = ByteArray(300) { (it % 251).toByte() }
        val flux = "INFO  | 12:00:01 Boot\r\n".encodeToByteArray() +
            CadrageFlux.MeshtasticTcp.encadrer("0801".depuisHex()) +
            "94".depuisHex() +                                   // un 0x94 isolé, sans 0xC3
            CadrageFlux.MeshtasticTcp.encadrer(longue)
        val recues = mutableListOf<ByteArray>()
        flux.toList().chunked(7).forEach { morceau -> recues += d.pousser(morceau.toByteArray()) }
        assertEquals(2, recues.size)
        assertEquals("0801", recues[0].enHex())
        assertContentEquals(longue, recues[1])
    }

    @Test fun meshtasticRefuseUneLongueurAuDelaDe512() {
        val d = CadrageFlux.MeshtasticTcp.decoupeur()
        val trames = d.pousser("94c30300".depuisHex() + CadrageFlux.MeshtasticTcp.encadrer("2a".depuisHex()))
        assertEquals(listOf("2a"), trames.map { it.enHex() })
    }

    @Test fun lesPilotesServentTelsQuelsSurLeFlux() {
        // Une réponse SELF_INFO de MeshCore arrivée par TCP : le pilote la lit comme en Bluetooth.
        val pilote = PiloteMeshCore()
        val selfInfo = ByteArray(58).also { it[0] = MeshCore.Rep.SELF_INFO.toByte() } + "T-Deck".encodeToByteArray()
        val (trame) = CadrageFlux.MeshCoreTcp.decoupeur().pousser(
            byteArrayOf(0x3e, (selfInfo.size and 0xff).toByte(), (selfInfo.size shr 8).toByte()) + selfInfo)
        pilote.recevoir(trame)
        assertEquals("T-Deck", pilote.identite)
    }

    @Test fun seuleUneAdresseLocaleEstAcceptee() {
        fun lire(texte: String) = AdresseReseau.lire(texte, 4403)
        assertEquals(AdresseReseau("192.168.4.1", 4403), assertIs<Lecture.Valide>(lire("192.168.4.1")).adresse)
        assertEquals(AdresseReseau("10.0.0.7", 5000), assertIs<Lecture.Valide>(lire(" tcp://10.0.0.7:5000/ ")).adresse)
        assertIs<Lecture.Valide>(lire("172.20.1.2"))
        assertIs<Lecture.Valide>(lire("100.101.1.2"))                     // VPN d'opérateur
        assertIs<Lecture.Valide>(lire("tdeck.local"))
        assertIs<Lecture.Valide>(lire("meshtastic"))
        assertIs<Lecture.Valide>(lire("[fe80::1]:4403"))
        assertIs<Lecture.Refusee>(lire("8.8.8.8"))                        // Internet : en clair, non
        assertIs<Lecture.Refusee>(lire("radio.exemple.fr"))
        assertIs<Lecture.Refusee>(lire("172.32.0.1"))
        assertIs<Lecture.Refusee>(lire("192.168.1"))
        assertIs<Lecture.Refusee>(lire("192.168.1.2:70000"))
        assertIs<Lecture.Refusee>(lire(""))
    }
}
