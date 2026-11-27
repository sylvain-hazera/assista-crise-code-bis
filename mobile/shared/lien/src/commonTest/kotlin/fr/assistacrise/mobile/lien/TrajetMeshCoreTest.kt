package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.MeshCore
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Trajet d'un message MeshCore reçu (27/11/2026), d'après le format des trames du firmware. */
class TrajetMeshCoreTest {
    private fun o(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }

    /** 0x88, SNR × 4, RSSI, puis la trame telle qu'entendue. */
    private fun entendue(entete: Int, octetChemin: Int, chemin: List<Int>, charge: List<Int>, transport: Boolean = false) =
        o(0x88, 0x14, -90 and 0xff, entete, *(if (transport) intArrayOf(1, 2, 3, 4) else intArrayOf()), octetChemin, *chemin.toIntArray(), *charge.toIntArray())

    private fun messageCanal(octetChemin: Int, texte: String) =
        o(17, 0x10, 0, 0, 0, octetChemin, 0, 1, 0, 0, 0) + texte.encodeToByteArray()

    private fun messageDirect(prefixe: List<Int>, octetChemin: Int, texte: String) =
        o(16, 0x10, 0, 0, *prefixe.toIntArray(), octetChemin, 0, 1, 0, 0, 0) + texte.encodeToByteArray()

    private val grpInondation = (MeshCore.CHARGE_GRP_TXT shl 2) or 1
    private val txtInondation = (MeshCore.CHARGE_TXT_MSG shl 2) or 1

    @Test
    fun laTrameEntendueDonneSesRelaisDansLOrdre() {
        val t = MeshCore.lireJournal(entendue(grpInondation, 2, listOf(0x3f, 0xa1), listOf(0x11, 0x22, 0x33)), 0)!!
        assertEquals(listOf("3f", "a1"), t.relais)
        assertEquals(5f, t.snr); assertEquals(-90, t.rssi)
        assertEquals(MeshCore.CHARGE_GRP_TXT, t.typeCharge)
        assertTrue(t.inondation)
        // Codes de transport (route 0) et empreintes de 2 octets (bits hauts de path_len à 01).
        val t2 = MeshCore.lireJournal(entendue(MeshCore.CHARGE_GRP_TXT shl 2, 0x42, listOf(0x3f, 0x01, 0xa1, 0x02), listOf(0x11), transport = true), 0)!!
        assertEquals(listOf("3f01", "a102"), t2.relais)
        // Une version inconnue ou un chemin plus long que la trame ne se lisent pas.
        assertNull(MeshCore.lireJournal(entendue(0x40 or grpInondation, 0, emptyList(), listOf(0x11)), 0))
        assertNull(MeshCore.lireJournal(entendue(grpInondation, 3, listOf(0x3f), emptyList()), 0))
    }

    @Test
    fun unMessageDeCanalPrendLeCheminEtSesCopiesRelayees() {
        val p = PiloteMeshCore()
        p.recevoir(entendue(grpInondation, 1, listOf(0x07), listOf(0x99, 0x98)))      // un autre message
        p.recevoir(entendue(grpInondation, 2, listOf(0x3f, 0xa1), listOf(0x11, 0x22, 0x33)))
        val r = p.recevoir(messageCanal(2, "Bob: bonjour")).messages.single().reception!!
        assertEquals(listOf(listOf("3f", "a1")), r.chemins.map { it.relais })
        assertEquals(5f, r.chemins.single().snr)
        // Une copie relayée ensuite par un autre répéteur rejoint le message.
        val suite = p.recevoir(entendue(grpInondation, 3, listOf(0x3f, 0xa1, 0x55), listOf(0x11, 0x22, 0x33))).chemins
        assertEquals(r.signature, suite.single().first)
        assertEquals(listOf("3f", "a1", "55"), suite.single().second.relais)
    }

    @Test
    fun unMessageDirectSeReconnaitASonExpediteur() {
        val p = PiloteMeshCore()
        p.recevoir(entendue(txtInondation, 1, listOf(0xaa), listOf(0x01, 0xbe, 0x10, 0x20, 0x30)))
        p.recevoir(entendue(txtInondation, 1, listOf(0xcc), listOf(0x01, 0xcd, 0x10, 0x20, 0x31)))
        val r = p.recevoir(messageDirect(listOf(0xbe, 1, 2, 3, 4, 5), 1, "salut")).directs.single().reception!!
        assertEquals(listOf(listOf("aa")), r.chemins.map { it.relais })
    }

    @Test
    fun sansTrameCorrespondanteOuParRouteDirecteRienNEstInvente() {
        val p = PiloteMeshCore()
        assertTrue(p.recevoir(messageCanal(2, "Bob: rien entendu")).messages.single().reception!!.chemins.isEmpty())
        p.recevoir(entendue(grpInondation, 2, listOf(0x3f, 0xa1), listOf(0x11)))
        assertTrue(p.recevoir(messageCanal(0xff, "Bob: direct")).messages.single().reception!!.chemins.isEmpty())
        // Une trame ne sert qu'à un seul message.
        assertEquals(1, p.recevoir(messageCanal(2, "Bob: un")).messages.single().reception!!.chemins.size)
        assertTrue(p.recevoir(messageCanal(2, "Bob: deux")).messages.single().reception!!.chemins.isEmpty())
    }
}
