package fr.assistacrise.mobile.domaine

/**
 * Recherche d'un noeud ou d'un contact radio (27/11/2026) : sans tenir compte des accents ni de
 * la casse, chaque mot tapé doit se trouver dans l'un des champs (nom, nom court, identifiant ou
 * clé, genre). « !6c73 », « repeteur 33 » ou « Bord » suffisent.
 */
object RechercheNoeud {
    private val ACCENTS = mapOf(
        'à' to 'a', 'â' to 'a', 'ä' to 'a', 'á' to 'a', 'ç' to 'c', 'é' to 'e', 'è' to 'e', 'ê' to 'e',
        'ë' to 'e', 'î' to 'i', 'ï' to 'i', 'í' to 'i', 'ô' to 'o', 'ö' to 'o', 'ó' to 'o', 'ù' to 'u',
        'û' to 'u', 'ü' to 'u', 'ú' to 'u', 'ÿ' to 'y', 'ñ' to 'n', 'œ' to 'o',
    )

    fun normaliser(texte: String): String = texte.lowercase().map { ACCENTS[it] ?: it }.joinToString("")

    fun correspond(requete: String, vararg champs: String?): Boolean {
        val mots = normaliser(requete).split(' ', '\t').filter { it.isNotBlank() }
        if (mots.isEmpty()) return true
        val texte = champs.filterNotNull().joinToString(" ") { normaliser(it) }
        return mots.all { it in texte }
    }
}
