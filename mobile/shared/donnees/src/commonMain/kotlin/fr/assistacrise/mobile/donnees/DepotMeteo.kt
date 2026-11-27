package fr.assistacrise.mobile.donnees

import io.ktor.http.encodeURLParameter
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put

/**
 * Couches météo de la carte de l'application (27/11/2026), quand Internet répond : les mêmes
 * données publiques que la carte météo du site, servies par notre serveur — jamais un service
 * extérieur appelé du téléphone.
 *
 * - `PLUIE` : la dernière image du radar (Météo-France) ;
 * - `RAFALES` : les rafales prévues pour le quart d'heure en cours ;
 * - `ORAGES` : contours des cellules orageuses vues par le radar, et le couloir que NOUS
 *   estimons pour l'heure qui vient (une estimation, pas une prévision) ;
 * - `ECLAIRS` : éclairs vus par le satellite MTG sur la dernière heure.
 *
 * Rien n'est gardé pour le hors réseau : une météo périmée n'a pas sa place sur la carte.
 */
class DepotMeteo(
    private val api: ClientApi,
    /** Instant (ms) d'une date ISO du serveur, ou null. */
    private val lireInstant: (String) -> Long?,
    private val maintenant: () -> Long,
) {
    enum class Couche { PLUIE, RAFALES, ORAGES, ECLAIRS }

    /** Une image à poser sur la carte. `coins` : haut-gauche, haut-droite, bas-droite,
     * bas-gauche, en (longitude, latitude). */
    class ImageMeteo(val octets: ByteArray, val coins: List<Pair<Double, Double>>, val heure: String)

    data class Emprise(val ouest: Double, val sud: Double, val est: Double, val nord: Double) {
        val bbox: String get() = listOf(ouest, sud, est, nord).joinToString(",") { ((it * 1000).toLong() / 1000.0).toString() }
        val centreLat: Double get() = (sud + nord) / 2
        val centreLon: Double get() = (ouest + est) / 2

        companion object {
            /** Bornée à ce que le serveur accepte. */
            fun de(ouest: Double, sud: Double, est: Double, nord: Double): Emprise? {
                val o = ouest.coerceIn(-180.0, 180.0); val e = est.coerceIn(-180.0, 180.0)
                val s = sud.coerceIn(-90.0, 90.0); val n = nord.coerceIn(-90.0, 90.0)
                return if (o < e && s < n) Emprise(o, s, e, n) else null
            }
        }
    }

    class Resultat(
        val pluie: ImageMeteo? = null,
        val rafales: ImageMeteo? = null,
        /** GeoJSON (FeatureCollection) des cellules ; `nature` vaut `cellule` ou `couloir`. */
        val orages: String? = null,
        val nombreCellules: Int = 0,
        /** GeoJSON des éclairs ; `age_min` sur chacun. */
        val eclairs: String? = null,
        val nombreEclairs: Int = 0,
        /** Attributions des sources lues, à afficher sous la carte. */
        val sources: List<String> = emptyList(),
        /** Ce qui n'a pas pu être lu, en clair. */
        val manques: List<String> = emptyList(),
        val injoignable: Boolean = false,
    )

    private var pluieGardee: ImageMeteo? = null
    private var rafalesGardees: ImageMeteo? = null

    suspend fun lire(couches: Set<Couche>, emprise: Emprise): Resultat {
        if (couches.isEmpty()) return Resultat()
        val sources = linkedSetOf<String>()
        val manques = mutableListOf<String>()
        var injoignable = false
        fun noter(r: Reponse<*>, quoi: String) {
            if (r is Reponse.Injoignable) injoignable = true
            if (r !is Reponse.Ok) manques += quoi
        }
        fun JsonObject.source() = (this["source"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.let { sources += it }

        var pluie: ImageMeteo? = null
        if (Couche.PLUIE in couches) {
            val r = api.meteo("orages/radar/?lat=${arrondi(emprise.centreLat)}&lon=${arrondi(emprise.centreLon)}")
            val o = (r as? Reponse.Ok)?.valeur as? JsonObject
            if (o == null) noter(r, "pluie du radar") else {
                o.source()
                val heure = o.texte("heure")
                val coins = coins(o["coins"])
                val zone = o.texte("zone") ?: "METROPOLE"
                if (heure != null && coins != null) {
                    pluie = pluieGardee?.takeIf { it.heure == heure }
                        ?: when (val image = api.imageMeteo("orages/radar/image/?heure=${heure.encodeURLParameter()}&zone=${zone.encodeURLParameter()}")) {
                            is Reponse.Ok -> ImageMeteo(image.valeur, coins, heure).also { pluieGardee = it }
                            else -> { noter(image, "image du radar"); null }
                        }
                }
            }
        }

        var rafales: ImageMeteo? = null
        if (Couche.RAFALES in couches) {
            val r = api.meteo("rafales-prevues/")
            val o = (r as? Reponse.Ok)?.valeur as? JsonObject
            if (o == null) noter(r, "rafales prévues") else {
                o.source()
                val echeances = (o["echeances"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.content }.orEmpty()
                val echeance = echeanceEnCours(echeances)
                val coins = coins(o["coins"])
                if (echeance != null && coins != null) {
                    rafales = rafalesGardees?.takeIf { it.heure == echeance }
                        ?: when (val image = api.imageMeteo("rafales-prevues/image/?echeance=${echeance.encodeURLParameter()}")) {
                            is Reponse.Ok -> ImageMeteo(image.valeur, coins, echeance).also { rafalesGardees = it }
                            else -> { noter(image, "image des rafales"); null }
                        }
                }
            }
        }

        var orages: String? = null
        var nombreCellules = 0
        if (Couche.ORAGES in couches) {
            val r = api.meteo("orages/?bbox=${emprise.bbox}")
            val o = (r as? Reponse.Ok)?.valeur as? JsonObject
            if (o == null) noter(r, "orages") else {
                o.source()
                val cellules = (o["cellules"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
                nombreCellules = cellules.size
                orages = geojsonDesOrages(cellules)
            }
        }

        var eclairs: String? = null
        var nombreEclairs = 0
        if (Couche.ECLAIRS in couches) {
            val r = api.meteo("foudre/?bbox=${emprise.bbox}&minutes=60")
            val o = (r as? Reponse.Ok)?.valeur as? JsonObject
            if (o == null) noter(r, "éclairs") else {
                o.source()
                val points = (o["features"] as? JsonArray) ?: JsonArray(emptyList())
                nombreEclairs = points.size
                eclairs = buildJsonObject { put("type", "FeatureCollection"); put("features", points) }.toString()
            }
        }
        return Resultat(pluie, rafales, orages, nombreCellules, eclairs, nombreEclairs, sources.toList(), manques, injoignable)
    }

    /** Le quart d'heure en cours : la première échéance qui n'est pas passée de plus de
     * 7 min 30, sinon la dernière disponible. */
    internal fun echeanceEnCours(echeances: List<String>): String? {
        val t = maintenant()
        return echeances.firstOrNull { e -> lireInstant(e)?.let { it >= t - 450_000 } == true } ?: echeances.lastOrNull()
    }

    private fun arrondi(x: Double) = (kotlin.math.round(x * 1000) / 1000).toString()

    companion object {
        private fun JsonObject.texte(cle: String) = (this[cle] as? JsonPrimitive)?.takeIf { it !is JsonNull && it.isString }?.content

        /** `[[lon, lat] × 4]`, ou null. */
        internal fun coins(e: JsonElement?): List<Pair<Double, Double>>? {
            val liste = (e as? JsonArray)?.mapNotNull { c ->
                val a = c as? JsonArray ?: return@mapNotNull null
                val lon = (a.getOrNull(0) as? JsonPrimitive)?.doubleOrNull
                val lat = (a.getOrNull(1) as? JsonPrimitive)?.doubleOrNull
                if (lon != null && lat != null) lon to lat else null
            }
            return liste?.takeIf { it.size == 4 }
        }

        /** Les contours (relevés du radar) et les couloirs (nos estimations) en un GeoJSON. */
        internal fun geojsonDesOrages(cellules: List<JsonObject>): String = buildJsonObject {
            put("type", "FeatureCollection")
            put("features", buildJsonArray {
                for (c in cellules) {
                    val releves = c["releves"] as? JsonObject
                    val mmh = (releves?.get("intensite_max_mmh") as? JsonPrimitive)?.doubleOrNull ?: 0.0
                    val libelle = (releves?.get("libelle") as? JsonPrimitive)?.content.orEmpty()
                    (c["couloir"] as? JsonObject)?.let { g ->
                        add(buildJsonObject {
                            put("type", "Feature"); put("geometry", g)
                            put("properties", buildJsonObject { put("nature", "couloir") })
                        })
                    }
                    (c["contour"] as? JsonObject)?.let { g ->
                        add(buildJsonObject {
                            put("type", "Feature"); put("geometry", g)
                            put("properties", buildJsonObject { put("nature", "cellule"); put("mmh", mmh); put("libelle", libelle) })
                        })
                    }
                }
            })
        }.toString()
    }
}
