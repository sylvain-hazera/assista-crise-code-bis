package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.PhotoEnAttente
import fr.assistacrise.mobile.domaine.PointEau
import fr.assistacrise.mobile.domaine.SignalementPei
import fr.assistacrise.mobile.domaine.SuiviSignalementPei
import fr.assistacrise.mobile.domaine.reunirPointsEau
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi

/**
 * Les points d'eau incendie autour des crises suivies, gardés sur le téléphone (chiffrés comme
 * le reste) pour la carte hors réseau, et les signalements faits sur le terrain (24/11/2026).
 * Signalements et photos passent par la file d'attente, comme les constats de dégâts : rien
 * n'est perdu sans réseau, et un serveur pas encore à jour garde la file pour plus tard.
 */
@OptIn(ExperimentalEncodingApi::class)
class DepotPointsEau(
    private val api: ClientApi,
    private val magasin: Magasin,
    private val file: FileAttente,
    private val nouvelleCle: () -> String,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true; encodeDefaults = true }
    private val _points = MutableStateFlow<List<PointEau>>(emptyList())
    val points: StateFlow<List<PointEau>> = _points
    private val _suivi = MutableStateFlow<List<SuiviSignalementPei>>(emptyList())
    val suivi: StateFlow<List<SuiviSignalementPei>> = _suivi

    suspend fun restaurer() {
        _points.value = magasin.lire(FICHIER)?.let { runCatching { json.decodeFromString(FORME, it) }.getOrNull() } ?: emptyList()
        _suivi.value = magasin.lire(FICHIER_SUIVI)?.let {
            runCatching { json.decodeFromString(ListSerializer(SuiviSignalementPei.serializer()), it) }.getOrNull()
        } ?: emptyList()
    }

    /**
     * Relit les points autour de chaque crise ouverte (dans un rayon de [rayonKm]). Hors réseau,
     * ou si le serveur ne connaît pas encore les points d'eau, la copie précédente reste.
     */
    suspend fun rafraichir(crises: List<Crise>, rayonKm: Int = RAYON_KM): Reponse<Unit> {
        val listes = mutableListOf<List<PointEau>>()
        for (crise in crises.filter { it.ouverte && it.latitude != null && it.longitude != null }.distinctBy { it.id }) {
            when (val r = api.pointsEau(crise.latitude!!, crise.longitude!!, rayonKm)) {
                is Reponse.Ok -> listes += r.valeur
                is Reponse.Refus -> return r
                is Reponse.Injoignable -> return r
            }
        }
        _points.value = reunirPointsEau(listes)
        magasin.ecrire(FICHIER, json.encodeToString(FORME, _points.value))
        (api.mesSignalementsPei() as? Reponse.Ok)?.let { r ->
            _suivi.value = r.valeur
            magasin.ecrire(FICHIER_SUIVI, json.encodeToString(ListSerializer(SuiviSignalementPei.serializer()), r.valeur))
        }
        return Reponse.Ok(Unit)
    }

    /** Circuit feu : le binôme déclare l'état de son point (en route, actif, fermé). */
    suspend fun declarerEtat(activation: String, etat: String, observeLe: String, libelle: String) {
        val charge = kotlinx.serialization.json.buildJsonObject {
            put("etat", kotlinx.serialization.json.JsonPrimitive(etat))
            put("observe_le", kotlinx.serialization.json.JsonPrimitive(observeLe))
        }.toString()
        file.ajouter(ActionEnAttente.GENRE_ETAT_POINT_EAU, activation, charge, libelle)
    }

    suspend fun signaler(signalement: SignalementPei, libelle: String) {
        file.ajouter(ActionEnAttente.GENRE_SIGNALEMENT_PEI, signalement.id,
                     json.encodeToString(SignalementPei.serializer(), signalement), libelle)
    }

    /** Une photo du signalement : les octets attendent chiffrés, la file ne porte que leur clé. */
    suspend fun ajouterPhoto(signalement: String, octets: ByteArray, photo: PhotoEnAttente, libelle: String) {
        val cle = "photo-${nouvelleCle()}"
        magasin.ecrire(cle, Base64.encode(octets))
        file.ajouter(ActionEnAttente.GENRE_PHOTO_SIGNALEMENT_PEI, signalement,
                     json.encodeToString(PhotoEnAttente.serializer(), photo.copy(cle = cle)), libelle)
    }

    fun lirePhoto(action: ActionEnAttente): PhotoEnAttente? =
        runCatching { json.decodeFromString(PhotoEnAttente.serializer(), action.charge) }.getOrNull()

    suspend fun octets(photo: PhotoEnAttente): ByteArray? = magasin.lire(photo.cle)?.let { runCatching { Base64.decode(it) }.getOrNull() }

    suspend fun oublierLesOctets(action: ActionEnAttente) {
        if (action.genre == ActionEnAttente.GENRE_PHOTO_SIGNALEMENT_PEI) lirePhoto(action)?.let { magasin.effacer(it.cle) }
    }

    /** Les signalements faits ici et pas encore partis. */
    fun enFile(): List<SignalementPei> = file.actions.value
        .filter { it.genre == ActionEnAttente.GENRE_SIGNALEMENT_PEI }
        .mapNotNull { runCatching { json.decodeFromString(SignalementPei.serializer(), it.charge) }.getOrNull() }

    suspend fun toutEffacer() {
        _points.value = emptyList(); _suivi.value = emptyList()
        magasin.effacer(FICHIER); magasin.effacer(FICHIER_SUIVI)
    }

    companion object {
        private const val FICHIER = "points-eau"
        private const val FICHIER_SUIVI = "points-eau-suivi"
        const val RAYON_KM = 15
        private val FORME = ListSerializer(PointEau.serializer())
    }
}
