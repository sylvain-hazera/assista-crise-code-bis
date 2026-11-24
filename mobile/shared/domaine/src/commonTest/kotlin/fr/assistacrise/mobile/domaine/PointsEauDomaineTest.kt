package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PointsEauDomaineTest {
    private fun point(id: Long, lat: Double, lon: Double, source: String = "OSM") =
        PointEau(id = id, source = source, latitude = lat, longitude = lon)

    @Test fun unNouveauPointAMoinsDeCinquanteMetresEstUnDoublonPossible() {
        val connus = listOf(point(1, 45.44000, 4.38700), point(2, 45.44030, 4.38700), point(3, 45.45, 4.39))
        // 0,0003° de latitude ≈ 33 m : 1 et 2 sont à moins de 50 m, 3 est loin.
        val doublons = doublonsPossibles(connus, 45.44001, 4.38700)
        assertEquals(listOf(1L, 2L), doublons.map { it.id })
        assertTrue(doublonsPossibles(connus, 45.30, 4.10).isEmpty())
    }

    @Test fun leToucherChoisitLePlusProcheDansLeRayon() {
        val connus = listOf(point(1, 45.44, 4.387), point(2, 45.4401, 4.387))
        assertEquals(2L, pointLePlusProche(connus, 45.44009, 4.387, 30.0)?.id)
        assertNull(pointLePlusProche(connus, 45.45, 4.387, 30.0))
    }

    @Test fun lesRelevesSeReunissentSansDoublonEtLaSourceSeDit() {
        val reunis = reunirPointsEau(listOf(listOf(point(1, 45.0, 4.0), point(2, 45.1, 4.1)), listOf(point(2, 45.1, 4.1))))
        assertEquals(listOf(1L, 2L), reunis.map { it.id })
        assertTrue(point(1, 0.0, 0.0).indicatif)
        assertEquals("Base du SDIS", point(1, 0.0, 0.0, "SDIS").libelleSource)
        assertEquals("Indisponible", point(1, 0.0, 0.0).copy(etat = "INDISPONIBLE").libelleEtat)
    }

    @Test fun distanceConnue() {
        // Saint-Étienne → Le Puy-en-Velay : environ 60 km à vol d'oiseau.
        val d = distanceMetres(45.4397, 4.3872, 45.0434, 3.8858)
        assertTrue(d in 55_000.0..62_000.0, "distance $d")
    }

    @Test fun lesGestesDuBinomeSuiventLeTerrainEtLaFilePrime() {
        assertEquals(listOf(EtatPointEau.EN_ROUTE, EtatPointEau.ACTIF), gestesPossibles("DEMANDE"))
        assertEquals(listOf(EtatPointEau.FERME), gestesPossibles("ACTIF"))
        assertTrue(gestesPossibles("ANNULE").isEmpty())
        val point = PointEauMission(id = "a1", nom = "BI-12", statut = "DEMANDE")
        assertEquals("DEMANDE" to false, etatPointEauAffiche(point, emptyList()))
        val enFile = ActionEnAttente(id = "x", genre = ActionEnAttente.GENRE_ETAT_POINT_EAU, cible = "a1",
                                     charge = """{"etat":"ACTIF","observe_le":"2026-11-24T14:05:00Z"}""", libelle = "", creeLe = 0)
        assertEquals("ACTIF" to true, etatPointEauAffiche(point, listOf(enFile)))
    }
}
