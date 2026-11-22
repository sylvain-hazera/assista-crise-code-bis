package fr.assistacrise.mobile

import fr.assistacrise.mobile.lien.MessageDirect
import fr.assistacrise.mobile.lien.MessageRadio
import fr.assistacrise.mobile.lien.PiloteMeshCore
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import fr.assistacrise.mobile.lien.PiloteRadio
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import fr.assistacrise.mobile.domaine.MessageConversationRadio as Message
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * La messagerie radio (22/11/2026) : tous les canaux du nœud et les messages directs, en
 * Meshtastic comme en MeshCore — au-delà du seul canal de l'équipe. « J'aurais voulu avoir la
 * liste des canaux de mon nœud, pouvoir parler dedans, la liste des contacts, faire une
 * recherche par nom, faire des messages directs. »
 *
 * Une conversation se désigne par une clé : `c:<index>` (canal) ou `d:<contact>` (direct, le
 * contact étant « !1a2b3c4d » en Meshtastic ou le préfixe de clé publique en MeshCore). Gardée
 * dans le magasin chiffré du téléphone, 200 messages par conversation au plus.
 */
class MessagerieRadio(private val app: Application) {

    private val json = Json { ignoreUnknownKeys = true }
    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val _conversations = MutableStateFlow<Map<String, List<Message>>>(emptyMap())
    val conversations: StateFlow<Map<String, List<Message>>> = _conversations
    private val _nonLus = MutableStateFlow<Map<String, Int>>(emptyMap())
    val nonLus: StateFlow<Map<String, Int>> = _nonLus
    /** La conversation à l'écran : ce qui y arrive n'est pas « non lu ». */
    @Volatile var ouverte: String? = null

    suspend fun restaurer() {
        _conversations.value = app.magasin.lire(FICHIER)?.let { runCatching { json.decodeFromString(FORME, it) }.getOrNull() } ?: emptyMap()
    }

    /** Ce que la radio vient d'entendre : messages de canal (tous) et messages directs. */
    fun recevoir(messages: List<MessageRadio>, directs: List<MessageDirect>, pilote: PiloteRadio) {
        if (messages.isEmpty() && directs.isEmpty()) return
        val maintenant = System.currentTimeMillis()
        for (m in messages) {
            // MeshCore écrit « Nom: texte » ; Meshtastic ne dit pas qui parle sur un canal.
            val coupe = m.texte.indexOf(": ").takeIf { it in 1..32 }
            ajouter("c:${m.canal}", Message(false, coupe?.let { m.texte.substring(0, it) } ?: "", coupe?.let { m.texte.substring(it + 2) } ?: m.texte, maintenant))
        }
        for (d in directs) ajouter("d:${d.de}", Message(false, nomDuContact(d.de, pilote), d.texte, maintenant))
    }

    /** Parler sur un canal du nœud. */
    suspend fun envoyerSurCanal(index: Int, texte: String): Boolean {
        val p = app.radio.piloteCourant ?: return false
        val ok = app.radio.envoyerAdmin(p.envoyerSurCanal(index, app.radio.texteSelonLaZone(texte), System.currentTimeMillis() / 1000))
        ajouter("c:$index", Message(true, "Moi", texte, System.currentTimeMillis(), ok), compter = false)
        return ok
    }

    /** Message direct à un contact. */
    suspend fun envoyerDirect(contact: String, texte: String): Boolean {
        val p = app.radio.piloteCourant ?: return false
        val propre = app.radio.texteSelonLaZone(texte)
        val trames = when (p) {
            is PiloteMeshtastic -> contact.removePrefix("!").toLongOrNull(16)?.let { num ->
                Meshtastic.decouper(propre).map { Meshtastic.texte(num, it, (1L..0xffffffffL).random()) }
            }
            is PiloteMeshCore -> p.avance.contacts.keys.firstOrNull { it.startsWith(contact, ignoreCase = true) }?.let { cle ->
                listOf(MeshCore.envoyerMessage(cle, propre, System.currentTimeMillis() / 1000))
            }
            else -> null
        } ?: return false
        val ok = app.radio.envoyerAdmin(trames)
        ajouter("d:$contact", Message(true, "Moi", texte, System.currentTimeMillis(), ok), compter = false)
        return ok
    }

    fun marquerLue(cle: String) { _nonLus.value = _nonLus.value - cle }

    fun effacer(cle: String) {
        _conversations.value = _conversations.value - cle
        _nonLus.value = _nonLus.value - cle
        sauver()
    }

    suspend fun toutEffacer() { _conversations.value = emptyMap(); _nonLus.value = emptyMap(); app.magasin.effacer(FICHIER) }

    fun nomDuContact(contact: String, pilote: PiloteRadio? = app.radio.piloteCourant): String {
        val a = pilote?.avance ?: return contact
        return when (pilote) {
            is PiloteMeshtastic -> a.noeuds.values.firstOrNull { it.identifiant == contact }?.let { it.nomLong.ifBlank { it.nomCourt } } ?: contact
            is PiloteMeshCore -> a.contacts.values.firstOrNull { it.pubkeyHex.startsWith(contact, ignoreCase = true) }?.nom ?: contact.take(12)
            else -> contact
        }.ifBlank { contact }
    }

    private fun ajouter(cle: String, m: Message, compter: Boolean = true) {
        _conversations.value = _conversations.value + (cle to ((_conversations.value[cle] ?: emptyList()) + m).takeLast(MAX))
        if (compter && cle != ouverte) _nonLus.value = _nonLus.value + (cle to ((_nonLus.value[cle] ?: 0) + 1))
        sauver()
    }

    private fun sauver() {
        val instantane = _conversations.value
        portee.launch { app.magasin.ecrire(FICHIER, json.encodeToString(FORME, instantane)) }
    }

    private companion object {
        const val FICHIER = "radio-conversations"
        const val MAX = 200
        val FORME = MapSerializer(String.serializer(), ListSerializer(Message.serializer()))
    }
}
