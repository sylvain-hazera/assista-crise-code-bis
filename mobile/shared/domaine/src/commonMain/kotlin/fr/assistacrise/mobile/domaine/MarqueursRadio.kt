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
 *
 * Le marqueur peut suivre un ou deux préfixes « Nom: » (27/11/2026) : la radio MeshCore ajoute le
 * nom de l'émetteur, et le relais Meshtastic ↔ MeshCore du canal de crise y ajoute l'auteur.
 *
 * Routes (27/11/2026) : trois émojis, trois états d'un même marqueur — ⛔ coupée totalement,
 * 🚧 une voie libérée, ✅ axe libéré. Un état plus récent, à moins de 30 m, remplace l'ancien.
 * Même règle au serveur (backend/core/marqueurs_terrain.py).
 */
object MarqueursRadio {
    data class Genre(val emoji: String, val libelle: String)

    /** Les quatre de MeshCore SAR d'abord (ils y ont une icône), puis ceux d'une crise chez nous. */
    val GENRES = listOf(
        Genre("🧑", "Personne trouvée"), Genre("🔥", "Feu"), Genre("🏕️", "Zone de regroupement"), Genre("📦", "Objet"),
        Genre("🌊", "Inondation"), Genre("⛔", "Route coupée totalement"), Genre("🚑", "Blessé"), Genre("⚠️", "Danger"),
    )

    /** Les trois états d'une route : (code serveur, émoji, libellé). */
    data class EtatRoute(val code: String, val emoji: String, val libelle: String)
    val ETATS_ROUTE = listOf(
        EtatRoute("ROUTE_COUPEE", "⛔", "Coupée totalement"),
        EtatRoute("ROUTE_UNE_VOIE", "🚧", "Une voie libérée"),
        EtatRoute("ROUTE_LIBEREE", "✅", "Axe libéré"),
    )
    fun estRoute(emoji: String) = ETATS_ROUTE.any { it.emoji == emoji }

    /** Rayon où un nouvel état de route remplace l'ancien ; rayon d'un même marqueur réentendu. */
    const val RAYON_ROUTE_M = 30.0
    const val RAYON_DOUBLON_M = 5.0

    fun distanceM(a: Marqueur, b: Marqueur): Double =
        Releve(a.latitude, a.longitude, 0).distanceA(Releve(b.latitude, b.longitude, 0))

    /**
     * Ce que la carte montre d'une liste de marqueurs datés, quelle que soit leur origine (radio,
     * serveur) : un même marqueur entendu deux fois n'en fait qu'un, et une route ne garde que son
     * dernier état. `liste` : du plus récent au plus ancien.
     */
    fun <T> pourLaCarte(liste: List<T>, marqueur: (T) -> Marqueur): List<T> {
        val gardes = mutableListOf<T>()
        for (x in liste) {
            val m = marqueur(x)
            val masque = gardes.any { g ->
                val n = marqueur(g)
                (n.emoji == m.emoji && distanceM(n, m) <= RAYON_DOUBLON_M) ||
                    (estRoute(n.emoji) && estRoute(m.emoji) && distanceM(n, m) <= RAYON_ROUTE_M)
            }
            if (!masque) gardes += x
        }
        return gardes
    }

    fun libelle(emoji: String): String = GENRES.firstOrNull { it.emoji == emoji }?.libelle
        ?: when (emoji) {
            "👤" -> "Personne trouvée"; "⛺" -> "Zone de regroupement"
            "🚧" -> "Route : une voie libérée"; "✅" -> "Route : axe libéré"; else -> "Marqueur"
        }

    data class Marqueur(val emoji: String, val latitude: Double, val longitude: Double, val note: String? = null, val couleur: Int = 0)

    private val NOUVEAU = Regex("""^S:([^:]+):(\d):(-?\d+\.?\d*),(-?\d+\.?\d*):?(.*)$""")
    private val ANCIEN = Regex("""^S:([^:]+):(-?\d+\.?\d*),(-?\d+\.?\d*):?(.*)$""")

    private val PREFIXE = Regex("""^[^:\n]{1,40}: """)

    fun lire(texte: String): Marqueur? {
        var t = texte.trim()
        // Un ou deux « Nom: » devant (radio MeshCore, relais du canal de crise).
        repeat(2) { if (!t.startsWith("S:")) PREFIXE.find(t)?.let { t = t.substring(it.range.last + 1).trimStart() } }
        val lignes = t.lines()
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
