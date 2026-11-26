package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ManifestationAsso
import fr.assistacrise.mobile.domaine.MarqueurCentral
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Ce que la carte du terrain garde pour le hors-réseau (27/11/2026) : les marqueurs du central
 * (posés par la radio des autres, l'application, le PC) et les manifestations du jour où je suis
 * inscrit, avec leurs postes placés (PC, signalisation…) et mon statut sur chacun.
 *
 * `instant` lit une date ISO 8601 (le code commun n'a pas de bibliothèque de dates : l'appelant
 * la fournit) ; `maintenant` donne l'heure en millisecondes.
 */
class DepotCarteTerrain(
    private val api: ClientApi,
    private val magasin: Magasin,
    private val instant: (String) -> Long?,
    private val maintenant: () -> Long,
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val _marqueurs = MutableStateFlow<List<MarqueurCentral>>(emptyList())
    val marqueurs: StateFlow<List<MarqueurCentral>> = _marqueurs
    private val _manifestations = MutableStateFlow<List<ManifestationAsso>>(emptyList())
    val manifestations: StateFlow<List<ManifestationAsso>> = _manifestations

    suspend fun restaurer() {
        _marqueurs.value = magasin.lire(FICHIER_MARQUEURS)?.let { runCatching { json.decodeFromString(FORME_MARQUEURS, it) }.getOrNull() } ?: emptyList()
        _manifestations.value = magasin.lire(FICHIER_MANIFS)?.let { runCatching { json.decodeFromString(FORME_MANIFS, it) }.getOrNull() } ?: emptyList()
    }

    /** Relit les marqueurs, et le détail des manifestations du jour. Hors réseau, la copie reste. */
    suspend fun rafraichir(): Reponse<Unit> {
        when (val r = api.marqueursTerrain()) {
            is Reponse.Ok -> { _marqueurs.value = r.valeur; magasin.ecrire(FICHIER_MARQUEURS, json.encodeToString(FORME_MARQUEURS, r.valeur)) }
            is Reponse.Injoignable -> return r
            is Reponse.Refus -> Unit
        }
        when (val r = api.manifestations()) {
            is Reponse.Ok -> {
                val details = r.valeur.filter { it.inscrit && duJour(it) }.mapNotNull { (api.manifestation(it.id) as? Reponse.Ok)?.valeur }
                _manifestations.value = details
                magasin.ecrire(FICHIER_MANIFS, json.encodeToString(FORME_MANIFS, details))
            }
            is Reponse.Injoignable -> return r
            is Reponse.Refus -> Unit
        }
        return Reponse.Ok(Unit)
    }

    /** Ajoute (ou remplace) un marqueur que le serveur vient de rendre. */
    suspend fun garder(m: MarqueurCentral) {
        _marqueurs.value = listOf(m) + _marqueurs.value.filter { it.id != m.id }
        magasin.ecrire(FICHIER_MARQUEURS, json.encodeToString(FORME_MARQUEURS, _marqueurs.value))
    }

    /** Une manifestation d'aujourd'hui (la veille au soir et le lendemain matin compris). */
    fun duJour(m: ManifestationAsso): Boolean {
        val debut = instant(m.debut) ?: return false
        val fin = instant(m.fin) ?: return false
        val t = maintenant()
        return debut <= t + 12 * HEURE && fin >= t - 6 * HEURE
    }

    /**
     * Mes présences en cours : postes où je suis pointé présent et dont le créneau n'est pas fini.
     * Rend (manifestation, poste, fin du créneau en ms). C'est ce qui allume le partage de
     * position en manifestation (décision de Sylvain du 26/11/2026 : du pointage à la fin).
     */
    fun presencesEnCours(): List<Triple<ManifestationAsso, fr.assistacrise.mobile.domaine.PosteManifestation, Long>> {
        val t = maintenant()
        return _manifestations.value.flatMap { m ->
            m.postes.filter { it.monStatut == "PRESENT" }.mapNotNull { p ->
                val debut = instant(p.debut) ?: return@mapNotNull null
                val fin = instant(p.fin) ?: return@mapNotNull null
                if (t in debut..fin) Triple(m, p, fin) else null
            }
        }
    }

    /** Un créneau où j'étais présent s'est terminé dans les douze dernières heures. */
    fun presenceTermineeRecemment(): Boolean {
        val t = maintenant()
        return _manifestations.value.any { m ->
            m.postes.any { p -> p.monStatut == "PRESENT" && (instant(p.fin) ?: Long.MAX_VALUE).let { it < t && it > t - 12 * HEURE } }
        }
    }

    suspend fun toutEffacer() {
        _marqueurs.value = emptyList(); _manifestations.value = emptyList()
        magasin.effacer(FICHIER_MARQUEURS); magasin.effacer(FICHIER_MANIFS)
    }

    private companion object {
        const val HEURE = 3_600_000L
        const val FICHIER_MARQUEURS = "marqueurs-terrain"
        const val FICHIER_MANIFS = "manifestations-du-jour"
        val FORME_MARQUEURS = ListSerializer(MarqueurCentral.serializer())
        val FORME_MANIFS = ListSerializer(ManifestationAsso.serializer())
    }
}
