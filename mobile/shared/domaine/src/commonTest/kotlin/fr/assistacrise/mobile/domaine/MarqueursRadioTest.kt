package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class MarqueursRadioTest {
    @Test fun ecrireEtRelire() {
        val m = MarqueursRadio.Marqueur("🔥", 44.84, -0.58, "départ de feu, 2 ha")
        val t = MarqueursRadio.ecrire(m)
        assertEquals("S:🔥:0:44.84000,-0.58000:départ de feu, 2 ha", t)
        assertEquals(m, MarqueursRadio.lire(t))
    }

    @Test fun formesDeMeshCoreSar() {
        // Forme actuelle, sans note ; ancienne forme sans couleur ; note sur plusieurs lignes.
        assertEquals(MarqueursRadio.Marqueur("🧑", 45.1, 5.2, couleur = 3), MarqueursRadio.lire("S:🧑:3:45.1,5.2"))
        assertEquals(MarqueursRadio.Marqueur("📦", 45.1, 5.2, "sac"), MarqueursRadio.lire("S:📦:45.1,5.2:sac"))
        assertEquals("pont\nrive gauche", MarqueursRadio.lire("S:🏕️:0:45.1,5.2:pont\nrive gauche")!!.note)
        assertEquals("rdv 14:30", MarqueursRadio.lire("S:🔥:0:45.1,5.2:rdv 14:30")!!.note)
    }

    @Test fun refuseCeQuiNEnEstPas() {
        assertNull(MarqueursRadio.lire("voir S:🔥:0:1,2 plus haut"))
        assertNull(MarqueursRadio.lire("S:🔥:0:95.0,2.0"))
        assertNull(MarqueursRadio.lire("S:🔥:0:abc,2"))
        assertNull(MarqueursRadio.lire("bonjour"))
    }

    @Test fun lireDerriereLesPrefixes() {
        // Radio MeshCore (« Nom: ») et relais du canal de crise (« Passerelle: Nom: »).
        assertEquals("⛔", MarqueursRadio.lire("Léa: S:⛔:0:44.85000,-0.57000")!!.emoji)
        assertEquals("arbre", MarqueursRadio.lire("Passerelle: Léa: S:⛔:0:44.85000,-0.57000:arbre")!!.note)
        assertNull(MarqueursRadio.lire("Attention: route coupée D20"))
    }

    @Test fun laCarteGardeLeDernierEtatDUneRouteEtUnSeulExemplaire() {
        val m = { e: String, lat: Double -> MarqueursRadio.Marqueur(e, lat, -0.57) }
        // Du plus récent au plus ancien.
        val liste = listOf(
            m("🚧", 44.85010),          // une voie libérée, 11 m plus loin : remplace la coupure
            m("🔥", 44.85000),          // un feu au même endroit : s'ajoute
            m("⛔", 44.85000),          // l'ancienne coupure
            m("🔥", 44.85001),          // le même feu, réentendu par un autre relais
            m("⛔", 44.90000),          // une autre route, loin : gardée
        )
        val carte = MarqueursRadio.pourLaCarte(liste) { it }
        assertEquals(listOf("🚧", "🔥", "⛔"), carte.map { it.emoji })
        assertEquals(44.9, carte.last().latitude)
        assertEquals(true, MarqueursRadio.estRoute("✅"))
    }

    @Test fun decimalesSansLaLangue() {
        assertEquals("0.00000", MarqueursRadio.cinqDecimales(0.0))
        assertEquals("-0.00001", MarqueursRadio.cinqDecimales(-0.00001))
        assertEquals("-12.34568", MarqueursRadio.cinqDecimales(-12.345678))
        assertEquals("0.00000", MarqueursRadio.cinqDecimales(-0.000001))
    }
}
