package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.Ecrivain
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Sauts, signal et accusés de réception (26/11/2026), d'après companion_protocol.md (MeshCore)
 * et mesh.proto (Meshtastic : MeshPacket 8, 9, 12, 14, 15 ; Data 6, 7, 8 ; Routing 3). */
class ReceptionEtAccusesTest {
    @Test fun meshCoreSautsDansLesSixBitsBasDuChemin() {
        // Canal, V3 : SNR -6 (= -1,5 dB), canal 0, chemin 0x43 (empreintes de 2 octets, 3 sauts).
        val t = ("11" + "fa0000" + "00" + "43" + "00" + "60c51669").depuisHex() + "Léa: ok".encodeToByteArray()
        val m = MeshCore.lireMessageCanal(t)!!
        assertEquals(3, m.reception?.sauts)
        assertEquals(-1.5f, m.reception?.snr)
        // Direct, V3 : chemin 0 = entendu sans relais.
        val d = ("10" + "080000" + "a1b2c3d4e5f6" + "00" + "00" + "60c51669").depuisHex() + "salut".encodeToByteArray()
        assertEquals(0, MeshCore.lireMessageRecu(d)?.reception?.sauts)
    }

    @Test fun meshCoreAccuseDeReceptionDUnMessageDirect() {
        var maintenant = 1_000L
        val p = PiloteMeshCore { maintenant }
        p.envoyerDirect("a1b2c3d4e5f60708", "rdv au pont", 1763100000, idLocal = 42)
        // MSG_SENT : inondation, code attendu 0x11223344, délai estimé.
        assertTrue(p.recevoir("06014433221110270000".depuisHex()).accuses.isEmpty())
        // SEND_CONFIRMED : même code, aller-retour 1234 ms.
        val a = p.recevoir("8244332211d2040000".depuisHex()).accuses.single()
        assertEquals(Accuse(42, StatutAccuse.RECU, 1234), a)
        // Le même accusé reçu deux fois n'en fait qu'un.
        assertTrue(p.recevoir("8244332211d2040000".depuisHex()).accuses.isEmpty())
    }

    @Test fun meshCoreRefusJusteApresUnEnvoi() {
        var maintenant = 0L
        val p = PiloteMeshCore { maintenant }
        p.recevoir(byteArrayOf(1))                                         // fin de lecture : prête
        p.envoyerDirect("a1b2c3d4e5f60708", "x", 0, idLocal = 7)
        maintenant = 1_000
        assertEquals(StatutAccuse.ECHEC, p.recevoir("0102".depuisHex()).accuses.single().statut)
    }

    private fun recu(de: Long, vers: Long, port: Int, charge: ByteArray, id: Long, requete: Long = 0, repondA: Long = 0,
                     emoji: Boolean = false, depart: Int = 0, restant: Int = 0, snr: Float = 0f, rssi: Int = 0): ByteArray {
        val data = Ecrivain().varint(1, port.toLong()).brut(2, charge).fixe32(6, requete).fixe32(7, repondA).fixe32(8, if (emoji) 1 else 0)
        val paquet = Ecrivain().fixe32(1, de).fixe32(2, vers).message(4, data).fixe32(6, id)
            .fixe32(8, snr.toRawBits().toLong() and 0xffffffffL).varint(9, restant.toLong()).varint(12, rssi.toLong()).varint(15, depart.toLong())
        return Ecrivain().message(2, paquet).fin()
    }

    @Test fun meshtasticSautsSignalEtReponse() {
        val p = PiloteMeshtastic { 9 }
        val m = p.recevoir(recu(0x0badcafe, Meshtastic.DIFFUSION, 1, "vu".encodeToByteArray(), 77, repondA = 55,
                                depart = 3, restant = 1, snr = 6.25f, rssi = -95)).messages.single()
        assertEquals(Reception(sauts = 2, snr = 6.25f, rssi = -95), m.reception)
        assertEquals(77, m.id); assertEquals(55, m.repondA)
        // Une réaction émoji est marquée comme telle.
        val r = p.recevoir(recu(0x0badcafe, Meshtastic.DIFFUSION, 1, "👍".encodeToByteArray(), 78, repondA = 77, emoji = true)).messages.single()
        assertTrue(r.reaction)
    }

    @Test fun meshtasticRepondEtReagitNativement() {
        val p = PiloteMeshtastic { 9 }
        val trame = p.envoyerSurCanal(1, "bien reçu", repondA = 77).single()
        val relu = p.recevoir(trame.copyOf().also { it[0] = 0x12 }).messages.single()
        assertEquals(77, relu.repondA)
        assertEquals(false, relu.reaction)
    }

    @Test fun meshtasticAccuseDuDestinataireOuDUnRelais() {
        var n = 100L
        val p = PiloteMeshtastic { n++ }
        val (id, _) = p.envoyerDirect(0x0badcafe, "tu me reçois ?")
        assertEquals(100, id)
        // Accusé d'un relais (sans erreur) : relayé ; puis du destinataire : reçu.
        val routageOk = Ecrivain().zero(3).fin()
        assertEquals(StatutAccuse.RELAYE, p.recevoir(recu(0x11111111, 0x22222222, 5, routageOk, 900, requete = id)).accuses.single().statut)
        assertEquals(StatutAccuse.RECU, p.recevoir(recu(0x0badcafe, 0x22222222, 5, routageOk, 901, requete = id)).accuses.single().statut)
        // Un accusé pour un paquet inconnu est ignoré.
        assertTrue(p.recevoir(recu(0x0badcafe, 0x22222222, 5, routageOk, 902, requete = 12345)).accuses.isEmpty())
        // Échec : trop de réémissions.
        val (id2, _) = p.envoyerDirect(0x0badcafe, "et là ?")
        val echec = p.recevoir(recu(0x22222222, 0x22222222, 5, Ecrivain().varint(3, 5).fin(), 903, requete = id2)).accuses.single()
        assertEquals(StatutAccuse.ECHEC, echec.statut)
        assertEquals("trop de réémissions sans accusé", echec.raison)
        assertNull(Meshtastic.raisonErreur(0))
    }

    @Test fun meshtasticTraceroute() {
        var n = 500L
        val p = PiloteMeshtastic { n++ }
        val demande = p.traceroute(0x0badcafe)
        // La demande relue : port 70, sans charge, réponse demandée — ce n'est pas une réponse.
        assertTrue(Meshtastic.lire(demande.copyOf().also { it[0] = 0x12 }) is Meshtastic.Evenement.Autre)
        // Réponse : un relais 0x11111111 à l'aller (fixed32 empaqueté), SNR 22/4 puis -12/4 (int32 non empaquetés).
        val route = Ecrivain().brut(1, byteArrayOf(0x11, 0x11, 0x11, 0x11)).varint(2, 22).varint(2, -12).varint(4, -128)
        p.recevoir(recu(0x0badcafe, 0x22222222, 70, route.fin(), 600, requete = 500))
        val t = p.avance.trajets[0x0badcafe]!!
        assertEquals(listOf(0x11111111L), t.aller)
        assertEquals(listOf(5.5f, -3f), t.snrAller)
        assertEquals(listOf<Float?>(null), t.snrRetour)          // inconnu au retour
    }
}
