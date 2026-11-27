package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RechercheNoeudTest {
    @Test
    fun uneRequeteVideGardeTout() {
        assertTrue(RechercheNoeud.correspond("  ", "FR29SPE_REPEATER"))
    }

    @Test
    fun sansAccentsNiCasse() {
        assertTrue(RechercheNoeud.correspond("repeteur", "FR29SPE_REPEATER", "Répéteur"))
        assertTrue(RechercheNoeud.correspond("FENEU", "49Feneu-Segre"))
        assertFalse(RechercheNoeud.correspond("bordeaux", "49Feneu-Segre"))
    }

    @Test
    fun chaqueMotDoitSeTrouver() {
        assertTrue(RechercheNoeud.correspond("repeteur 40", "FR40SPLD_Pianiste#01", "Répéteur", "a0364e7db399"))
        assertFalse(RechercheNoeud.correspond("compagnon 40", "FR40SPLD_Pianiste#01", "Répéteur"))
    }

    @Test
    fun parIdentifiantOuCle() {
        assertTrue(RechercheNoeud.correspond("!6c73", "Meshtastic YA22", "Y41V", "!6c730f74"))
        assertTrue(RechercheNoeud.correspond("148d2", "44SHER", null, "148d2decd1bf"))
    }
}
