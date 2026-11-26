package fr.assistacrise.mobile.domaine

/**
 * Réactions émoji sur la radio MeshCore (26/11/2026). Le protocole n'en prévoit pas : les
 * applications les écrivent dans un message texte ordinaire, en désignant le message visé par
 * une empreinte. Deux formats circulent, on lit les deux et on écrit le plus répandu :
 *
 * - **MeshCoreOne** (documenté, docs/Reactions.md ; lu aussi par meshcore-open) — c'est celui
 *   qu'on envoie. Canal : `@[Auteur visé]👍\n<empreinte>` ; direct : `👍\n<empreinte>`.
 *   Empreinte : SHA-256(texte UTF-8 + heure d'émission en UInt32 petit-boutiste), 5 premiers
 *   octets, en base 32 de Crockford, minuscules (8 caractères). Le texte est celui du message
 *   sans le « Nom: » que la radio ajoute sur un canal ; l'heure est celle de l'émetteur, portée
 *   par la trame. L'ancien ordre (`👍@[Auteur]\n…`) est encore accepté en lecture.
 * - **meshcore-open** : `r:<empreinte 4 hex>:<rang 2 hex>`, le rang désignant l'émoji dans sa
 *   liste (recopiée ici dans le même ordre, licence MIT) ; empreinte : hachage « Dart » de
 *   heure + nom de l'auteur (canal seulement) + 5 premiers caractères du texte, 16 bits bas.
 *
 * En Meshtastic, une réaction est native (champ `emoji` + `reply_id`) : rien de tout ceci.
 */
object ReactionsRadio {
    /** Ceux qu'on propose d'un geste : les six premiers de la liste de meshcore-open. */
    val RAPIDES = listOf("👍", "❤️", "😂", "🎉", "👏", "🔥")

    enum class Format { MC1, OPEN }

    /** Une réaction lue : l'émoji, l'empreinte du message visé et, sur un canal (MC1), son auteur. */
    data class Lue(val emoji: String, val empreinte: String, val format: Format, val auteurVise: String? = null)

    private const val CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"

    fun empreinteMc1(texte: String, horodatageS: Long): String {
        val h = sha256(texte.encodeToByteArray() + ByteArray(4) { i -> (horodatageS ushr (8 * i)).toByte() })
        var n = 0L
        for (i in 0 until 5) n = (n shl 8) or (h[i].toLong() and 0xff)
        return (0 until 8).map { CROCKFORD[((n ushr (35 - 5 * it)) and 31).toInt()] }.joinToString("")
    }

    /** Le hachage de chaîne de la machine virtuelle Dart (unités UTF-16, 30 bits), que
     * meshcore-open utilise pour ses empreintes. */
    internal fun hachageDart(texte: String): Long {
        val m = 0xffffffffL
        var h = 0L
        for (c in texte) {
            h = (h + c.code) and m
            h = (h + ((h shl 10) and m)) and m
            h = h xor (h ushr 6)
        }
        h = (h + ((h shl 3) and m)) and m
        h = h xor (h ushr 11)
        h = (h + ((h shl 15) and m)) and m
        h = h and 0x3fffffff
        return if (h == 0L) 1 else h
    }

    fun empreinteOpen(horodatageS: Long, auteur: String?, texte: String): String =
        (hachageDart("$horodatageS${auteur ?: ""}${texte.take(5)}") and 0xffff).toString(16).padStart(4, '0')

    /** Ce qu'on envoie pour réagir (format MeshCoreOne). `auteurVise` : sur un canal, l'auteur du
     * message visé ; null en message direct. */
    fun ecrire(emoji: String, texteVise: String, horodatageVise: Long, auteurVise: String?): String {
        val e = empreinteMc1(texteVise, horodatageVise)
        return if (auteurVise.isNullOrBlank()) "$emoji\n$e" else "@[$auteurVise]$emoji\n$e"
    }

    private val MC1 = Regex("""^(?:@\[(.*)])?(.+?)\n([a-tv-zA-TV-Z0-9]{8})$""")
    private val MC1_ANCIEN = Regex("""^(.+?)(?:@\[(.*)])?\n([a-tv-zA-TV-Z0-9]{8})$""")
    private val OPEN = Regex("""^r:([0-9a-f]{4}):([0-9a-f]{2})$""")

