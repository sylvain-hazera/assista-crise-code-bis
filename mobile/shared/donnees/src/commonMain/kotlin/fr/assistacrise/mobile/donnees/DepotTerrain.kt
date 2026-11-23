package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.EtiquetteTerrain
import fr.assistacrise.mobile.domaine.MessageTerrainSortant
import fr.assistacrise.mobile.domaine.TypeMessageTerrain
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlin.random.Random

/**
 * Les messages de terrain du téléphone (22/11/2026) : ils partent par la file, comme tout le
 * reste, et un petit journal dit pour chacun par où il est parti et s'il est arrivé.
 */
class DepotTerrain(
    private val magasin: Magasin,
    private val file: FileAttente,
    private val auteur: () -> String?,
    private val horloge: () -> Long,
    private val maintenantIso: () -> String,
) {
    @Serializable
    data class Envoye(
        val id: String,
        val action: String,
        val type: String,
        val libelle: String,
        val texte: String = "",
        val emisLe: Long,
        /** EN_FILE, RADIO (avec le protocole), RECU, REFUSE. */
        val etat: String = EN_FILE,
        val protocole: String? = null,
        val erreur: String? = null,
    )

    private val json = Json { ignoreUnknownKeys = true }
    private val _journal = MutableStateFlow<List<Envoye>>(emptyList())
    val journal: StateFlow<List<Envoye>> = _journal

    suspend fun restaurer() {
        _journal.value = magasin.lire(FICHIER)?.let { runCatching { json.decodeFromString(FORME, it) }.getOrNull() } ?: emptyList()
    }

    /** Met le message en file. `equipe` : celle dont le canal radio porte le message sans réseau. */
    suspend fun envoyer(
        type: TypeMessageTerrain, mission: String?, equipe: String?, texte: String = "", nombre: Int? = null,
        latitude: Double? = null, longitude: Double? = null, dossier: String? = null,
    ): Envoye {
        require(!type.texteObligatoire || texte.isNotBlank()) { type.questionTexte }
        val identifiant = Random.nextInt(0, 0xffffff).toString(16).padStart(6, '0')
        val sortant = MessageTerrainSortant(type.name, mission, dossier, equipe, texte.trim(), nombre, latitude, longitude, maintenantIso(), identifiant)
        val action = file.ajouter(ActionEnAttente.GENRE_MESSAGE_TERRAIN, equipe ?: "", json.encodeToString(MessageTerrainSortant.serializer(), sortant), type.libelle)
        val envoye = Envoye(identifiant, action.id, type.name, type.libelle, texte.trim(), horloge())
        garder((listOf(envoye) + _journal.value).take(MAX))
        return envoye
    }

    /** L'étiquette radio d'une action en file, ou null si elle est illisible. */
    fun etiquette(action: ActionEnAttente): String? {
        val m = runCatching { json.decodeFromString(MessageTerrainSortant.serializer(), action.charge) }.getOrNull() ?: return null
        val type = TypeMessageTerrain.entries.firstOrNull { it.name == m.type } ?: return null
        return EtiquetteTerrain.ecrire(type, m.mission, auteur() ?: return null, m.identifiant, m.texte, m.nombre, m.dossier)
    }

    /** Après un passage de la file : ce qui n'y est plus est arrivé ; ce qui est parti par radio le dit. */
    suspend fun apresSynchronisation() {
        val actions = file.actions.value.associateBy { it.id }
        val maj = _journal.value.map { e ->
            val a = actions[e.action]
            when {
                e.etat == RECU || e.etat == REFUSE -> e
                a == null -> e.copy(etat = RECU)
                a.etat == EtatAction.REFUSEE -> e.copy(etat = REFUSE, erreur = a.erreur)
                a.parRadio -> e.copy(etat = RADIO, protocole = a.radio)
                else -> e
            }
        }
        if (maj != _journal.value) garder(maj)
    }

    suspend fun toutEffacer() { _journal.value = emptyList(); magasin.effacer(FICHIER) }

    private suspend fun garder(liste: List<Envoye>) {
        _journal.value = liste
        magasin.ecrire(FICHIER, json.encodeToString(FORME, liste))
    }

    companion object {
        const val EN_FILE = "EN_FILE"
        const val RADIO = "RADIO"
        const val RECU = "RECU"
        const val REFUSE = "REFUSE"
        private const val FICHIER = "terrain"
        private const val MAX = 30
        private val FORME = ListSerializer(Envoye.serializer())
    }
}
