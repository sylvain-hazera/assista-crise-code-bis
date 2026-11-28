package fr.assistacrise.mobile.domaine

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Où un marqueur peut se poser (28/11/2026) : miroir de backend/core/zones_marqueurs.py. */
class ZoneMarquageTest {
    private val carre = Json.parseToJsonElement("""{"type":"Polygon","coordinates":[[[4.0,45.0],[5.0,45.0],[5.0,46.0],[4.0,46.0],[4.0,45.0]],
        [[4.4,45.4],[4.6,45.4],[4.6,45.6],[4.4,45.6],[4.4,45.4]]]}""")

    @Test
    fun dansLeContourEtHorsDuTrou() {
        assertTrue(ZoneMarquage.dansGeoJson(carre, 45.2, 4.2))
        assertFalse(ZoneMarquage.dansGeoJson(carre, 45.5, 4.5))       // dans le trou
        assertFalse(ZoneMarquage.dansGeoJson(carre, 46.5, 4.5))
    }

    @Test
    fun multiPolygone() {
        val deux = Json.parseToJsonElement("""{"type":"MultiPolygon","coordinates":[[[[0,0],[1,0],[1,1],[0,1],[0,0]]],[[[10,10],[11,10],[11,11],[10,11],[10,10]]]]}""")
        assertTrue(ZoneMarquage.dansGeoJson(deux, 10.5, 10.5))
        assertFalse(ZoneMarquage.dansGeoJson(deux, 5.0, 5.0))
    }

    @Test
    fun criseSansContourLeRayon() {
        val crise = CrisePerimetre(id = "c", latitude = 45.0, longitude = 4.0, rayonKm = 10.0)
        assertTrue(crise.contient(45.05, 4.0))                            // ~5,6 km
        assertFalse(crise.contient(45.2, 4.0))                            // ~22 km
        assertTrue(CrisePerimetre(id = "c", zone = carre, latitude = 45.0, longitude = 4.0, rayonKm = 1.0).contient(45.9, 4.9))
    }

    @Test
    fun manifestationCinqKilometres() {
        val m = ManifestationAsso(id = "m", titre = "Course", debut = "", fin = "", zonePoints = listOf(listOf(45.0, 4.0)))
        assertTrue(m.pres(45.03, 4.0))                                    // ~3,3 km
        assertFalse(m.pres(45.1, 4.0))                                    // ~11 km
        // Serveur ancien, sans zone_points : le lieu.
        assertTrue(ManifestationAsso(id = "m", titre = "C", debut = "", fin = "", latitude = 45.0, longitude = 4.0).pres(45.01, 4.0))
    }
}