    fun lire(texte: String): Lue? {
        OPEN.find(texte)?.let { m ->
            val emoji = LISTE_OPEN.getOrNull(m.groupValues[2].toInt(16)) ?: return null
            return Lue(emoji, m.groupValues[1], Format.OPEN)
        }
        MC1.find(texte)?.let { m ->
            if (resembleUnEmoji(m.groupValues[2])) return Lue(m.groupValues[2], m.groupValues[3].lowercase(), Format.MC1, m.groupValues[1].ifEmpty { null })
        }
        MC1_ANCIEN.find(texte)?.let { m ->
            if (resembleUnEmoji(m.groupValues[1])) return Lue(m.groupValues[1], m.groupValues[3].lowercase(), Format.MC1, m.groupValues[2].ifEmpty { null })
        }
        return null
    }

    /** La réaction vise-t-elle ce message ? `auteur` : son auteur sur un canal, null en direct. */
    fun vise(r: Lue, texte: String, horodatageS: Long, auteur: String?): Boolean = when (r.format) {
        Format.MC1 -> r.empreinte == empreinteMc1(texte, horodatageS) && (r.auteurVise ?: "") == (auteur ?: "")
        Format.OPEN -> r.empreinte == empreinteOpen(horodatageS, auteur, texte)
    }

    /** Un seul émoji, pas de la prose (même test que meshcore-open et MeshTrax). */
    private fun resembleUnEmoji(s: String): Boolean {
        if (s.isEmpty() || s.length > 16 || s.any { it.isWhitespace() }) return false
        val premier = if (s[0].isHighSurrogate() && s.length > 1) (((s[0].code - 0xd800) shl 10) + (s[1].code - 0xdc00) + 0x10000) else s[0].code
        return premier >= 0x2000 || s.any { it.code == 0xfe0f || it.code == 0x20e3 }
    }

    /** La liste de meshcore-open, dans son ordre : le rang 0x00 est 👍, 0x01 ❤️… */
    private val LISTE_OPEN = listOf(
        "👍", "❤️", "😂", "🎉", "👏", "🔥", "😀", "😃", "😄", "😁", "😅", "😂",
        "🤣", "😊", "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙",
        "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎", "🥸", "🤩",
        "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁", "😣", "😖", "😫", "😩",
        "🥺", "😢", "😭", "😤", "😠", "😡", "🤬", "🤯", "😳", "🥵", "🥶", "😱",
        "😨", "😰", "😥", "😓", "🤗", "🤔", "🤭", "🤫", "🤥", "😶", "👍", "👎",
        "👊", "✊", "🤛", "🤜", "🤞", "✌️", "🤟", "🤘", "👌", "🤌", "🤏", "👈",
        "👉", "👆", "👇", "☝️", "👋", "🤚", "🖐️", "✋", "🖖", "👏", "🙌", "👐",
        "🤲", "🤝", "🙏", "✍️", "💅", "🤳", "💪", "❤️", "🧡", "💛", "💚", "💙",
        "💜", "🖤", "🤍", "🤎", "💔", "❤️‍🔥", "❤️‍🩹", "💕", "💞", "💓", "💗", "💖",
        "💘", "💝", "💟", "💌", "💢", "💥", "💫", "💦", "💨", "🕳️", "💬", "👁️‍🗨️",
        "🗨️", "🗯️", "💭", "🎉", "🎊", "🎈", "🎁", "🎀", "🪅", "🪆", "🏆", "🥇",
        "🥈", "🥉", "⚽", "⚾", "🥎", "🏀", "🏐", "🏈", "🏉", "🎾", "🥏", "🎳",
        "🏏", "🏑", "🏒", "🥍", "🏓", "🏸", "🥊", "🥋", "🥅", "⛳", "🔥", "⭐",
        "🌟", "✨", "⚡", "💡", "🔦", "🏮", "🪔", "📱", "💻", "⌚", "📷", "📺",
        "📻", "🎵", "🎶", "🚀",
    )
}
