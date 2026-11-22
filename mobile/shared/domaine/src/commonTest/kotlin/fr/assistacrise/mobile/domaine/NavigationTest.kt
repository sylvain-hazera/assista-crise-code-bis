package fr.assistacrise.mobile.domaine

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class NavigationTest {
    @Test fun distanceEtCapEntreDeuxPointsConnus() {
        // Bordeaux (Pey-Berland) -> Mérignac : environ 5,5 km vers l'ouest.
        val d = Navigation.distanceM(44.8378, -0.5772, 44.8446, -0.6466)
        assertTrue(abs(d - 5_530) < 200, "distance $d")
        val cap = Navigation.capDeg(44.8378, -0.5772, 44.8446, -0.6466)
        assertTrue(cap in 270.0..290.0, "cap $cap")
        assertEquals("O", Navigation.capLisible(cap).substringAfter(" "))
    }

    @Test fun laFlecheTientCompteDeLOrientationDuTelephone() {
        assertEquals(0.0, Navigation.angleFleche(90.0, 90.0))
        assertEquals(270.0, Navigation.angleFleche(0.0, 90.0))
    }

    @Test fun autourDeMoiTrieParDistance() {
        val proches = Navigation.autourDe(44.84, -0.58, listOf(
            Destination("Loin", 45.0, -0.58, "point"), Destination("Près", 44.841, -0.58, "point")))
        assertEquals(listOf("Près", "Loin"), proches.map { it.first.nom })
        assertEquals("111 m", Navigation.distanceLisible(proches.first().second))
    }

    @Test fun estimationDesTuiles() {
        // Un carré d'environ 1 km : une tuile au zoom 10, quelques dizaines au zoom 16.
        val n = CartesEmbarquees.tuiles(44.835, -0.585, 44.845, -0.570, 16, 16)
        assertTrue(n in 4..30, "tuiles $n")
        assertTrue(CartesEmbarquees.tuiles(44.0, -1.3, 45.6, 0.3, 6, 14) > CartesEmbarquees.tuiles(44.0, -1.3, 45.6, 0.3, 6, 12))
        assertEquals("18 Mo", CartesEmbarquees.tailleLisible(1000 * CartesEmbarquees.OCTETS_PAR_TUILE))
    }
}
