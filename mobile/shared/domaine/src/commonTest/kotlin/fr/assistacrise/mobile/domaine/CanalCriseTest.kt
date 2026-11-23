package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** Un canal radio par crise, adressage « @INDICATIF » (23/11/2026). */
class CanalCriseTest {
    private val canal = CanalCrise("c1", "CriseGier", "#crisegier", "ALPHA")

    @Test fun adresserEtReconnaitre() {
        assertEquals("@ALPHA on arrive", canal.adresser("on arrive"))
        assertEquals("rendez-vous au pont", canal.pourMoi("@alpha rendez-vous au pont"))
        assertEquals("Léa: rendez-vous au pont", canal.pourMoi("Léa: @ALPHA rendez-vous au pont"))
        assertNull(canal.pourMoi("@BRAVO on arrive"))
        assertNull(canal.pourMoi("qui est sur la D88 ?"))
    }

    @Test fun lePlanDitCeQuiManqueEtOuLeMettre() {
        val plan = PlanRadio("c1", meshtastic = listOf(CanalPlanMeshtastic("Fr_Balise"), CanalPlanMeshtastic("Fr_EMCOM"), CanalPlanMeshtastic("CriseGier")),
                             meshcore = listOf(CanalPlanMeshCore("#crisegier")))
        assertEquals(listOf("CriseGier"), plan.absents(false, listOf("LongFast", "fr_balise", "Fr_EMCOM")))
        assertEquals(emptyList(), plan.absents(true, listOf("Public", "crisegier")))
        assertEquals(3, PlanRadio.emplacementLibreMeshtastic(mapOf(0 to 1, 1 to 2, 2 to 2, 3 to 0)))
        assertNull(PlanRadio.emplacementLibreMeshtastic((0..7).associateWith { 2 }))
        assertEquals(2, PlanRadio.emplacementLibreMeshCore(setOf(0, 1)))
    }
}
