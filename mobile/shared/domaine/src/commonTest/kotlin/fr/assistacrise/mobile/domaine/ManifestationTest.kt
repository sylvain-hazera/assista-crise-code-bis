package fr.assistacrise.mobile.domaine

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ManifestationTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test fun litLaReponseDuServeur() {
        val m = json.decodeFromString(ManifestationAsso.serializer(), """
            {"id":"m1","institution_nom":"Radio-club","type_libelle":"Dispositif de signalisation radio","titre":"Course",
             "debut":"2027-03-01T08:00:00Z","fin":"2027-03-01T12:00:00Z","statut":"PUBLIEE","places":2,"occupes":2,
             "je_suis_inscrit":false,"organise":true,
             "postes":[{"id":"p1","intitule":"Carrefour","debut":"2027-03-01T08:00:00Z","fin":"2027-03-01T12:00:00Z",
                        "places":2,"occupes":2,"attente":1,"mon_statut":"LISTE_ATTENTE","mon_rang_attente":1}]}""")
        val p = m.postes.single()
        assertTrue(p.complet && p.engage)
        assertEquals("Liste d'attente, n° 1", p.etat())
        assertEquals("Complet (2/2), 1 en attente", p.copy(monStatut = null).etat())
    }
}
