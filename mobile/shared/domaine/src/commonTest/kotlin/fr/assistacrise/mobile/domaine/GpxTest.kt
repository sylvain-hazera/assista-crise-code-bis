package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class GpxTest {
    @Test fun pointsDePassage() {
        val g = Gpx.ecrire(listOf(Gpx.Point("🔥 Feu", 44.84, -0.58, "2 ha <rive> & pont", "2026-11-26T18:30:00Z", "Danger Area")), "Carte")
        assertTrue(g.startsWith("<?xml"))
        assertTrue("""<wpt lat="44.84000" lon="-0.58000"><time>2026-11-26T18:30:00Z</time><name>🔥 Feu</name><desc>2 ha &lt;rive&gt; &amp; pont</desc><sym>Danger Area</sym></wpt>""" in g)
        assertEquals(1, Regex("<wpt ").findAll(g).count())
        assertTrue(g.trimEnd().endsWith("</gpx>"))
    }
}
