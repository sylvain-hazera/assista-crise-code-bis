package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Emplacements d'urgence 5-6-7, sauvegarde et restauration (25/11/2026). */
class PlanUrgenceTest {
    private val crise = EntreeUrgence("crise", "CriseGier", "01")
    private val equipe = EntreeUrgence("equipe", "AC-ALPH", "ab".repeat(16))
    private val commune = EntreeUrgence("commune", "RiveDeGier", "01")
    private val table = listOf(
        CanalComplet(0, "LongFast", "01"),
        CanalComplet(2, "AC-ALPH", "ab".repeat(16)),           // l'équipe est déjà là
        CanalComplet(5, "ADRASEC", "cd".repeat(16)),           // occupé : sera sauvegardé
    )

    @Test fun dejaPresentUtiliseOccupeRemplace() {
        val p = PlanUrgence.proposer(listOf(crise, equipe, commune), table, meshcore = false)
        assertEquals(5, p[0].emplacement); assertEquals("ADRASEC", p[0].remplace?.nom)
        assertEquals(2, p[1].dejaPresent); assertNull(p[1].emplacement)
        assertEquals(7, p[2].emplacement); assertNull(p[2].remplace)
        assertEquals(listOf(5 to crise, 7 to commune), PlanUrgence.aEcrire(p))
    }

    @Test fun memeNomAutreCleNEstPasLeMemeCanal() {
        val p = PlanUrgence.proposer(listOf(equipe), listOf(CanalComplet(2, "AC-ALPH", "00".repeat(16))), meshcore = false)
        assertNull(p[0].dejaPresent); assertEquals(6, p[0].emplacement)
    }

    @Test fun choixDeLIntervenantEtControles() {
        val p = PlanUrgence.proposer(listOf(crise, commune), table, meshcore = false, choix = mapOf("crise" to 3))
        assertEquals(3, p[0].emplacement); assertNull(p[0].remplace)
        assertNull(PlanUrgence.erreur(p, 8))
        assertNotNull(PlanUrgence.erreur(PlanUrgence.proposer(listOf(crise, commune), table, false, mapOf("crise" to 7)), 8))
        assertNotNull(PlanUrgence.erreur(PlanUrgence.proposer(listOf(crise), table, false, mapOf("crise" to 0)), 8))
    }

    @Test fun meshCoreLesTroisDerniers() {
        assertEquals(mapOf("crise" to 37, "equipe" to 38, "commune" to 39), PlanUrgence.emplacementsParDefaut(true, 40))
    }

    @Test fun restaurerRemetLOrigineVideLesLibresEtGardeLEquipe() {
        val ecritCrise = CanalComplet(5, "CriseGier", "01")
        val ecritEquipe = CanalComplet(6, "AC-ALPH", "ab".repeat(16))
        val ecritCommune = CanalComplet(7, "RiveDeGier", "01")
        val s = SauvegardeRadio("a1b2", "MESHTASTIC", 0, table = table, ecrits = listOf(ecritCrise, ecritEquipe, ecritCommune),
                                roles = mapOf(5 to "crise", 6 to "equipe", 7 to "commune"))
        val actuelle = listOf(table[0], table[1], ecritCrise, ecritEquipe, CanalComplet(7, "Perso", "ee".repeat(16)))
        val actions = PlanUrgence.restaurer(s, actuelle, garderEquipe = true)
        assertEquals(listOf(5, 7), actions.map { it.index })
        assertEquals("ADRASEC", actions[0].vers?.nom)                  // l'origine revient
        assertTrue(actions[1].modifieDepuis)                           // changé à la main : signalé
        assertEquals(3, PlanUrgence.restaurer(s, actuelle, garderEquipe = false).size)
    }

    @Test fun lienDeCanalMeshtastic() {
        val lien = PlanUrgence.lienMeshtastic(listOf("AC-ALPH" to "ab".repeat(16), "Rive" to "01"))
        assertTrue(lien.startsWith("https://meshtastic.org/e/?add=true#"))
        // Même encodage que le serveur (radio_equipe.lien_meshtastic), vérifié octet par octet.
        assertEquals("https://meshtastic.org/e/?add=true#ChsSEKurq6urq6urq6urq6urq6saB0FDLUFMUEgKCRIBARoEUml2ZQ", lien)
    }
}
