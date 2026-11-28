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
    /** Mes manifestations à venir (26/11/2026) : celles où je suis inscrit, du jour à J+30, avec
     * leur détail (postes, mon statut), lisibles sans réseau. Celles du jour en sont tirées. */
    private val _aVenir = MutableStateFlow<List<ManifestationAsso>>(emptyList())
    val aVenir: StateFlow<List<ManifestationAsso>> = _aVenir
    /** La liste des manifestations telle que le serveur l'a rendue la dernière fois. */
    private val _liste = MutableStateFlow<List<ManifestationAsso>>(emptyList())
    val liste: StateFlow<List<ManifestationAsso>> = _liste
    /** Le périmètre de la carte : la crise en cours, sinon celles de ma commune (27/11/2026). */
    private val _perimetre = MutableStateFlow(fr.assistacrise.mobile.domaine.PerimetreCarte())
    val perimetre: StateFlow<fr.assistacrise.mobile.domaine.PerimetreCarte> = _perimetre

    /** Les lieux de la zone en cours : contours ou centres des crises du périmètre, lieux (sinon
     * postes placés) des manifestations du jour. La carte hors ligne les couvre, + 15 km. */
    fun lieuxDeLaZone(): List<Pair<Double, Double>> =
        _perimetre.value.crises.flatMap { it.points() } + _manifestations.value.flatMap { m ->
            if (m.latitude != null && m.longitude != null) listOf(m.latitude!! to m.longitude!!)
            else m.postes.mapNotNull { p -> if (p.latitude != null && p.longitude != null) p.latitude!! to p.longitude!! else null }
        }

    /** Une clé stable de la zone en cours (crises et manifestations) : une région déjà
     * embarquée pour la même zone n'est pas retéléchargée. Vide : pas de zone. */
    fun cleDeLaZone(): String = (_perimetre.value.crises.map { "c" + it.id.take(8) } + _manifestations.value.map { "m" + it.id.take(8) })
        .sorted().joinToString("-")

    suspend fun restaurer() {
        _marqueurs.value = magasin.lire(FICHIER_MARQUEURS)?.let { runCatching { json.decodeFromString(FORME_MARQUEURS, it) }.getOrNull() } ?: emptyList()
        _manifestations.value = magasin.lire(FICHIER_MANIFS)?.let { runCatching { json.decodeFromString(FORME_MANIFS, it) }.getOrNull() } ?: emptyList()
        _perimetre.value = magasin.lire(FICHIER_PERIMETRE)?.let { runCatching { json.decodeFromString(fr.assistacrise.mobile.domaine.PerimetreCarte.serializer(), it) }.getOrNull() }
            ?: fr.assistacrise.mobile.domaine.PerimetreCarte()
        _aVenir.value = magasin.lire(FICHIER_A_VENIR)?.let { runCatching { json.decodeFromString(FORME_MANIFS, it) }.getOrNull() } ?: emptyList()
        _liste.value = magasin.lire(FICHIER_LISTE)?.let { runCatching { json.decodeFromString(FORME_MANIFS, it) }.getOrNull() } ?: emptyList()
    }

    /** Relit les marqueurs, et le détail des manifestations du jour. Hors réseau, la copie reste. */
    suspend fun rafraichir(): Reponse<Unit> {
        when (val r = api.perimetreCarte()) {
            is Reponse.Ok -> { _perimetre.value = r.valeur; magasin.ecrire(FICHIER_PERIMETRE, json.encodeToString(fr.assistacrise.mobile.domaine.PerimetreCarte.serializer(), r.valeur)) }
            is Reponse.Injoignable -> return r
            is Reponse.Refus -> Unit
        }
        when (val r = api.marqueursTerrain()) {
            is Reponse.Ok -> { _marqueurs.value = r.valeur; magasin.ecrire(FICHIER_MARQUEURS, json.encodeToString(FORME_MARQUEURS, r.valeur)) }
            is Reponse.Injoignable -> return r
            is Reponse.Refus -> Unit
        }
        when (val r = api.manifestations()) {
            is Reponse.Ok -> {
                gardeLaListe(r.valeur)
                val aVenir = r.valeur.filter { it.inscrit && aVenir(it) }.mapNotNull { (api.manifestation(it.id) as? Reponse.Ok)?.valeur }
                _aVenir.value = aVenir
                magasin.ecrire(FICHIER_A_VENIR, json.encodeToString(FORME_MANIFS, aVenir))
                val details = aVenir.filter { duJour(it) }
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

    /** Garde la liste rendue par le serveur, pour l'écran des manifestations hors réseau. */
    suspend fun gardeLaListe(liste: List<ManifestationAsso>) {
        _liste.value = liste
        magasin.ecrire(FICHIER_LISTE, json.encodeToString(FORME_MANIFS, liste))
    }

    /** Le détail gardé d'une manifestation (une de mes manifestations à venir), sans réseau. */
    fun detailGarde(id: String): ManifestationAsso? = _aVenir.value.firstOrNull { it.id == id }

    /** Pas encore finie (6 heures de marge) et commençant dans les 30 jours. */
    fun aVenir(m: ManifestationAsso): Boolean {
        val debut = instant(m.debut) ?: return false
        val fin = instant(m.fin) ?: return false
        val t = maintenant()
        return fin >= t - 6 * HEURE && debut <= t + JOURS_A_VENIR * 24 * HEURE
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
    /**
     * À quoi rattacher un marqueur posé maintenant (28/11/2026, décision de Sylvain : seulement en
     * phase de crise ou de manifestation, et toujours rattaché à l'une ou à l'autre) : les crises
     * ouvertes du périmètre, puis les manifestations du jour en cours — de leur premier début
     * (manifestation ou poste, pour la mise en place) à leur dernière fin.
     */
    fun rattachementsEnCours(): List<fr.assistacrise.mobile.domaine.Rattachement> {
        val t = maintenant()
        val crises = _perimetre.value.crises.map { fr.assistacrise.mobile.domaine.Rattachement(crise = it.id, nom = it.nom.ifBlank { "Crise" }) }
        val manifs = _manifestations.value.filter { m ->
            if (m.statut == "ANNULEE" || m.statut == "BROUILLON") return@filter false
            val debuts = (listOf(m.debut) + m.postes.map { it.debut }).mapNotNull(instant)
            val fins = (listOf(m.fin) + m.postes.map { it.fin }).mapNotNull(instant)
            debuts.isNotEmpty() && fins.isNotEmpty() && t in debuts.min()..fins.max()
        }.map { fr.assistacrise.mobile.domaine.Rattachement(manifestation = it.id, nom = it.titre) }
        return crises + manifs
    }

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
        _marqueurs.value = emptyList(); _manifestations.value = emptyList(); _perimetre.value = fr.assistacrise.mobile.domaine.PerimetreCarte()
        _aVenir.value = emptyList(); _liste.value = emptyList()
        listOf(FICHIER_MARQUEURS, FICHIER_MANIFS, FICHIER_PERIMETRE, FICHIER_A_VENIR, FICHIER_LISTE).forEach { magasin.effacer(it) }
    }

    private companion object {
        const val HEURE = 3_600_000L
        const val FICHIER_MARQUEURS = "marqueurs-terrain"
        const val FICHIER_MANIFS = "manifestations-du-jour"
        const val FICHIER_PERIMETRE = "perimetre-carte"
        const val FICHIER_A_VENIR = "manifestations-a-venir"
        const val FICHIER_LISTE = "manifestations-liste"
        const val JOURS_A_VENIR = 30L
        val FORME_MARQUEURS = ListSerializer(MarqueurCentral.serializer())
        val FORME_MANIFS = ListSerializer(ManifestationAsso.serializer())
    }
}
