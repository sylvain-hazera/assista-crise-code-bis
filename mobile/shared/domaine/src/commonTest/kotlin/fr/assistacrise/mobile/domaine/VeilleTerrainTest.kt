package fr.assistacrise.mobile.domaine

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class VeilleTerrainTest {
    private val json = Json { ignoreUnknownKeys = true }

    /** La réponse telle que le serveur la rend (core/tests/test_veille_terrain.py). */
    private val reponse = """{"genere_le":"2026-11-27T22:00:00Z","zones":[
        {"nature":"crise","id":"c1","nom":"Orages (essai)","communes":1,"rubriques":[
          {"code":"METEO","libelle":"Vigilance météo","etat":"perimee","evenements":[]},
          {"code":"ORAGES","libelle":"Orages, foudre, pluie intense","etat":"ok","evenements":[
            {"niveau":"EXCEPTIONNEL","titre":"Orage en approche de Saint-Étienne","detail":"Notre estimation"},
            {"niveau":"ALERTE","titre":"Orage intense sur Saint-Étienne","detail":""}]},
          {"code":"SEISMES","libelle":"Séismes","etat":"ok","evenements":[{"niveau":"INFO","titre":"Séisme de magnitude 2.4","detail":""}]},
          {"code":"EAU","libelle":"Crues et inondation","etat":"ok","evenements":[{"niveau":"ALERTE","titre":"Vigilance crues orange : Furan","detail":""}]}]}]}"""

    @Test
    fun seLitEtSeResume() {
        val v = json.decodeFromString(VeilleTerrain.serializer(), reponse)
        assertEquals(3, v.alertes)
        assertTrue(v.exceptionnel)
        assertEquals("Veille : 3 alertes (Orages, Crues)", v.resume())
        val meteo = v.zones.single().rubriques.first()
        assertEquals("Pas de donnée récente : la source ne répond plus.", meteo.texteSiVide)
    }

    @Test
    fun rienOuAucuneZone() {
        assertEquals("Veille : aucune crise ni manifestation en cours", VeilleTerrain().resume())
        val calme = VeilleTerrain(zones = listOf(ZoneVeille(rubriques = listOf(RubriqueVeille("SEISMES", "Séismes",
            evenements = listOf(EvenementVeille(titre = "Petit séisme")))))))
        assertEquals("Veille : rien d'important à signaler", calme.resume())
    }
}
