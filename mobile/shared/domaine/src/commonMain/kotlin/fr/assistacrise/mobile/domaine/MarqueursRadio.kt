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
 * Routes (27/11/2026, décision de Sylvain) : cinq états d'un même marqueur. L'émoji porte la
 * famille et la précision de sens ouvre la note, le texte reste du SAR pur :
 * « S:⛔:0:44.85000,-0.57000:1 sens · arbre en travers ».
 * ⛔ coupée (2 sens / 1 sens), 🚧 1 file fermée (1 sens / 2 sens), ✅ axe libéré. Un état plus
 * récent, à moins de 30 m, remplace l'ancien. Mêmes règles au serveur (core/marqueurs_terrain.py).
 *
 * « Secours à personne » (🆘) remplace « personne trouvée » et « blessé » ; 🧑, 👤 et 🚑 reçus
 * d'autres applications sont lus ainsi.
 */
object MarqueursRadio {
    /** Un genre qu'on pose ; `precision` : le sens, pour une route. */
    data class Genre(val emoji: String, val libelle: String, val precision: String = "")

    /** Les cinq états d'une route : code serveur, émoji, précision de sens, libellé. */
    data class EtatRoute(val code: String, val emoji: String, val precision: String, val libelle: String)
    val ETATS_ROUTE = listOf(
        EtatRoute("ROUTE_COUPEE_2S", "⛔", "2 sens", "Coupée dans les 2 sens"),
        EtatRoute("ROUTE_COUPEE_1S", "⛔", "1 sens", "Coupée dans 1 sens"),
        EtatRoute("ROUTE_FILE_1S", "🚧", "1 file, 1 sens", "1 file fermée dans 1 sens"),
        EtatRoute("ROUTE_FILE_2S", "🚧", "1 file, 2 sens", "1 file fermée dans les 2 sens"),
        EtatRoute("ROUTE_LIBEREE", "✅", "", "Axe libéré"),
    )
    fun estRoute(emoji: String) = emoji == "⛔" || emoji == "🚧" || emoji == "✅"

    /** Ceux qu'on propose : secours, feu, inondation, une route dans l'un de ses états, puis les autres. */
    val GENRES = listOf(Genre("🆘", "Secours à personne"), Genre("🔥", "Feu"), Genre("🌊", "Inondation")) +
        ETATS_ROUTE.filter { it.precision.isNotEmpty() }.map { Genre(it.emoji, "Route : " + it.libelle.lowercase(), it.precision) } +
        listOf(Genre("⚠️", "Danger"), Genre("🏕️", "Zone de regroupement"), Genre("📦", "Objet"),
               // Information (26/11/2026) : aussi un signalement « Information utile » du public.
               Genre("ℹ️", "Information"))

    private val PRECISIONS = ETATS_ROUTE.map { it.precision }.filter { it.isNotEmpty() }.sortedByDescending { it.length }

    /** (précision de sens en tête de la note, reste de la note). */
    fun precisionEtNote(note: String?): Pair<String, String> {
        val t = note?.trim().orEmpty()
        val bas = t.lowercase()
        for (p in PRECISIONS) {
            if (bas == p) return p to ""
            if (bas.startsWith(p) && bas[p.length] in " ·-:") return p to t.substring(p.length).trim(' ', '·', '-', ':')
        }
        return "" to t
    }

    /** La note d'un état de route : sa précision, puis la note libre. */
    fun noteDeRoute(precision: String, libre: String?): String? {
        val l = libre?.trim().orEmpty()
        return when {
            precision.isNotEmpty() && l.isNotEmpty() -> "$precision · $l"
            precision.isNotEmpty() -> precision
            else -> l.ifEmpty { null }
        }
    }

    /** L'état d'une route, s'il est précisé (les marqueurs d'avant le 27/11/2026 ne le sont pas). */
    fun etatDe(m: Marqueur): EtatRoute? {
        if (!estRoute(m.emoji)) return null
        val p = precisionEtNote(m.note).first
        return ETATS_ROUTE.firstOrNull { it.emoji == m.emoji && it.precision == p }
    }

    /** Le libellé complet d'un marqueur : « Route coupée dans 1 sens », « Secours à personne »… */
    fun libelleDe(m: Marqueur): String = when {
        estRoute(m.emoji) -> etatDe(m)?.let { if (it.code == "ROUTE_LIBEREE") "Route : axe libéré" else "Route " + it.libelle.replaceFirstChar { c -> c.lowercase() } }
            ?: if (m.emoji == "⛔") "Route coupée, sens non précisé" else "1 file fermée, sens non précisé"
        else -> libelle(m.emoji)
    }

    /** La note sans la précision de sens. */
    fun noteLibre(m: Marqueur): String? = precisionEtNote(m.note).second.ifEmpty { null }

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

    fun libelle(emoji: String): String = GENRES.firstOrNull { it.emoji == emoji && it.precision.isEmpty() }?.libelle
        ?: when (emoji) {
            "🧑", "👤", "🚑" -> "Secours à personne"; "⛺" -> "Zone de regroupement"; "ℹ" -> "Information"
            "⛔" -> "Route coupée"; "🚧" -> "1 file fermée"; "✅" -> "Route : axe libéré"; else -> "Marqueur"
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

    /** Quelques mots seulement par radio (Sylvain, 27/11/2026 : « ne sois pas aussi précis en mesh
     * qu'en data ») ; la note entière part au central par le réseau. Même règle au serveur. */
    const val NOTE_RADIO_MAX = 30

    /** Le texte radio : émoji, position, sens d'une route, et au plus NOTE_RADIO_MAX caractères de note. */
    fun ecrirePourLaRadio(m: Marqueur): String {
        val (precision, libre) = precisionEtNote(m.note?.replace('\n', ' '))
        val court = if (libre.length > NOTE_RADIO_MAX) libre.take(NOTE_RADIO_MAX - 1).trimEnd() + "…" else libre
        return ecrire(m.copy(note = noteDeRoute(precision, court)))
    }

    /** « 44.84000 », sans dépendre de la langue du téléphone (virgule décimale en français). */
    internal fun cinqDecimales(v: Double): String {
        val n = (abs(v) * 100_000).roundToLong()
        return (if (v < 0 && n != 0L) "-" else "") + "${n / 100_000}." + (n % 100_000).toString().padStart(5, '0')
    }
}
