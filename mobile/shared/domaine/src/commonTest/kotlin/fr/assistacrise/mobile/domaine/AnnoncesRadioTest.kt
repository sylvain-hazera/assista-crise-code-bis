package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AnnoncesRadioTest {
    @Test
    fun lireUneAnnonceDuCentral() {
        val a = AnnoncesRadio.lire("📋 D-0123 · Pompage · Talence · 44.80000,-0.59000")!!
        assertEquals(AnnoncesRadio.Annonce("D-0123", "Pompage", "Talence", 44.8, -0.59), a)
        assertTrue(a.situee)
    }

    @Test
    fun derriereLesPrefixesDeLaRadio() {
        assertEquals("D-7", AnnoncesRadio.lire("Passerelle: PC: 📋 D-7 · Eau · -")?.numero)
    }

    @Test
    fun sansPositionNiCommune() {
        val a = AnnoncesRadio.lire("📋 D-9 · Pompage · -")!!
        assertEquals("", a.commune)
        assertNull(a.latitude)
    }

    @Test
    fun autreChoseNEnEstPas() {
        assertNull(AnnoncesRadio.lire("bonjour"))
        assertNull(AnnoncesRadio.lire("S:🔥:0:44.8,-0.5"))
        assertNull(AnnoncesRadio.lire("PC: rien en cours pour ce canal."))
    }

    @Test
    fun laPlusRecenteEtPasCellesDejaArrivees() {
        val vieille = AnnoncesRadio.Annonce("D-1", "Eau") to 1L
        val recente = AnnoncesRadio.Annonce("D-1", "Pompage") to 2L
        val connue = AnnoncesRadio.Annonce("D-2") to 3L
        assertEquals(listOf(recente), AnnoncesRadio.aGarder(listOf(vieille, recente, connue), setOf("D-2")))
    }

    @Test
    fun parRadioQuelquesMotsSeulement() {
        val m = MarqueursRadio.Marqueur("⛔", 44.85, -0.57, "1 sens · arbre tombé en travers de la chaussée après la tempête")
        assertEquals("S:⛔:0:44.85000,-0.57000:1 sens · arbre tombé en travers de la…", MarqueursRadio.ecrirePourLaRadio(m))
        assertEquals("S:🔥:0:44.85000,-0.57000:feu", MarqueursRadio.ecrirePourLaRadio(m.copy(emoji = "🔥", note = "feu")))
    }

    @Test
    fun informationEstUnGenre() {
        assertEquals("Information", MarqueursRadio.libelle("ℹ️"))
    }
}
