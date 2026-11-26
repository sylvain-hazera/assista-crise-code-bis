package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** La carte hors ligne de la zone en cours (27/11/2026) : crise ou manifestation + 15 km. */
class ZoneHorsLigneTest {
    @Test fun unPointPlusQuinzeKilometres() {
        val e = CartesEmbarquees.emprise(listOf(44.84 to -0.58))!!
        // 15 km de chaque côté : environ 0,135° en latitude, 0,19° en longitude à Bordeaux.
        assertTrue(e.nord - e.sud in 0.26..0.28, "hauteur ${e.nord - e.sud}")
        assertTrue(e.est - e.ouest in 0.36..0.40, "largeur ${e.est - e.ouest}")
    }

    @Test fun assezPreciseSansPrendreToutLaPlace() {
        val (tuiles, octets) = CartesEmbarquees.estimationZone(CartesEmbarquees.emprise(listOf(44.84 to -0.58))!!)
        // Niveaux 6 à 15 : environ 1 700 tuiles, une trentaine de mégaoctets.
        assertTrue(tuiles in 1_200L..2_500L, "tuiles $tuiles")
        assertTrue(octets < 50_000_000L, "octets $octets")
    }

    @Test fun plusieursLieuxEtRien() {
        val e = CartesEmbarquees.emprise(listOf(44.84 to -0.58, 44.90 to -0.50))!!
        assertTrue(e.sud < 44.84 && e.nord > 44.90 && e.ouest < -0.58 && e.est > -0.50)
        assertNull(CartesEmbarquees.emprise(emptyList()))
    }
}
