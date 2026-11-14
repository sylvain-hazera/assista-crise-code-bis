package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Commentaire
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.Photo
import fr.assistacrise.mobile.domaine.PhotoEnAttente
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi

/**
 * Ce que l'intervenant ajoute à un dossier depuis le terrain : des commentaires et des photos.
 *
 * Tout passe par la file d'attente — une cave inondée n'a pas de réseau, et la photo prise là
 * doit partir toute seule en remontant. Les octets d'une photo attendent dans le magasin
 * chiffré, jamais dans la galerie ni dans un fichier lisible.
 *
 * **La trace d'une photo** tient en trois choses, fixées au moment de la prise et non de
 * l'envoi : son empreinte (SHA-256 des octets exacts qui partiront), l'heure, et la position —
 * inscrite DANS la photo, là où le serveur la lit. Au retour, l'empreinte que le serveur a
 * calculée de son côté est comparée à celle du téléphone (`Synchronisation`).
 */
@OptIn(ExperimentalEncodingApi::class)
class DepotDossiers(
    private val api: ClientApi,
    private val magasin: Magasin,
    private val file: FileAttente,
    private val nouvelleCle: () -> String,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    private val _commentaires = MutableStateFlow<Map<String, List<Commentaire>>>(emptyMap())
    val commentaires: StateFlow<Map<String, List<Commentaire>>> = _commentaires
    private val _photos = MutableStateFlow<Map<String, List<Photo>>>(emptyMap())
    val photos: StateFlow<Map<String, List<Photo>>> = _photos

    /** Relit du disque ce qu'on sait d'un dossier : il doit se lire sans réseau. */
    suspend fun restaurer(idDossier: String) {
        lire("commentaires-$idDossier", ListSerializer(Commentaire.serializer()))?.let { _commentaires.value += (idDossier to it) }
        lire("photos-$idDossier", ListSerializer(Photo.serializer()))?.let { _photos.value += (idDossier to it) }
    }

    suspend fun rafraichir(idDossier: String): Reponse<Unit> {
        (api.photos(idDossier) as? Reponse.Ok)?.let {
            garder("photos-$idDossier", ListSerializer(Photo.serializer()), it.valeur)
            _photos.value += (idDossier to it.valeur)
        }
        return when (val r = api.commentaires(idDossier)) {
            is Reponse.Ok -> {
                garder("commentaires-$idDossier", ListSerializer(Commentaire.serializer()), r.valeur)
                _commentaires.value += (idDossier to r.valeur)
                Reponse.Ok(Unit)
            }
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    suspend fun commenter(dossier: Dossier, texte: String) {
        file.ajouter(ActionEnAttente.GENRE_COMMENTAIRE, dossier.id, texte.trim(), "Commentaire sur « ${dossier.titre} »")
    }

    /**
     * Met une photo en attente d'envoi. `octets` sont les octets DÉFINITIFS — position déjà
     * inscrite — et `empreinte` leur SHA-256 : rien ne les modifie plus d'ici au serveur.
     */
    suspend fun ajouterPhoto(dossier: Dossier, octets: ByteArray, photo: PhotoEnAttente) {
        val cle = "photo-${nouvelleCle()}"
        magasin.ecrire(cle, Base64.encode(octets))            // sur disque, chiffrée, avant la file
        file.ajouter(
            ActionEnAttente.GENRE_PHOTO, dossier.id,
            json.encodeToString(PhotoEnAttente.serializer(), photo.copy(cle = cle)),
            "Photo pour « ${dossier.titre} »",
        )
    }

    fun lirePhotoEnAttente(action: ActionEnAttente): PhotoEnAttente? =
        runCatching { json.decodeFromString(PhotoEnAttente.serializer(), action.charge) }.getOrNull()

    suspend fun octetsEnAttente(photo: PhotoEnAttente): ByteArray? =
        magasin.lire(photo.cle)?.let { runCatching { Base64.decode(it) }.getOrNull() }

    /** L'action a quitté la file (envoyée, ou écartée par la personne) : les octets n'ont plus à attendre. */
    suspend fun oublierLesOctets(action: ActionEnAttente) {
        if (action.genre == ActionEnAttente.GENRE_PHOTO) lirePhotoEnAttente(action)?.let { magasin.effacer(it.cle) }
    }

    suspend fun toutEffacer(actionsRestantes: List<ActionEnAttente>) {
        actionsRestantes.forEach { oublierLesOctets(it) }
        (_commentaires.value.keys + _photos.value.keys).forEach { magasin.effacer("commentaires-$it"); magasin.effacer("photos-$it") }
        _commentaires.value = emptyMap(); _photos.value = emptyMap()
    }

    private suspend fun <T> lire(nom: String, forme: KSerializer<T>): T? =
        magasin.lire(nom)?.let { runCatching { json.decodeFromString(forme, it) }.getOrNull() }

    private suspend fun <T> garder(nom: String, forme: KSerializer<T>, valeur: T) = magasin.ecrire(nom, json.encodeToString(forme, valeur))
}
