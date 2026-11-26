package fr.assistacrise.mobile.domaine

/**
 * « Il faut une notification particulière si on me tague dans un canal mesh ou une discussion de
 * groupe » (23/11/2026). Une mention, c'est « @ » suivi d'un de mes noms : `@Léa`, `@Léa Martin`,
 * `@[Léa Martin]` (la forme que l'application MeshCore insère), ou le nom court ou long de mon
 * nœud radio. Sans tenir compte des accents ni de la casse ; « @léandre » ne mentionne pas Léa.
 */
object Mentions {
    fun mentionne(texte: String, noms: Collection<String>): Boolean {
        val t = normaliser(texte)
        if ('@' !in t) return false
        return noms.map(::normaliser).filter { it.length >= 2 }.distinct().any { nom ->
            "@[$nom]" in t || Regex("(^|[^\\p{L}\\p{N}_])@" + Regex.escape(nom) + "(?![\\p{L}\\p{N}_])").containsMatchIn(t)
        }
    }

    /** Le tag d'une personne, toujours `@[Nom]` (26/11/2026) : c'est la forme qu'insèrent et
     * reconnaissent l'application MeshCore, meshcore-open et MeshCore SAR (surlignage, notification
     * « on vous mentionne »). `@Léa` sans crochets n'y était pas reconnu. Sur la radio, `Nom` est
     * le nom radio de la personne (nom annoncé MeshCore, nom long Meshtastic). */
    fun etiquette(nom: String): String {
        val propre = nom.trim().removePrefix("@").removePrefix("[").removeSuffix("]").trim().replace("]", "")
        return "@[$propre]"
    }

    /** Une réponse sur la radio, à la manière des applications MeshCore : `@[Nom] texte`, en tête
     * du message et sans citation (une trame est petite, et c'est cette forme que les autres
     * applications affichent comme une réponse). */
    fun reponseRadio(auteur: String, texte: String): String =
        auteur.takeIf { it.isNotBlank() }?.let { etiquette(it) + " " + texte.trim() } ?: texte.trim()

    /** `@[Nom] texte` en tête d'un message reçu : (nom mentionné, reste du texte), sinon null. */
    fun lireReponse(texte: String): Pair<String, String>? =
        Regex("""^@\[([^\]]+)\]\s+(.+)$""", RegexOption.DOT_MATCHES_ALL).find(texte)?.let { it.groupValues[1] to it.groupValues[2] }

    /** Une réponse précise à un message : on tague son auteur et on cite le début du message,
     * court (une trame radio est petite) : « ↪ @Léa « rdv au pont… » c'est noté ». */
    fun reponse(auteur: String, cite: String, texte: String, longueurCitation: Int = 30): String {
        val extrait = cite.trim().replace(Regex("\\s+"), " ").let { if (it.length > longueurCitation) it.take(longueurCitation - 1).trimEnd() + "…" else it }
        val qui = auteur.takeIf { it.isNotBlank() }?.let { etiquette(it) + " " } ?: ""
        return "↪ $qui« $extrait » ${texte.trim()}".trim()
    }

    private val ACCENTS = mapOf(
        'à' to 'a', 'â' to 'a', 'ä' to 'a', 'á' to 'a', 'ç' to 'c', 'é' to 'e', 'è' to 'e', 'ê' to 'e', 'ë' to 'e',
        'î' to 'i', 'ï' to 'i', 'í' to 'i', 'ô' to 'o', 'ö' to 'o', 'ó' to 'o', 'ù' to 'u', 'û' to 'u', 'ü' to 'u',
        'ú' to 'u', 'ÿ' to 'y', 'ñ' to 'n',
    )

    fun normaliser(texte: String): String =
        texte.lowercase().map { ACCENTS[it] ?: it }.joinToString("").replace(Regex("\\s+"), " ").trim()
}
