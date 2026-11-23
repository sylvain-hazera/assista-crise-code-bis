package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Compte
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
internal data class SessionEnregistree(
    val acces: String,
    val rafraichissement: String,
    val compte: Compte,
)

/**
 * Qui est connecté, et avec quels jetons. Seule détentrice des jetons : le reste de
 * l'application ne voit que `compte`.
 */
class Session(private val magasin: Magasin) {
    /** La session du central, ou celle du satellite (23/11/2026) : un jeton du central ne vaut pas
     * sur le satellite, qui a sa propre clé. Les deux sont gardées : revenir au central rend la
     * session du central telle qu'elle était. */
    private var fichier = FICHIER

    suspend fun basculerEspace(satellite: Boolean) {
        fichier = if (satellite) FICHIER_SATELLITE else FICHIER
        courante = null
        _compte.value = null
        restaurer()
    }

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private var courante: SessionEnregistree? = null

    private val _compte = MutableStateFlow<Compte?>(null)
    val compte: StateFlow<Compte?> = _compte

    /**
     * Zone de travail : « PROD » (données réelles) ou « DEMO » (formation, données fictives).
     * Envoyée avec chaque requête (en-tête X-Environment), comme la bascule du site ; gardée sur
     * le téléphone, pour que la tâche de fond et le service de terrain travaillent dans la même.
     */
    private val _environnement = MutableStateFlow(PROD)
    val environnement: StateFlow<String> = _environnement
    val enFormation: Boolean get() = _environnement.value == DEMO

    suspend fun changerDEnvironnement(zone: String) {
        require(zone == PROD || zone == DEMO)
        _environnement.value = zone
        if (zone == PROD) magasin.effacer(FICHIER_ZONE) else magasin.ecrire(FICHIER_ZONE, zone)
    }

    internal val jetonAcces: String? get() = courante?.acces
    internal val jetonRafraichissement: String? get() = courante?.rafraichissement

    /** À appeler une fois au démarrage : retrouve la session du lancement précédent. */
    suspend fun restaurer() {
        val texte = magasin.lire(fichier) ?: return
        // Un fichier illisible (format d'une autre version, clé du Keystore perdue) vaut
        // déconnexion : on redemande le mot de passe plutôt que de planter au démarrage.
        courante = runCatching { json.decodeFromString<SessionEnregistree>(texte) }.getOrNull()
        _compte.value = courante?.compte
        // La formation ne survit pas à un compte qui n'y a plus droit.
        _environnement.value = if (magasin.lire(FICHIER_ZONE) == DEMO && courante?.compte?.peutSeFormer == true) DEMO else PROD
    }

    internal suspend fun ouvrir(acces: String, rafraichissement: String, compte: Compte) {
        enregistrer(SessionEnregistree(acces, rafraichissement, compte))
    }

    /** Le serveur fait tourner le jeton de rafraîchissement : l'ancien est mort dès l'échange. */
    internal suspend fun renouveler(acces: String, rafraichissement: String?) {
        val s = courante ?: return
        enregistrer(s.copy(acces = acces, rafraichissement = rafraichissement ?: s.rafraichissement))
    }

    internal suspend fun mettreAJourLeCompte(compte: Compte) {
        val s = courante ?: return
        enregistrer(s.copy(compte = compte))
    }

    suspend fun fermer() {
        courante = null
        _compte.value = null
        magasin.effacer(fichier)
        changerDEnvironnement(PROD)
    }

    /**
     * Ce que ce téléphone présente au serveur pour être reconnu : un appareil déjà connu du
     * compte n'est pas ralenti par les essais ratés de quelqu'un d'autre. Ne dispense ni du
     * mot de passe ni du code, et survit à la déconnexion — c'est le téléphone qui est
     * reconnu, pas la session.
     */
    internal suspend fun appareil(): String = magasin.lire(FICHIER_APPAREIL).orEmpty()

    internal suspend fun retenirAppareil(jeton: String) {
        if (jeton.isNotBlank()) magasin.ecrire(FICHIER_APPAREIL, jeton)
    }

    private suspend fun enregistrer(s: SessionEnregistree) {
        courante = s
        magasin.ecrire(fichier, json.encodeToString(SessionEnregistree.serializer(), s))
        _compte.value = s.compte
    }

    companion object {
        const val PROD = "PROD"
        const val DEMO = "DEMO"
        private const val FICHIER_ZONE = "zone"
        private const val FICHIER = "session"
        private const val FICHIER_SATELLITE = "session-satellite"
        private const val FICHIER_APPAREIL = "appareil"
    }
}
