package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Constat
import fr.assistacrise.mobile.domaine.PhotoEnAttente
import fr.assistacrise.mobile.domaine.PointTournee
import fr.assistacrise.mobile.domaine.SecteurEmbarque
import fr.assistacrise.mobile.domaine.TypeBien
import fr.assistacrise.mobile.domaine.secteurAEffacer
import fr.assistacrise.mobile.domaine.tourneeHorsLigne
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi

/**
 * L'évaluation des dégâts à pied, côté données (DOSSIER-ADRESSES-ET-DEGATS.md, § 4 et 5).
 *
 * - **La tournée** : demandée au serveur quand il répond, calculée sur le secteur embarqué sinon.
 * - **Le secteur embarqué** n'est chargé qu'à la demande (« embarquer ce secteur »), gardé dans le
 *   magasin chiffré, daté, et **effacé dès la synchronisation** de ce qui y a été saisi.
 * - **Constats et photos** passent par la file d'attente, comme tout le reste. Le constat porte
 *   un identifiant tiré ici : renvoyé dix fois, il ne crée qu'un constat. Une photo vise son
 *   constat, pas le bien : un point nouveau n'a de fiche qu'une fois son constat reçu.
 */
@OptIn(ExperimentalEncodingApi::class)
class DepotDegats(
    private val api: ClientApi,
    private val magasin: Magasin,
    private val file: FileAttente,
    private val nouvelleCle: () -> String,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true; encodeDefaults = true }

    private val _secteur = MutableStateFlow<SecteurEmbarque?>(null)
    val secteur: StateFlow<SecteurEmbarque?> = _secteur
    private val _types = MutableStateFlow<List<TypeBien>>(emptyList())
    val types: StateFlow<List<TypeBien>> = _types

    suspend fun restaurer() {
        magasin.lire(FICHIER_SECTEUR)?.let { t -> _secteur.value = runCatching { json.decodeFromString(SecteurEmbarque.serializer(), t) }.getOrNull() }
        magasin.lire(FICHIER_TYPES)?.let { t -> _types.value = runCatching { json.decodeFromString(ListSerializer(TypeBien.serializer()), t) }.getOrDefault(emptyList()) }
    }

    /** Le catalogue des types de bien, gardé pour servir hors réseau. */
    suspend fun chargerTypes(): Reponse<List<TypeBien>> = api.typesBien().also { r ->
        if (r is Reponse.Ok) {
            _types.value = r.valeur
            magasin.ecrire(FICHIER_TYPES, json.encodeToString(ListSerializer(TypeBien.serializer()), r.valeur))
        }
    }

    /** « Embarquer ce secteur » : adresses, biens, dossiers et cercles autour de moi, pour la crise. */
    suspend fun embarquer(crise: String, latitude: Double, longitude: Double, rayonM: Int = RAYON_EMBARQUE_M): Reponse<SecteurEmbarque> {
        chargerTypes()
        return api.secteurEmbarque(crise, latitude, longitude, rayonM).also { r ->
            if (r is Reponse.Ok) enregistrer(r.valeur)
        }
    }

    suspend fun effacerSecteur() {
        magasin.effacer(FICHIER_SECTEUR)
        _secteur.value = null
    }

    /**
     * Les points autour de moi. En ligne, ceux du serveur ; sans réponse, ceux du secteur embarqué
     * (`horsLigne` vrai). Ce qui a été évalué ici et attend d'être envoyé est marqué dans les deux cas.
     */
    suspend fun tournee(crise: String, latitude: Double, longitude: Double, rayonM: Int = 150): Tournee {
        val enFile = constatsEnFile()
        return when (val r = api.tournee(crise, latitude, longitude, rayonM)) {
            is Reponse.Ok -> {
                val evaluesIci = enFile.mapNotNull { it.banId }.toSet()
                Tournee(r.valeur.map { if (it.banId != null && it.banId in evaluesIci) it.copy(enAttente = true) else it }, horsLigne = false)
            }
            is Reponse.Refus -> Tournee(emptyList(), horsLigne = false, refus = r.message)
            is Reponse.Injoignable -> {
                val s = _secteur.value?.takeIf { it.crise == crise }
                    ?: return Tournee(emptyList(), horsLigne = true, refus = "Pas de réseau, et aucun secteur embarqué pour cette crise.")
                Tournee(tourneeHorsLigne(s, enFile, latitude, longitude, rayonM.toDouble()), horsLigne = true)
            }
        }
    }

    /** Met un constat en file (et le compte dans le secteur embarqué, qui attendra son envoi). */
    suspend fun constater(constat: Constat, libelle: String) {
        file.ajouter(ActionEnAttente.GENRE_CONSTAT, constat.id, json.encodeToString(Constat.serializer(), constat), libelle)
        _secteur.value?.let { enregistrer(it.copy(constatsFaits = it.constatsFaits + 1)) }
    }

    /** Une photo du constat : les octets attendent chiffrés, la file ne porte que leur clé. */
    suspend fun ajouterPhoto(constat: String, octets: ByteArray, photo: PhotoEnAttente, libelle: String) {
        val cle = "photo-${nouvelleCle()}"
        magasin.ecrire(cle, Base64.encode(octets))
        file.ajouter(ActionEnAttente.GENRE_PHOTO_CONSTAT, constat,
                     json.encodeToString(PhotoEnAttente.serializer(), photo.copy(cle = cle)), libelle)
    }

    fun lirePhoto(action: ActionEnAttente): PhotoEnAttente? =
        runCatching { json.decodeFromString(PhotoEnAttente.serializer(), action.charge) }.getOrNull()

    suspend fun octets(photo: PhotoEnAttente): ByteArray? = magasin.lire(photo.cle)?.let { runCatching { Base64.decode(it) }.getOrNull() }

    suspend fun oublierLesOctets(action: ActionEnAttente) {
        if (action.genre == ActionEnAttente.GENRE_PHOTO_CONSTAT) lirePhoto(action)?.let { magasin.effacer(it.cle) }
    }

    /** Après chaque envoi de la file : tout ce qui a été saisi est parti, le secteur s'efface. */
    suspend fun apresSynchronisation() {
        if (secteurAEffacer(_secteur.value, file.actions.value)) effacerSecteur()
    }

    fun constatsEnFile(): List<Constat> = file.actions.value
        .filter { it.genre == ActionEnAttente.GENRE_CONSTAT }
        .mapNotNull { runCatching { json.decodeFromString(Constat.serializer(), it.charge) }.getOrNull() }

    private suspend fun enregistrer(secteur: SecteurEmbarque) {
        magasin.ecrire(FICHIER_SECTEUR, json.encodeToString(SecteurEmbarque.serializer(), secteur))
        _secteur.value = secteur
    }

    data class Tournee(val points: List<PointTournee>, val horsLigne: Boolean, val refus: String? = null)

    companion object {
        private const val FICHIER_SECTEUR = "degats-secteur"
        private const val FICHIER_TYPES = "degats-types"
        const val RAYON_EMBARQUE_M = 1000
    }
}
