package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Competence
import fr.assistacrise.mobile.domaine.Creneau
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.Fiche
import fr.assistacrise.mobile.domaine.Grille
import fr.assistacrise.mobile.domaine.Mobilisation
import fr.assistacrise.mobile.domaine.Titre
import fr.assistacrise.mobile.domaine.TitreDuCatalogue
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Ce que le bénévole fait pour lui-même : ses disponibilités, sa fiche, ses titres, et les
 * dossiers confiés à ses équipes. C'est le chemin de la page « Ma fiche de bénévole » et de
 * « Mes interventions » du site.
 *
 * Contrairement aux messages et aux statuts de mission, **rien ici ne passe par la file
 * d'attente** : une disponibilité cochée sans réseau, puis envoyée trois heures plus tard,
 * arriverait peut-être après que la garde a été constituée — et la personne croirait avoir
 * répondu. Ces gestes exigent le serveur, et l'écran dit quand il manque. Ce qui est gardé
 * sur le téléphone ne sert qu'à relire.
 */
class DepotBenevole(
    private val api: ClientApi,
    private val magasin: Magasin,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    private val _grille = MutableStateFlow<Grille?>(null)
    val grille: StateFlow<Grille?> = _grille
    private val _fiche = MutableStateFlow<Fiche?>(null)
    val fiche: StateFlow<Fiche?> = _fiche
    private val _titres = MutableStateFlow<List<Titre>>(emptyList())
    val titres: StateFlow<List<Titre>> = _titres
    private val _dossiers = MutableStateFlow<List<Dossier>>(emptyList())
    val dossiers: StateFlow<List<Dossier>> = _dossiers

    private val _mobilisations = MutableStateFlow<List<Mobilisation>>(emptyList())
    /** Les demandes de mobilisation qui me sont adressées, actives d'abord. Gardées sur le
     * téléphone : un QR code doit pouvoir se présenter là où il n'y a pas de réseau. */
    val mobilisations: StateFlow<List<Mobilisation>> = _mobilisations

    suspend fun chargerLesMobilisations(idCompte: String): Reponse<Unit> = when (val r = api.mesMobilisations()) {
        is Reponse.Ok -> {
            // Le serveur rend aussi celles que mon institution a émises : seules les miennes se présentent.
            val miennes = r.valeur.filter { it.cibleUtilisateur == idCompte && it.jeton != null }.sortedByDescending { it.active }
            garder("mobilisations", ListSerializer(Mobilisation.serializer()), miennes)
            _mobilisations.value = miennes
            Reponse.Ok(Unit)
        }
        is Reponse.Refus -> r
        is Reponse.Injoignable -> r
    }

    suspend fun restaurer() {
        _mobilisations.value = lire("mobilisations", ListSerializer(Mobilisation.serializer())) ?: emptyList()
        _fiche.value = lire("fiche", Fiche.serializer())
        _titres.value = lire("titres", ListSerializer(Titre.serializer())) ?: emptyList()
        _dossiers.value = lire("dossiers", ListSerializer(Dossier.serializer())) ?: emptyList()
    }

    /** La grille n'est jamais relue du disque : une disponibilité périmée affichée comme vraie trompe. */
    suspend fun chargerLaGrille(campagne: String?): Reponse<Unit> {
        _grille.value = null
        return when (val r = api.grille(campagne)) {
            is Reponse.Ok -> { _grille.value = r.valeur; Reponse.Ok(Unit) }
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    /** La case ne change qu'une fois le serveur d'accord : pas de disponibilité imaginaire. */
    suspend fun declarer(date: String, creneau: Creneau?, disponible: Boolean): Reponse<Unit> {
        val r = api.declarerCreneau(date, creneau, disponible, _grille.value?.campagne?.id)
        if (r is Reponse.Ok) _grille.value = _grille.value?.avec(date, creneau, disponible)
        return r
    }

    /** Le serveur retire alors les créneaux de la période : la grille est relue pour le montrer. */
    suspend fun repondreIndisponible(campagne: String): Reponse<Unit> {
        val r = api.repondreIndisponible(campagne)
        if (r is Reponse.Ok && _grille.value?.campagne?.id == campagne) chargerLaGrille(campagne)
        return r
    }

    private val _catalogue = MutableStateFlow<List<TitreDuCatalogue>>(emptyList())
    val catalogue: StateFlow<List<TitreDuCatalogue>> = _catalogue

    /** Mes documents : ce que j'ai déclaré, et ce que je peux déclarer. */
    suspend fun chargerMesDocuments(idCompte: String): Reponse<Unit> {
        (api.catalogueDesTitres() as? Reponse.Ok)?.let { _catalogue.value = it.valeur.filter { t -> t.actif } }
        return when (val r = api.mesTitres(idCompte)) {
            is Reponse.Ok -> { garder("titres", ListSerializer(Titre.serializer()), r.valeur); _titres.value = r.valeur; Reponse.Ok(Unit) }
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    /** Une pièce ne passe PAS par la file : elle n'attend pas, en clair ou non, sur le téléphone. */
    suspend fun deposerJustificatif(idCompte: String, idCatalogue: String, octets: ByteArray, nomFichier: String, typeMime: String, dateObtention: String?): Reponse<Unit> {
        // Déjà déclaré (refusé, ou saisi par l'encadrement) : on remplace la pièce au lieu de déclarer deux fois.
        val existant = _titres.value.firstOrNull { it.qualification == idCatalogue }?.id
        val r = api.deposerJustificatif(idCatalogue, existant, octets, nomFichier, typeMime, dateObtention)
        if (r is Reponse.Ok) chargerMesDocuments(idCompte)
        return r
    }

    private val _competences = MutableStateFlow<List<Competence>>(emptyList())
    /** Le catalogue des compétences, pour l'arbre « Ce que je sais faire ». */
    val competences: StateFlow<List<Competence>> = _competences

    suspend fun chargerLaFiche(idCompte: String): Reponse<Unit> {
        (api.catalogueDesCompetences() as? Reponse.Ok)?.let { _competences.value = it.valeur }
        (api.mesTitres(idCompte) as? Reponse.Ok)?.let { garder("titres", ListSerializer(Titre.serializer()), it.valeur); _titres.value = it.valeur }
        return when (val r = api.maFiche()) {
            is Reponse.Ok -> { garder("fiche", Fiche.serializer(), r.valeur); _fiche.value = r.valeur; Reponse.Ok(Unit) }
            is Reponse.Refus -> r
            is Reponse.Injoignable -> r
        }
    }

    suspend fun enregistrerLaFiche(fiche: Fiche): Reponse<Unit> = when (val r = api.enregistrerFiche(fiche)) {
        is Reponse.Ok -> { garder("fiche", Fiche.serializer(), r.valeur); _fiche.value = r.valeur; Reponse.Ok(Unit) }
        is Reponse.Refus -> r
        is Reponse.Injoignable -> r
    }

    /** Les dossiers de MES équipes : le serveur en rend parfois davantage, selon le rôle. */
    suspend fun chargerLesDossiers(mesEquipes: Set<String>): Reponse<Unit> = when (val r = api.dossiers()) {
        is Reponse.Ok -> {
            // Les dossiers clos ou résolus ne restent pas sur le téléphone (23/11/2026) : seul ce
            // qui reste à faire est gardé hors réseau. Le serveur garde tout.
            val miens = Dossier.trier(r.valeur.filter { it.equipe != null && it.equipe in mesEquipes && !it.clos })
            garder("dossiers", ListSerializer(Dossier.serializer()), miens)
            _dossiers.value = miens
            Reponse.Ok(Unit)
        }
        is Reponse.Refus -> r
        is Reponse.Injoignable -> r
    }

    suspend fun definirStatut(dossier: Dossier, statut: String): Reponse<Unit> {
        val r = api.definirStatutDossier(dossier.id, statut)
        if (r is Reponse.Ok) _dossiers.value = _dossiers.value.map { if (it.id == dossier.id) it.copy(statut = statut) else it }
        return r
    }

    suspend fun toutEffacer() {
        listOf("fiche", "titres", "dossiers", "mobilisations").forEach { magasin.effacer(it) }
        _mobilisations.value = emptyList()
        _grille.value = null; _fiche.value = null
        _titres.value = emptyList(); _dossiers.value = emptyList()
    }

    private suspend fun <T> lire(nom: String, forme: KSerializer<T>): T? =
        magasin.lire(nom)?.let { runCatching { json.decodeFromString(forme, it) }.getOrNull() }

    private suspend fun <T> garder(nom: String, forme: KSerializer<T>, valeur: T) =
        magasin.ecrire(nom, json.encodeToString(forme, valeur))
}
