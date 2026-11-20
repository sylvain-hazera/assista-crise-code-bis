package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private val SECTEUR = SecteurEmbarque(
    crise = "c1", latitude = 44.87, longitude = -1.2, rayonM = 1000.0, genereLe = "2026-11-20T08:00:00Z",
    adresses = listOf(
        AdresseEmbarquee("a1", "1 Rue des Pins", 44.87, -1.2000),
        AdresseEmbarquee("a3", "3 Rue des Pins", 44.87, -1.2003),
        AdresseEmbarquee("a12", "12 Allée des Chênes", 44.87, -1.2100),
    ),
    biens = listOf(
        BienEmbarque(id = "h1", banId = "a1", adresse = "1 Rue des Pins", latitude = 44.8701, longitude = -1.2000, statutEvaluation = "DETRUITE"),
        BienEmbarque(id = "h2", adresse = "Véhicule — parking", latitude = 44.8702, longitude = -1.2002, statutEvaluation = "DETRUITE", typeBien = "Véhicule"),
    ),
)

private fun constat(banId: String? = null, lat: Double? = null, lon: Double? = null) =
    Constat(id = "k-$banId-$lat", crise = "c1", banId = banId, latitude = lat, longitude = lon, statutEvaluation = "DEGATS_FORTS", constateLe = "2026-11-20T09:00:00Z")

class DegatsTest {
    @Test fun laTourneeHorsLigneVaDuPlusProcheAuPlusLointain() {
        val points = tourneeHorsLigne(SECTEUR, emptyList(), 44.87, -1.2002, rayonM = 100.0)
        // a3 à 8 m, le bien de a1 (replacé) à 19 m, le véhicule h2 à 22 m.
        assertEquals(listOf("a3", "a1", "h2"), points.map { it.banId ?: it.habitation })
        val adresseConnue = points.first { it.banId == "a1" }
        assertEquals("h1", adresseConnue.habitation)
        assertEquals(44.8701, adresseConnue.latitude)                       // la position du bien l'emporte
        assertTrue(points.none { it.banId == "a12" })                        // à 780 m
    }

    @Test fun ceQuiEstEvalueIciEstMarqueEtLePointNouveauApparait() {
        val points = tourneeHorsLigne(SECTEUR, listOf(constat(banId = "a3"), constat(lat = 44.8705, lon = -1.2001)), 44.87, -1.2002)
        assertTrue(points.first { it.banId == "a3" }.enAttente)
        assertTrue(points.any { it.enAttente && it.banId == null && it.libelle == "Point ajouté ici" })
    }

    @Test fun leSuivantEstLePlusProcheQuiResteAEvaluer() {
        val points = tourneeHorsLigne(SECTEUR, listOf(constat(banId = "a3")), 44.87, -1.2002)
        assertEquals(null, prochainPoint(points))                            // h2 et a1 détruits, a3 évalué ici
        val sansConstat = tourneeHorsLigne(SECTEUR, emptyList(), 44.87, -1.2002)
        assertEquals("a3", prochainPoint(sansConstat)?.banId)
        assertEquals(null, prochainPoint(sansConstat, sauf = "a3"))
    }

    @Test fun leSecteurSEffaceDesQueToutEstParti() {
        val enFile = ActionEnAttente("1", ActionEnAttente.GENRE_CONSTAT, "k", "{}", "x", 0)
        assertFalse(secteurAEffacer(SECTEUR, emptyList()))                   // rien saisi : on le garde
        assertFalse(secteurAEffacer(SECTEUR.copy(constatsFaits = 2), listOf(enFile)))
        assertTrue(secteurAEffacer(SECTEUR.copy(constatsFaits = 2), emptyList()))
        assertFalse(secteurAEffacer(null, emptyList()))
    }

    @Test fun laDistanceEstJusteSurQuelquesCentainesDeMetres() {
        assertEquals(23.8, distanceM(44.87, -1.2, 44.87, -1.2003), 0.5)
        assertEquals(111.3, distanceM(44.87, -1.2, 44.871, -1.2), 0.5)
    }
}
