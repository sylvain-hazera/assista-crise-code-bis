package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.AdminMeshCore
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * Administration d'un répéteur MeshCore à distance (26/11/2026). Trames d'après le micrologiciel :
 * companion_radio/MyMesh.cpp (CMD_SEND_LOGIN, CMD_SEND_STATUS_REQ, onContactResponse,
 * queueMessage) et simple_repeater/MyMesh.h (RepeaterStats).
 */
class RepeteurMeshCoreTest {
    private val pub = "c1c2c3c4c5c6" + "00".repeat(26)

    private fun contactRepeteur(): ByteArray =
        byteArrayOf(3) + pub.depuisHex() + byteArrayOf(2, 0, 0) + ByteArray(64) + "Relais".encodeToByteArray().copyOf(32) + ByteArray(12)

    private fun le16(v: Int) = byteArrayOf(v.toByte(), (v shr 8).toByte())
    private fun le32(v: Long) = ByteArray(4) { (v ushr (8 * it)).toByte() }
    private val envoye = byteArrayOf(6, 0) + ByteArray(4) + le32(5000)

    @Test fun trames() {
        assertEquals("1a" + pub + "736563726574", AdminMeshCore.connexion(pub, "secret").enHex())
        assertEquals("1b" + pub, AdminMeshCore.demanderStatut(pub).enHex())
        assertEquals("1d" + pub, AdminMeshCore.deconnexion(pub).enHex())
        // Commande : type de texte 1 (CLI), tentative 0, heure, préfixe de 6 octets, texte.
        assertEquals("0201" + "00" + "10000000" + "c1c2c3c4c5c6" + "ver".encodeToByteArray().enHex(),
            fr.assistacrise.mobile.lien.meshcore.MeshCore.envoyerMessage(pub, "ver", 16, typeTexte = 1).enHex())
    }

    @Test fun lireLeStatut() {
        val stats = le16(4100) + le16(1) + le16(-118) + le16(-95) + le32(1000) + le32(800) + le32(120) + le32(86400) +
            le32(500) + le32(300) + le32(600) + le32(400) + le16(2) + le16(22) + le16(3) + le16(7) + le32(900) + le32(4)
        assertEquals(56, stats.size)
        val s = assertNotNull(AdminMeshCore.lireStatut(byteArrayOf(0x87.toByte(), 0) + pub.depuisHex().copyOf(6) + stats))
        assertEquals(4100, s.batterieMv); assertEquals(-118, s.bruitDbm); assertEquals(-95, s.dernierRssi)
        assertEquals(86400L, s.enMarcheS); assertEquals(5.5f, s.dernierSnr); assertEquals(4L, s.erreursReception)
        assertEquals("c1c2c3c4c5c6", s.prefixeHex)
    }

    @Test fun sessionComplete() {
        val p = PiloteMeshCore { 1_000L }
        p.recevoir(byteArrayOf(1))                       // fin de lecture : radio prête
        p.recevoir(contactRepeteur())
        p.seConnecter(pub, "secret")
        assertEquals(PiloteRadio.EtatSession.CONNEXION, p.avance.repeteurs[pub]!!.etat)
        assertTrue(p.recevoir(envoye).accuses.isEmpty())
        // Connexion réussie, administrateur, rôle 3.
        p.recevoir(byteArrayOf(0x85.toByte(), 1) + pub.depuisHex().copyOf(6) + le32(0) + byteArrayOf(3, 2))
        val s = p.avance.repeteurs[pub]!!
        assertEquals(PiloteRadio.EtatSession.CONNECTEE, s.etat); assertTrue(s.admin); assertEquals(3, s.role)

        p.commandeRepeteur(pub, "ver", 16)
        p.recevoir(envoye)
        // La réponse (type de texte 1) va dans la console, pas dans la messagerie.
        val reponse = byteArrayOf(7) + pub.depuisHex().copyOf(6) + byteArrayOf(0, 1) + le32(17) + "v1.11.0".encodeToByteArray()
        val r = p.recevoir(reponse)
        assertTrue(r.directs.isEmpty())
        assertEquals(listOf(true to "ver", false to "v1.11.0"), p.avance.repeteurs[pub]!!.console.map { it.moi to it.texte })
    }

    @Test fun motDePasseRefuse() {
        val p = PiloteMeshCore { 1_000L }
        p.recevoir(byteArrayOf(1)); p.recevoir(contactRepeteur())
        p.seConnecter(pub, "faux"); p.recevoir(envoye)
        p.recevoir(byteArrayOf(0x86.toByte(), 0) + pub.depuisHex().copyOf(6))
        assertEquals(PiloteRadio.EtatSession.REFUSEE, p.avance.repeteurs[pub]!!.etat)
        assertEquals("mot de passe refusé", p.avance.repeteurs[pub]!!.raison)
    }

    @Test fun lesAccusesDesMessagesDirectsRestentJustes() {
        val p = PiloteMeshCore { 1_000L }
        p.recevoir(byteArrayOf(1)); p.recevoir(contactRepeteur())
        // Statut demandé, puis un vrai message direct : chaque « envoyé » retrouve le sien.
        p.demanderStatutRepeteur(pub)
        p.envoyerDirect(pub, "salut", 16, idLocal = 42)
        p.recevoir(envoye)                                                     // celui du statut
        p.recevoir(byteArrayOf(6, 0) + le32(0xabcdef) + le32(5000))           // celui du message
        val r = p.recevoir(byteArrayOf(0x82.toByte()) + le32(0xabcdef) + le32(1200))
        assertEquals(listOf(Accuse(42, StatutAccuse.RECU, 1200)), r.accuses)
    }
}
