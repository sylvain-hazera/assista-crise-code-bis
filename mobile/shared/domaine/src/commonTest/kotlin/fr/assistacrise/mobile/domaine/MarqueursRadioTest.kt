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
        assertNull(MarqueursRadio.lire("Salut: S:🔥:0:1,2"))
        assertNull(MarqueursRadio.lire("S:🔥:0:95.0,2.0"))
        assertNull(MarqueursRadio.lire("S:🔥:0:abc,2"))
        assertNull(MarqueursRadio.lire("bonjour"))
    }

    @Test fun decimalesSansLaLangue() {
        assertEquals("0.00000", MarqueursRadio.cinqDecimales(0.0))
        assertEquals("-0.00001", MarqueursRadio.cinqDecimales(-0.00001))
        assertEquals("-12.34568", MarqueursRadio.cinqDecimales(-12.345678))
        assertEquals("0.00000", MarqueursRadio.cinqDecimales(-0.000001))
    }
}
