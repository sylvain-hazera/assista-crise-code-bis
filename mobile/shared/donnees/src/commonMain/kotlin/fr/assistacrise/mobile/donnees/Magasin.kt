package fr.assistacrise.mobile.donnees

/**
 * Où l'application range ce qu'elle garde d'un lancement à l'autre.
 *
 * Une interface, parce que la règle du projet — on ne stocke rien en clair — se tient à un
 * seul endroit : l'implémentation Android chiffre tout par le Keystore. Rien d'autre dans
 * l'application n'écrit sur disque.
 */
interface Magasin {
    suspend fun lire(nom: String): String?
    suspend fun ecrire(nom: String, contenu: String)
    suspend fun effacer(nom: String)
}

/** Pour les tests, et rien d'autre : tout disparaît avec le processus. */
class MagasinEnMemoire : Magasin {
    val contenu = mutableMapOf<String, String>()
    override suspend fun lire(nom: String): String? = contenu[nom]
    override suspend fun ecrire(nom: String, contenu: String) { this.contenu[nom] = contenu }
    override suspend fun effacer(nom: String) { contenu.remove(nom) }
}
