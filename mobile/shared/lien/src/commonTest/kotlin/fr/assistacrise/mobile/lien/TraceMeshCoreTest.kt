package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.AdminMeshCore
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/**
 * Trace de chemin MeshCore (26/11/2026). Trames construites d'après le micrologiciel
 * (examples/companion_radio/MyMesh.cpp : CMD_SEND_TRACE_PATH, onTraceRecv) et la logique de
 * meshcore-open (screens/path_trace_map.dart, buildPath).
 */
class TraceMeshCoreTest {
    private fun contact(pub: String, type: Int, plen: Int, chemin: String): ByteArray =
        byteArrayOf(3) + pub.depuisHex() + byteArrayOf(type.toByte(), 0, plen.toByte()) + chemin.depuisHex().copyOf(64) +
            "N".encodeToByteArray().copyOf(32) + ByteArray(12)

    private val pubRepeteur = "c1" + "00".repeat(31)
    private val pubCompagnon = "d2" + "11".repeat(31)

    @Test fun leContactGardeSonChemin() {
        val c = assertNotNull(AdminMeshCore.lireContact(contact(pubRepeteur, 2, 2, "a1b2")))
        assertEquals(listOf("a1", "b2"), c.relais)
        // Empreintes de 2 octets : bits hauts de path_len = 01.
        val c2 = assertNotNull(AdminMeshCore.lireContact(contact(pubRepeteur, 2, 0x42, "a1a2b1b2")))
        assertEquals(listOf("a1a2", "b1b2"), c2.relais)
        assertEquals(2, c2.longueurChemin)
        // Inondation (0xFF) : pas de chemin.
        assertEquals(emptyList(), assertNotNull(AdminMeshCore.lireContact(contact(pubRepeteur, 2, 0xff, ""))).relais)
    }

    @Test fun cheminEnMiroir() {
        val rep = assertNotNull(AdminMeshCore.lireContact(contact(pubRepeteur, 2, 2, "a1b2")))
        // Répéteur : A, B, lui, B, A.
        assertEquals("a1b2c1b2a1" to 1, AdminMeshCore.cheminDeTrace(rep, listOf(rep), true)!!.let { it.first.enHex() to it.second })
        val comp = assertNotNull(AdminMeshCore.lireContact(contact(pubCompagnon, 1, 2, "a1b2")))
        // Compagnon : jusqu'à son dernier relais seulement.
        assertEquals("a1b2a1", AdminMeshCore.cheminDeTrace(comp, listOf(comp), false)!!.first.enHex())
        // Joint sans relais ni cible : rien à tracer.
        val direct = assertNotNull(AdminMeshCore.lireContact(contact(pubCompagnon, 1, 0, "")))
        assertNull(AdminMeshCore.cheminDeTrace(direct, listOf(direct), false))
        // Répéteur voisin direct : la trace va jusqu'à lui et revient.
        val voisin = assertNotNull(AdminMeshCore.lireContact(contact(pubRepeteur, 2, 0, "")))
        assertEquals("c1", AdminMeshCore.cheminDeTrace(voisin, listOf(voisin), true)!!.first.enHex())
    }

    @Test fun empreintesDeTroisOctetsAllongeesAQuatre() {
        val relais = assertNotNull(AdminMeshCore.lireContact(contact("a1a2a3a4" + "00".repeat(28), 2, 0, "")))
        val rep = assertNotNull(AdminMeshCore.lireContact(contact(pubRepeteur, 2, 0x81, "a1a2a3")))
        val (chemin, largeur) = assertNotNull(AdminMeshCore.cheminDeTrace(rep, listOf(relais, rep), true))
        assertEquals(4, largeur)
        assertEquals("a1a2a3a4" + "c1000000" + "a1a2a3a4", chemin.enHex())
        // Relais inconnu : pas de trace possible.
        assertNull(AdminMeshCore.cheminDeTrace(rep, listOf(rep), true))
    }

    @Test fun trameDeTrace() {
        // [36][tag LE][code d'accès 0][drapeaux : 0 = empreintes d'un octet][chemin]
        assertEquals("24" + "78563412" + "00000000" + "00" + "a1c1a1",
            AdminMeshCore.traceroute(0x12345678, "a1c1a1".depuisHex(), 1).enHex())
        assertEquals("01", AdminMeshCore.traceroute(1, "a1a2".depuisHex(), 2).enHex().substring(18, 20))
    }

    private fun reponseTrace(tag: Long, chemin: String, snrs: List<Int>, fin: Int, drapeaux: Int = 0): ByteArray {
        val c = chemin.depuisHex()
        return byteArrayOf(0x89.toByte(), 0, c.size.toByte(), drapeaux.toByte()) +
            ByteArray(4) { (tag ushr (8 * it)).toByte() } + ByteArray(4) + c + snrs.map { it.toByte() }.toByteArray() + byteArrayOf(fin.toByte())
    }

    @Test fun lireLaReponse() {
        val t = assertNotNull(AdminMeshCore.lireTrace(reponseTrace(7, "a1c1a1", listOf(22, -12, 8), 30)))
        assertEquals(7L, t.tag)
        assertEquals(listOf("a1" to 5.5f, "c1" to -3f, "a1" to 2f), t.sauts)
        assertEquals(7.5f, t.snrFinal)
    }

    @Test fun cycleCompletDansLePilote() {
        var maintenant = 1_700_000_000_000L
        val p = PiloteMeshCore { maintenant }
        p.recevoir(contact(pubRepeteur, 2, 1, "a1").also { it[0] = AdminMeshCore.Rep.CONTACT.toByte() })
        val trame = assertNotNull(p.tracer(pubRepeteur))
        assertEquals("a1c1a1", trame.copyOfRange(10, trame.size).enHex())
        val tag = 1_700_000_000L
        assertEquals(PiloteRadio.EtatTrace.DEMANDEE, p.avance.tracesMeshCore[pubRepeteur]!!.etat)
        // RESP_CODE_SENT : réservé, tag, délai estimé (ms).
        p.recevoir(byteArrayOf(6, 0) + ByteArray(4) { (tag ushr (8 * it)).toByte() } + byteArrayOf(0x10, 0x27, 0, 0))
        assertEquals(PiloteRadio.EtatTrace.PARTIE, p.avance.tracesMeshCore[pubRepeteur]!!.etat)
        assertEquals(10_000L, p.avance.tracesMeshCore[pubRepeteur]!!.delaiEstimeMs)
        maintenant += 3_000
        p.recevoir(reponseTrace(tag, "a1c1a1", listOf(20, 4, 12), 16))
        val fin = p.avance.tracesMeshCore[pubRepeteur]!!
        assertEquals(PiloteRadio.EtatTrace.REVENUE, fin.etat)
        assertEquals(3, fin.resultat!!.sauts.size)
        // Une réponse étrangère (autre tag) n'y touche pas.
        p.recevoir(reponseTrace(99, "b2", listOf(1), 1))
        assertEquals(3, p.avance.tracesMeshCore[pubRepeteur]!!.resultat!!.sauts.size)
    }

    @Test fun traceRefuseeParLaRadio() {
        val p = PiloteMeshCore { 1_000L }
        // Hors lecture initiale : la radio est prête (canal refusé = fin de lecture).
        p.recevoir(byteArrayOf(1))
        p.recevoir(contact(pubRepeteur, 2, 1, "a1"))
        assertNotNull(p.tracer(pubRepeteur))
        p.recevoir(byteArrayOf(1))
        assertEquals(PiloteRadio.EtatTrace.ECHEC, p.avance.tracesMeshCore[pubRepeteur]!!.etat)
    }
}
