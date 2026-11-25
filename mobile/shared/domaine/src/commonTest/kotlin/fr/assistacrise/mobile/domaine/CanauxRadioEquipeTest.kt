package fr.assistacrise.mobile.domaine

import fr.assistacrise.mobile.domaine.PlanCanauxEquipes.Action
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals

/** Les canaux d'équipe sur la radio du téléphone (25/11/2026). */
class CanauxRadioEquipeTest {
    private val alpha = CanalAInstaller("AC-ALPHA", "00".repeat(16), "v1")
    private val adrasec = CanalAInstaller("ADRA42", "11".repeat(16), "v9")

    @Test fun lireLaReponseDuServeur() {
        val json = """[{"equipe":"e1","nom_equipe":"Alpha","indicatif":"ALPHA",
            "meshtastic":{"nom":"AC-ALPHA","psk_hex":"00","version":"a"},"meshcore":null}]"""
        val premier = Json { ignoreUnknownKeys = true }.decodeFromString<List<CanauxRadioEquipe>>(json).single()
        assertEquals("AC-ALPHA", premier.meshtastic?.nom)
        assertEquals(listOf(CanalAInstaller("AC-ALPHA", "00", "a")), PlanCanauxEquipes.pour(false, listOf(premier)))
        assertEquals(emptyList(), PlanCanauxEquipes.pour(true, listOf(premier)))
    }

    @Test fun absentAjoute() {
        assertEquals(listOf(Action.Ajouter(alpha)), PlanCanauxEquipes.actions(listOf(alpha), emptyMap(), emptyMap()))
    }

    @Test fun dejaMisParLaPersonneJamaisTouche() {
        // Le canal ADRASEC est déjà sur la radio, mis à la main : rien, même si la version diffère.
        assertEquals(emptyList(), PlanCanauxEquipes.actions(listOf(adrasec), mapOf("adra42" to 3), emptyMap()))
    }

    @Test fun cleRegenereeReecriteSurPlace() {
        assertEquals(listOf(Action.Reecrire(2, alpha)),
            PlanCanauxEquipes.actions(listOf(alpha), mapOf("ac-alpha" to 2), mapOf("ac-alpha" to "v0")))
        assertEquals(emptyList(), PlanCanauxEquipes.actions(listOf(alpha), mapOf("ac-alpha" to 2), mapOf("ac-alpha" to "v1")))
    }

    @Test fun equipeQuitteeRetireSeulementCeQuOnAInstalle() {
        val actions = PlanCanauxEquipes.actions(emptyList(), mapOf("ac-bravo" to 4, "perso" to 5), mapOf("ac-bravo" to "v1"))
        assertEquals(listOf(Action.Retirer(4, "ac-bravo")), actions)
    }

    @Test fun indicatifChangeAncienRetireNouveauAjoute() {
        val actions = PlanCanauxEquipes.actions(listOf(alpha), mapOf("ac-alph" to 1), mapOf("ac-alph" to "v1"))
        assertEquals(listOf(Action.Ajouter(alpha), Action.Retirer(1, "ac-alph")), actions)
    }
}
