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

    private val ACCENTS = mapOf(
        'à' to 'a', 'â' to 'a', 'ä' to 'a', 'á' to 'a', 'ç' to 'c', 'é' to 'e', 'è' to 'e', 'ê' to 'e', 'ë' to 'e',
        'î' to 'i', 'ï' to 'i', 'í' to 'i', 'ô' to 'o', 'ö' to 'o', 'ó' to 'o', 'ù' to 'u', 'û' to 'u', 'ü' to 'u',
        'ú' to 'u', 'ÿ' to 'y', 'ñ' to 'n',
    )

    fun normaliser(texte: String): String =
        texte.lowercase().map { ACCENTS[it] ?: it }.joinToString("").replace(Regex("\\s+"), " ").trim()
}
