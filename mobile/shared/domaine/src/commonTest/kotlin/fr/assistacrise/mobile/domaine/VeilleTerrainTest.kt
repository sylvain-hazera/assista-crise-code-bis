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
    fun lesStationsSeLisentEnUneLigne() {
        val v = json.decodeFromString(VeilleTerrain.serializer(), """{"zones":[],"stations":{"autour_de":"votre position","resultats":[
            {"distance_km":1.2,"adresse":"12 route de Lyon","ville":"Firminy","carburants_disponibles":["Gazole","SP95"],
             "ruptures_temporaires":["E10"],"automate_24_24":true},
            {"distance_km":3.0,"adresse":"","ville":"Unieux","carburants_disponibles":[],"ruptures_temporaires":["Gazole"]}]}}""")
        assertEquals("votre position", v.stations.autourDe)
        val (a, b) = v.stations.resultats
        assertEquals("1,2 km · 12 route de Lyon, Firminy", a.titre)
        assertEquals("Gazole, SP95 · manque : E10 · automate 24/24", a.etat)
        assertEquals("plus rien à délivrer · manque : Gazole", b.etat)
        assertTrue(b.enRupture)
    }

    @Test
    fun rienOuAucuneZone() {
        assertEquals("Veille : aucune crise ni manifestation en cours", VeilleTerrain().resume())
        val calme = VeilleTerrain(zones = listOf(ZoneVeille(rubriques = listOf(RubriqueVeille("SEISMES", "Séismes",
            evenements = listOf(EvenementVeille(titre = "Petit séisme")))))))
        assertEquals("Veille : rien d'important à signaler", calme.resume())
    }
}
