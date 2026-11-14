package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.Depot
import fr.assistacrise.mobile.domaine.GenreDepot
import fr.assistacrise.mobile.domaine.Information
import fr.assistacrise.mobile.domaine.TypeDepot
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Le mode citoyen (dossier § 13) : les crises ouvertes, ce qu'on y a publié, et les trois
 * gestes — se déclarer en sécurité, demander de l'aide, signaler. Les crises et les types
 * sont gardés sur le téléphone : un formulaire doit pouvoir se remplir sans réseau.
 */
class DepotCitoyen(
    private val api: ClientApi,
    private val magasin: Magasin,
    private val file: FileAttente,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    private val _crises = MutableStateFlow<List<Crise>>(emptyList())
    val crises: StateFlow<List<Crise>> = _crises
    private val _typesDemande = MutableStateFlow<List<TypeDepot>>(emptyList())
    val typesDemande: StateFlow<List<TypeDepot>> = _typesDemande
    private val _typesInformation = MutableStateFlow<List<TypeDepot>>(emptyList())
    val typesInformation: StateFlow<List<TypeDepot>> = _typesInformation
    private val _typesOffre = MutableStateFlow<List<TypeDepot>>(emptyList())
    val typesOffre: StateFlow<List<TypeDepot>> = _typesOffre
    private val _informations = MutableStateFlow<List<Information>>(emptyList())
    val informations: StateFlow<List<Information>> = _informations

    suspend fun restaurer() {
        _crises.value = lire("crises", Crise.serializer())
        _typesDemande.value = lire("types-demande", TypeDepot.serializer())
        _typesInformation.value = lire("types-information", TypeDepot.serializer())
        _typesOffre.value = lire("types-offre", TypeDepot.serializer())
        _informations.value = lire("informations", Information.serializer())
    }

    suspend fun rafraichir(): Reponse<Unit> {
        val r = api.liste("crises/", Crise.serializer())
        if (r !is Reponse.Ok) return r.sansListe()
        // Les crises closes n'intéressent plus personne ici.
        garder("crises", Crise.serializer(), r.valeur.filter { it.ouverte }, _crises)
        (api.liste("types-demande/", TypeDepot.serializer()) as? Reponse.Ok)?.let {
            garder("types-demande", TypeDepot.serializer(), it.valeur.filter { t -> !t.libelle.isNullOrBlank() }, _typesDemande)
        }
        (api.liste("types-information/", TypeDepot.serializer()) as? Reponse.Ok)?.let {
            garder("types-information", TypeDepot.serializer(), it.valeur.filter { t -> !t.libelle.isNullOrBlank() }, _typesInformation)
        }
        (api.liste("types-offre/", TypeDepot.serializer()) as? Reponse.Ok)?.let {
            garder("types-offre", TypeDepot.serializer(), it.valeur.filter { t -> !t.libelle.isNullOrBlank() }, _typesOffre)
        }
        (api.liste("informations/", Information.serializer()) as? Reponse.Ok)?.let {
            val ouvertes = _crises.value.map { c -> c.id }.toSet()
            garder("informations", Information.serializer(), it.valeur.filter { i -> i.crise in ouvertes }, _informations)
        }
        return Reponse.Ok(Unit)
    }

    /**
     * Dépose : en file d'abord. Le corps est figé ici, tel qu'il partira. `clePhoto` désigne
     * les octets d'une photo jointe, déjà gardés chiffrés (`DepotDossiers.garderOctets`).
     */
    suspend fun deposer(depot: Depot, clePhoto: String? = null) {
        val corps = corps(depot)
        file.ajouter(
            genre = ActionEnAttente.GENRE_DEPOT,
            cible = depot.genre.chemin,
            charge = (if (clePhoto == null) corps else JsonObject(corps + (CLE_PHOTO to kotlinx.serialization.json.JsonPrimitive(clePhoto)))).toString(),
            libelle = when (depot.genre) {
                GenreDepot.SECURITE -> "Déclaration « en sécurité » — ${depot.crise.nom}"
                GenreDepot.DEMANDE -> "Demande « ${depot.titre.trim()} »"
                GenreDepot.SIGNALEMENT -> "Signalement « ${depot.titre.trim()} »"
                GenreDepot.OFFRE -> "Offre d'aide « ${depot.titre.trim()} »"
            },
        )
    }

    suspend fun toutEffacer() {
        listOf("crises", "types-demande", "types-information", "types-offre", "informations").forEach { magasin.effacer(it) }
        _typesOffre.value = emptyList()
        _crises.value = emptyList(); _informations.value = emptyList()
        _typesDemande.value = emptyList(); _typesInformation.value = emptyList()
    }

    private suspend fun <T> lire(nom: String, forme: KSerializer<T>): List<T> =
        magasin.lire(nom)?.let { runCatching { json.decodeFromString(ListSerializer(forme), it) }.getOrNull() } ?: emptyList()

    private suspend fun <T> garder(nom: String, forme: KSerializer<T>, valeur: List<T>, flux: MutableStateFlow<List<T>>) {
        magasin.ecrire(nom, json.encodeToString(ListSerializer(forme), valeur))
        flux.value = valeur
    }

    private fun <T> Reponse<T>.sansListe(): Reponse<Unit> = when (this) {
        is Reponse.Ok -> Reponse.Ok(Unit)
        is Reponse.Refus -> this
        is Reponse.Injoignable -> this
    }

    companion object {
        /** Dans le corps mis en file : où attendent les octets de la photo jointe. Ne part jamais au serveur. */
        const val CLE_PHOTO = "_photo"

        /** Le corps attendu par le serveur pour chaque geste. Public pour être testé seul. */
        fun corps(d: Depot): JsonObject = buildJsonObject {
            // Les précisions du type d'abord : un champ du formulaire, s'il porte le même nom, l'emporte.
            d.precisions.forEach { (cle, valeur) -> put(cle, valeur) }
            // Le serveur attend une géométrie en texte (EWKT), pas un objet : il la passe telle
            // quelle à PostGIS. Longitude d'abord, comme toujours en WKT.
            fun position(cle: String) = d.position?.let { p ->
                put(cle, "SRID=4326;POINT(${p.longitude} ${p.latitude})")
            }
            when (d.genre) {
                GenreDepot.SECURITE -> {
                    put("crise", d.crise.id)
                    put("situation", d.situation.name)
                    put("type_declarant", d.declarant.name)
                    put("prenom_referent", d.deposant.prenom.trim())
                    put("nom_referent", d.deposant.nom.trim())
                    put("contact_referent", d.deposant.telephone.trim())
                    put("nombre_adultes", d.adultes)
                    put("nombre_enfants", d.enfants)
                    if (d.description.isNotBlank()) put("commentaire", d.description.trim())
                    position("location")
                }
                GenreDepot.DEMANDE -> {
                    put("crisis", d.crise.id)
                    put("request_type", d.type?.id)
                    put("title", d.titre.trim())
                    if (d.description.isNotBlank()) put("description", d.description.trim())
                    put("first_name_request", d.deposant.prenom.trim())
                    put("last_name_request", d.deposant.nom.trim())
                    put("email_request", d.deposant.email.trim())
                    put("phone_request", d.deposant.telephone.trim())
                    position("location")
                }
                GenreDepot.OFFRE -> {
                    put("crisis", d.crise.id)
                    put("offer_type", d.type?.id)
                    put("title", d.titre.trim())
                    if (d.description.isNotBlank()) put("description", d.description.trim())
                    put("first_name_offer", d.deposant.prenom.trim())
                    put("last_name_offer", d.deposant.nom.trim())
                    put("email_offer", d.deposant.email.trim())
                    put("phone_offer", d.deposant.telephone.trim())
                    position("location")
                }
                GenreDepot.SIGNALEMENT -> {
                    put("crisis", d.crise.id)
                    put("information_type", d.type?.id)
                    put("title", d.titre.trim())
                    put("first_name_information", d.deposant.prenom.trim())
                    put("last_name_information", d.deposant.nom.trim())
                    put("email_information", d.deposant.email.trim())
                    put("phone_information", d.deposant.telephone.trim())
                    position("location")
                }
            }
        }
    }
}
