package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.MessageEquipe
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Mes équipes et leur messagerie, gardées sur le téléphone pour rester lisibles sans réseau.
 *
 * La messagerie passe par le serveur d'Assista-Crise, qui écrit dans le salon Matrix de
 * l'équipe et sur ses canaux radio : un seul fil, quelle que soit la voie. Le client Matrix
 * natif (chiffrement de bout en bout sur le téléphone) viendra le remplacer — voir le
 * dossier § 9 pour ce qui l'en sépare encore.
 */
class DepotEquipes(
    private val api: ClientApi,
    private val magasin: Magasin,
    private val file: FileAttente,
) {
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }

    private val _equipes = MutableStateFlow<List<Equipe>>(emptyList())
    val equipes: StateFlow<List<Equipe>> = _equipes

    /** Fils de messages, par identifiant d'équipe. */
    private val _fils = MutableStateFlow<Map<String, List<MessageEquipe>>>(emptyMap())
    val fils: StateFlow<Map<String, List<MessageEquipe>>> = _fils

    suspend fun restaurer() {
        _equipes.value = lire(FICHIER, ListSerializer(Equipe.serializer())) ?: emptyList()
        _fils.value = _equipes.value.mapNotNull { e ->
            lire(fichierFil(e.id), ListSerializer(MessageEquipe.serializer()))?.let { e.id to it }
        }.toMap()
    }

    suspend fun rafraichir(): Reponse<Unit> = when (val r = api.mesEquipes()) {
        is Reponse.Ok -> {
            magasin.ecrire(FICHIER, json.encodeToString(ListSerializer(Equipe.serializer()), r.valeur))
            _equipes.value = r.valeur
            Reponse.Ok(Unit)
        }
        is Reponse.Refus -> r
        is Reponse.Injoignable -> r
    }

    suspend fun rafraichirFil(idEquipe: String): Reponse<Unit> = when (val r = api.messagerie(idEquipe)) {
        is Reponse.Ok -> { garderFil(idEquipe, r.valeur); Reponse.Ok(Unit) }
        is Reponse.Refus -> r
        is Reponse.Injoignable -> r
    }

    /** Écrit un message : en file d'abord, comme tout le reste. */
    suspend fun ecrire(equipe: Equipe, texte: String) {
        file.ajouter(
            genre = ActionEnAttente.GENRE_MESSAGE_EQUIPE,
            cible = equipe.id,
            charge = texte.trim(),
            libelle = "Message à « ${equipe.nom} »",
        )
    }

    /**
     * La radio de ce téléphone vient d'entendre un message sur le canal de cette équipe. Il
     * entre dans le fil tout de suite, marqué « par radio » : sans réseau, c'est le seul
     * chemin par lequel il peut arriver.
     */
    suspend fun entenduParRadio(idEquipe: String, texte: String, maintenant: Long) {
        // MeshCore écrit « Nom: texte » ; Meshtastic ne dit pas qui parle.
        val coupe = texte.indexOf(": ").takeIf { it in 1..32 }
        val message = MessageEquipe(
            id = "${MessageEquipe.PREFIXE_RADIO_LOCALE}$maintenant-${texte.hashCode().toUInt().toString(16)}",
            source = MessageEquipe.SOURCE_RADIO_LOCALE,
            texte = if (coupe != null) texte.substring(coupe + 2) else texte,
            horodatage = maintenant,
            auteur = if (coupe != null) texte.substring(0, coupe) else "Par radio",
        )
        val fil = _fils.value[idEquipe] ?: emptyList()
        // La même trame peut arriver par deux relais à quelques secondes d'écart.
        if (fil.any { it.texte == message.texte && it.auteur == message.auteur && maintenant - it.horodatage < 120_000 }) return
        ecrireFil(idEquipe, fil + message)
    }

    internal suspend fun garderFil(idEquipe: String, messages: List<MessageEquipe>) {
        // Ce que la radio a entendu ici reste dans le fil tant que le serveur ne le rend pas
        // lui-même : une passerelle l'a peut-être relayé, peut-être pas.
        val textesServeur = messages.map { it.texte }
        val entendus = (_fils.value[idEquipe] ?: emptyList()).filter { local ->
            local.id.startsWith(MessageEquipe.PREFIXE_RADIO_LOCALE) && textesServeur.none { it.endsWith(local.texte) }
        }
        ecrireFil(idEquipe, (messages + entendus).sortedBy { it.horodatage })
    }

    private suspend fun ecrireFil(idEquipe: String, messages: List<MessageEquipe>) {
        // On ne garde que la fin du fil : le téléphone n'est pas l'archive de l'équipe.
        val fin = messages.takeLast(FIL_GARDE)
        magasin.ecrire(fichierFil(idEquipe), json.encodeToString(ListSerializer(MessageEquipe.serializer()), fin))
        _fils.value = _fils.value + (idEquipe to fin)
    }

    suspend fun toutEffacer() {
        _equipes.value.forEach { magasin.effacer(fichierFil(it.id)) }
        magasin.effacer(FICHIER)
        _equipes.value = emptyList()
        _fils.value = emptyMap()
    }

    private suspend fun <T> lire(nom: String, forme: kotlinx.serialization.KSerializer<T>): T? =
        magasin.lire(nom)?.let { runCatching { json.decodeFromString(forme, it) }.getOrNull() }

    private fun fichierFil(idEquipe: String) = "fil-$idEquipe"

    private companion object {
        const val FICHIER = "equipes"
        const val FIL_GARDE = 200
    }
}
