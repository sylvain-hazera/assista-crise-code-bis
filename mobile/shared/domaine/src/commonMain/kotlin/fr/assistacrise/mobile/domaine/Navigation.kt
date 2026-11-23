package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/** Un point important de la crise (lieu d'accueil, PC, point de rassemblement…), embarqué. */
@Serializable
data class PointCrise(
    val id: String,
    val nom: String = "",
    @SerialName("type_libelle") val type: String? = null,
    val adresse: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val crise: String? = null,
) {
    val situe: Boolean get() = latitude != null && longitude != null
}

/** Une destination de « Aller vers » : un point, un dossier, un membre. */
data class Destination(val nom: String, val latitude: Double, val longitude: Double, val genre: String, val dossier: String? = null)

/**
 * « Aller vers un point », sans itinéraire (22/11/2026) : distance et cap à vol d'oiseau, et
 * le sens de la flèche une fois l'orientation du téléphone connue.
 */
object Navigation {
    private const val RAYON_TERRE_M = 6_371_000.0
    /** En deçà, on est arrivé : l'application propose « Arrivé sur les lieux ». */
    const val SEUIL_ARRIVEE_M = 30.0

    fun distanceM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val p1 = rad(lat1); val p2 = rad(lat2)
        val dp = rad(lat2 - lat1); val dl = rad(lon2 - lon1)
        val a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
        return 2 * RAYON_TERRE_M * atan2(sqrt(a), sqrt(1 - a))
    }

    /** Cap vers la destination, en degrés depuis le nord (0 à 360). */
    fun capDeg(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val p1 = rad(lat1); val p2 = rad(lat2); val dl = rad(lon2 - lon1)
        val y = sin(dl) * cos(p2)
        val x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
        return (atan2(y, x) * 180 / PI + 360) % 360
    }

    /** Angle de la flèche à l'écran, une fois connu le cap vers lequel pointe le téléphone. */
    fun angleFleche(capDestination: Double, orientationTelephone: Double): Double =
        ((capDestination - orientationTelephone) % 360 + 360) % 360

    fun distanceLisible(m: Double): String = when {
        m < 1000 -> "${m.roundToInt()} m"
        m < 10_000 -> "${(m / 100).roundToInt() / 10.0} km".replace('.', ',')
        else -> "${(m / 1000).roundToInt()} km"
    }

    fun capLisible(deg: Double): String {
        val points = listOf("N", "NE", "E", "SE", "S", "SO", "O", "NO")
        return "${deg.roundToInt()}° ${points[((deg + 22.5) / 45).toInt() % 8]}"
    }

    /** Les destinations triées par distance (« Autour de moi »). */
    fun autourDe(lat: Double, lon: Double, destinations: List<Destination>): List<Pair<Destination, Double>> =
        destinations.map { it to distanceM(lat, lon, it.latitude, it.longitude) }.sortedBy { it.second }

    private fun rad(d: Double) = d * PI / 180
}

/** Estimation d'une région de carte embarquée : nombre de tuiles et taille (raster IGN). */
object CartesEmbarquees {
    /** Taille moyenne constatée d'une tuile IGN Plan raster (PNG 256 px). */
    const val OCTETS_PAR_TUILE = 18_000L

    fun tuiles(sud: Double, ouest: Double, nord: Double, est: Double, zoomMin: Int, zoomMax: Int): Long {
        var total = 0L
        for (z in zoomMin..zoomMax) {
            val n = 1 shl z
            val x1 = lonVersX(ouest, n); val x2 = lonVersX(est, n)
            val y1 = latVersY(nord, n); val y2 = latVersY(sud, n)
            total += (x2 - x1 + 1).toLong() * (y2 - y1 + 1).toLong()
        }
        return total
    }

    fun tailleLisible(octets: Long): String = when {
        octets < 1_000_000 -> "${octets / 1000} Ko"
        octets < 1_000_000_000 -> "${octets / 1_000_000} Mo"
        else -> "${(octets / 100_000_000) / 10.0} Go".replace('.', ',')
    }

    private fun lonVersX(lon: Double, n: Int) = ((lon + 180) / 360 * n).toInt().coerceIn(0, n - 1)
    private fun latVersY(lat: Double, n: Int): Int {
        val r = lat * PI / 180
        return ((1 - kotlin.math.ln(kotlin.math.tan(r) + 1 / cos(r)) / PI) / 2 * n).toInt().coerceIn(0, n - 1)
    }
}
