package fr.assistacrise.mobile.domaine

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class MiseAJourTest {
    private val json = Json { ignoreUnknownKeys = true }
    private val site = "https://www.assista-crise.fr"
    private val apps = mapOf("assista-crise" to "assista-crise.apk", "reserve-resilience" to "reserve-resilience.apk")

    @Test fun leFichierPublieSeLitMemeAncien() {
        // Tel que publié le 16/11/2026, sans numéro : on ne propose rien.
        val ancien = json.decodeFromString(VersionPubliee.serializer(),
            """{"version": "0.9.0", "fichier": "reserve-resilience.apk", "applications": {"assista-crise": "assista-crise.apk"}}""")
        assertNull(MisesAJour.aProposer(ancien, 13, "assista-crise", site, null, 0))
        val nouveau = json.decodeFromString(VersionPubliee.serializer(),
            """{"version": "0.10.0", "code": 14, "minimum": 0, "applications": {"assista-crise": "assista-crise.apk"}}""")
        assertEquals(MiseAJourProposee(UrgenceMiseAJour.CONSEILLEE, "0.10.0", "$site/mobile/assista-crise.apk"),
            MisesAJour.aProposer(nouveau, 13, "assista-crise", site, null, 0))
    }

    @Test fun conseilleeOuObligatoireSelonLeMinimum() {
        assertEquals(UrgenceMiseAJour.AUCUNE, MisesAJour.urgence(VersionPubliee("0.10.0", 14), 14))
        assertEquals(UrgenceMiseAJour.CONSEILLEE, MisesAJour.urgence(VersionPubliee("0.10.0", 14, minimum = 10), 13))
        assertEquals(UrgenceMiseAJour.OBLIGATOIRE, MisesAJour.urgence(VersionPubliee("0.10.0", 14, minimum = 14), 13))
    }

    @Test fun plusTardAttendUnJourOuUneHeure() {
        val conseillee = VersionPubliee("0.10.0", 14, applications = apps)
        val heure = 3600_000L
        assertNull(MisesAJour.aProposer(conseillee, 13, "assista-crise", site, reporteeLe = 0, maintenant = 23 * heure))
        assertEquals("0.10.0", MisesAJour.aProposer(conseillee, 13, "assista-crise", site, 0, 25 * heure)?.versionPubliee)
        val obligatoire = conseillee.copy(minimum = 14)
        assertNull(MisesAJour.aProposer(obligatoire, 13, "assista-crise", site, 0, heure / 2))
        assertEquals(UrgenceMiseAJour.OBLIGATOIRE, MisesAJour.aProposer(obligatoire, 13, "assista-crise", site, 0, 2 * heure)?.urgence)
    }

    @Test fun chaqueMarqueRecoitSonApplication() {
        val publiee = VersionPubliee("0.10.0", 14, applications = apps)
        assertEquals("https://app.reserve-resilience.org/mobile/reserve-resilience.apk",
            MisesAJour.aProposer(publiee, 13, "reserve-resilience", "https://app.reserve-resilience.org/", null, 0)?.adresse)
    }

    @Test fun unNomDeFichierDouteuxNEstJamaisPropose() {
        val piege = VersionPubliee("0.10.0", 14, applications = mapOf("assista-crise" to "../../ailleurs.apk"))
        assertNull(MisesAJour.aProposer(piege, 13, "assista-crise", site, null, 0))
        assertNull(MisesAJour.aProposer(VersionPubliee("0.10.0", 14, applications = mapOf("assista-crise" to "https://x/y.apk")),
            13, "assista-crise", site, null, 0))
    }
}
