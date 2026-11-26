package fr.assistacrise.mobile.domaine

import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * Marqueurs d'incident par la radio (26/11/2026), lisibles par MeshCore SAR et réciproquement.
 * Un marqueur est un message texte ordinaire, sur un canal ou en direct :
 *
 *     S:<émoji>:<couleur>:<latitude>,<longitude>:<note>
 *
 * `couleur` est un chiffre (0 par défaut) ; l'ancienne forme, sans couleur, est encore lue. Les
 * lignes suivantes, s'il y en a, complètent la note. Format relevé dans les messages de MeshCore
 * SAR ; le code est écrit ici, rien n'en est repris. Sans application compatible, le message
 * reste lisible tel quel. Il passe aussi sur Meshtastic, comme n'importe quel texte.
 */
object MarqueursRadio {
    data class Genre(val emoji: String, val libelle: String)

    /** Les quatre de MeshCore SAR d'abord (ils y ont une icône), puis ceux d'une crise chez nous. */
    val GENRES = listOf(
        Genre("🧑", "Personne trouvée"), Genre("🔥", "Feu"), Genre("🏕️", "Zone de regroupement"), Genre("📦", "Objet"),
        Genre("🌊", "Inondation"), Genre("🚧", "Route coupée"), Genre("🚑", "Blessé"), Genre("⚠️", "Danger"),
    )

    fun libelle(emoji: String): String = GENRES.firstOrNull { it.emoji == emoji }?.libelle
        ?: when (emoji) { "👤" -> "Personne trouvée"; "⛺" -> "Zone de regroupement"; else -> "Marqueur" }

    data class Marqueur(val emoji: String, val latitude: Double, val longitude: Double, val note: String? = null, val couleur: Int = 0)

    private val NOUVEAU = Regex("""^S:([^:]+):(\d):(-?\d+\.?\d*),(-?\d+\.?\d*):?(.*)$""")
    private val ANCIEN = Regex("""^S:([^:]+):(-?\d+\.?\d*),(-?\d+\.?\d*):?(.*)$""")

    fun lire(texte: String): Marqueur? {
        val lignes = texte.trim().lines()
        val premiere = lignes.firstOrNull() ?: return null
        if (!premiere.startsWith("S:")) return null
        val n = NOUVEAU.find(premiere)
        val m = n ?: ANCIEN.find(premiere) ?: return null
        val g = m.groupValues
        val emoji = g[1].trim().ifEmpty { return null }
        val decalage = if (n != null) 1 else 0
        val lat = g[2 + decalage].toDoubleOrNull() ?: return null
        val lon = g[3 + decalage].toDoubleOrNull() ?: return null
        if (lat !in -90.0..90.0 || lon !in -180.0..180.0) return null
        val note = (listOf(g[4 + decalage].trim()) + lignes.drop(1).map { it.trim() }).filter { it.isNotEmpty() }.joinToString("\n").ifEmpty { null }
        return Marqueur(emoji, lat, lon, note, if (n != null) g[2].toInt() else 0)
    }

    /** Le texte à envoyer. Cinq décimales : environ un mètre, et le message reste court. Les « : »
     * de la note sont gardés (seuls les quatre premiers champs sont découpés). */
    fun ecrire(m: Marqueur): String {
        val base = "S:${m.emoji}:${m.couleur.coerceIn(0, 9)}:${cinqDecimales(m.latitude)},${cinqDecimales(m.longitude)}"
        val note = m.note?.replace('\n', ' ')?.trim().orEmpty()
        return if (note.isEmpty()) base else "$base:$note"
    }

    /** « 44.84000 », sans dépendre de la langue du téléphone (virgule décimale en français). */
    internal fun cinqDecimales(v: Double): String {
        val n = (abs(v) * 100_000).roundToLong()
        return (if (v < 0 && n != 0L) "-" else "") + "${n / 100_000}." + (n % 100_000).toString().padStart(5, '0')
    }
}
