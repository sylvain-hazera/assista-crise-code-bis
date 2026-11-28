package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Le périmètre de la carte (27/11/2026, `carte-terrain/perimetre/`) : la crise en cours de mes
 * équipes (« engagement »), sinon les crises de ma commune (« commune »), sinon rien. */
@Serializable
data class PerimetreCarte(val raison: String = "aucune", val crises: List<CrisePerimetre> = emptyList())

@Serializable
data class CrisePerimetre(
    val id: String,
    val nom: String = "",
    val latitude: Double? = null,
    val longitude: Double? = null,
    /** La zone effective de la crise (GeoJSON) : le contour dessiné, sinon les communes ou
     * départements tamponnés (28/11/2026). Absente : seule la règle du rayon s'applique. */
    val zone: kotlinx.serialization.json.JsonElement? = null,
    @SerialName("rayon_km") val rayonKm: Double = 10.0,
) {
    /** Ce point est-il dans la zone de la crise ? (même règle que backend/core/zones_marqueurs.py) */
    fun contient(latitude: Double, longitude: Double): Boolean {
        zone?.let { return ZoneMarquage.dansGeoJson(it, latitude, longitude) }
        val la = this.latitude ?: return false
        val lo = this.longitude ?: return false
        return ZoneMarquage.distanceKm(latitude, longitude, la, lo) <= rayonKm
    }

    /** Les sommets du contour (latitude, longitude), sinon le centre. */
    fun points(): List<Pair<Double, Double>> {
        val z = zone?.toString()
        val sommets = z?.let { Regex("""\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*]""").findAll(it)
            .map { m -> m.groupValues[2].toDouble() to m.groupValues[1].toDouble() }.toList() }.orEmpty()
        return sommets.ifEmpty { listOfNotNull(if (latitude != null && longitude != null) latitude to longitude else null) }
    }
}

/** Un marqueur terrain tel que le serveur le garde (27/11/2026, `marqueurs-terrain/`) : arrivé par
 * une passerelle radio, l'application ou le site, sur une crise ou une manifestation. */
@Serializable
data class MarqueurCentral(
    val id: String,
    val crise: String? = null,
    val manifestation: String? = null,
    val emoji: String,
    val genre: String = "",
    val libelle: String = "",
    val route: Boolean = false,
    val latitude: Double,
    val longitude: Double,
    val note: String = "",
    @SerialName("auteur_nom") val auteur: String = "",
    @SerialName("source_libelle") val source: String = "",
    @SerialName("cree_le") val creeLe: String = "",
    @SerialName("decision_libelle") val decision: String = "",
) {
    val marqueur: MarqueursRadio.Marqueur get() = MarqueursRadio.Marqueur(emoji, latitude, longitude, note.ifBlank { null })
}


/** Ce à quoi un marqueur posé est rattaché : une crise ouverte OU une manifestation en cours. */
data class Rattachement(val crise: String? = null, val manifestation: String? = null, val nom: String = "") {
    val cle: String get() = crise?.let { "c:$it" } ?: "m:$manifestation"
}


/**
 * Où un marqueur peut se poser depuis l'application (28/11/2026, décision de Sylvain) : dans la
 * zone d'une crise ouverte ou près d'une manifestation en cours. Même calcul que le serveur
 * (backend/core/zones_marqueurs.py), qui refuse aussi un point hors zone.
 */
object ZoneMarquage {
    fun distanceKm(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6371.0
        val p1 = lat1 * kotlin.math.PI / 180; val p2 = lat2 * kotlin.math.PI / 180
        val dp = p2 - p1; val dl = (lon2 - lon1) * kotlin.math.PI / 180
        val a = kotlin.math.sin(dp / 2).let { it * it } + kotlin.math.cos(p1) * kotlin.math.cos(p2) * kotlin.math.sin(dl / 2).let { it * it }
        return 2 * r * kotlin.math.asin(kotlin.math.sqrt(a))
    }

    /** Le point est-il dans un Polygon ou un MultiPolygon GeoJSON (trous compris) ? */
    fun dansGeoJson(geo: kotlinx.serialization.json.JsonElement, latitude: Double, longitude: Double): Boolean {
        val o = geo as? kotlinx.serialization.json.JsonObject ?: return false
        val type = (o["type"] as? kotlinx.serialization.json.JsonPrimitive)?.content
        val coords = o["coordinates"] as? kotlinx.serialization.json.JsonArray ?: return false
        val polygones = when (type) {
            "Polygon" -> listOf(coords)
            "MultiPolygon" -> coords.mapNotNull { it as? kotlinx.serialization.json.JsonArray }
            else -> return false
        }
        return polygones.any { dansPolygone(it, latitude, longitude) }
    }

    private fun anneau(e: kotlinx.serialization.json.JsonElement): List<Pair<Double, Double>> =
        (e as? kotlinx.serialization.json.JsonArray).orEmpty().mapNotNull { p ->
            val a = p as? kotlinx.serialization.json.JsonArray ?: return@mapNotNull null
            val lon = (a.getOrNull(0) as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull()
            val lat = (a.getOrNull(1) as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull()
            if (lon != null && lat != null) lon to lat else null
        }

    private fun dansPolygone(anneaux: kotlinx.serialization.json.JsonArray, latitude: Double, longitude: Double): Boolean {
        val exterieur = anneaux.firstOrNull()?.let(::anneau) ?: return false
        if (!dansAnneau(exterieur, latitude, longitude)) return false
        return anneaux.drop(1).none { dansAnneau(anneau(it), latitude, longitude) }
    }

    /** Lancer de rayon, en (longitude, latitude). */
    internal fun dansAnneau(points: List<Pair<Double, Double>>, latitude: Double, longitude: Double): Boolean {
        var dedans = false
        var j = points.size - 1
        for (i in points.indices) {
            val (xi, yi) = points[i]; val (xj, yj) = points[j]
            if ((yi > latitude) != (yj > latitude) && longitude < (xj - xi) * (latitude - yi) / (yj - yi) + xi) dedans = !dedans
            j = i
        }
        return dedans
    }
}
