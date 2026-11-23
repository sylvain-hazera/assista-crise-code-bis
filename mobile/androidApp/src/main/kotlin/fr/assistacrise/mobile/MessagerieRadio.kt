package fr.assistacrise.mobile

import fr.assistacrise.mobile.lien.MessageDirect
import fr.assistacrise.mobile.lien.MessageRadio
import fr.assistacrise.mobile.lien.PiloteMeshCore
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import fr.assistacrise.mobile.lien.PiloteRadio
import fr.assistacrise.mobile.lien.Protocole
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
 * Une conversation se désigne par une clé : `<PROTOCOLE>|c:<index>` (canal) ou
 * `<PROTOCOLE>|d:<contact>` (direct, le contact étant « !1a2b3c4d » en Meshtastic ou le préfixe
 * de clé publique en MeshCore). Le protocole en tête, parce qu'un téléphone peut tenir les deux
 * radios à la fois (23/11/2026) : le canal 0 de l'une n'est pas celui de l'autre. Gardée dans le
 * magasin chiffré du téléphone, 200 messages par conversation au plus.
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
        val pr = pilote.protocole
        for (m in messages) {
            // MeshCore écrit « Nom: texte » ; Meshtastic donne l'émetteur à part (nœud « !1a2b3c4d »).
            val coupe = if (m.de != null) null else m.texte.indexOf(": ").takeIf { it in 1..32 }
            val auteur = m.de?.let { nomDuContact(cle(pr, "d:$it")) } ?: coupe?.let { m.texte.substring(0, it) } ?: ""
            val texte = coupe?.let { m.texte.substring(it + 2) } ?: m.texte
            val k = cle(pr, "c:${m.canal}")
            ajouter(k, Message(false, auteur, texte, maintenant))
            // Un canal d'équipe sonne déjà par la messagerie de l'équipe ; les autres sonnent
            // aussi, sauf ceux qu'on a fait taire (cloche) — 23/11/2026 : « un message reçu
            // n'émet pas de notification, il en faut ».
            if (k !in muets() && app.radio.equipeDuCanal(pr, m.canal) == null) {
                val nom = pilote.canaux.firstOrNull { it.index == m.canal }?.nom ?: "Canal ${m.canal}"
                alerter(k, "« $nom » · ${pr.libelle}", FormatNotification.ligneRadio(auteur, texte))
                FormatNotification.urgenceTerrain(app, auteur, texte, CIBLE + k)
            }
        }
        for (d in directs) {
            val k = cle(pr, "d:${d.de}")
            val nom = nomDuContact(k)
            ajouter(k, Message(false, nom, d.texte, maintenant))
            alerter(k, "$nom · message direct ${pr.libelle}", FormatNotification.ligneRadio("", d.texte))
            FormatNotification.urgenceTerrain(app, nom, d.texte, CIBLE + k)
        }
    }

    /** Envoie sur la conversation désignée par sa clé (canal ou direct, sur la radio de son protocole). */
    suspend fun envoyer(cle: String, texte: String): Boolean {
        val (protocole, reste) = lireCle(cle) ?: return false
        val liaison = app.radio.pour(protocole)
        val p = liaison.piloteCourant?.takeIf { it.prete } ?: return false
        val propre = app.radio.texteSelonLaZone(texte)
        val maintenant = System.currentTimeMillis()
        val trames = when {
            reste.startsWith("c:") -> reste.removePrefix("c:").toIntOrNull()?.let { p.envoyerSurCanal(it, propre, maintenant / 1000) }
            p is PiloteMeshtastic -> reste.removePrefix("d:").removePrefix("!").toLongOrNull(16)?.let { num ->
                Meshtastic.decouper(propre).map { Meshtastic.texte(num, it, (1L..0xffffffffL).random()) }
            }
            p is PiloteMeshCore -> p.avance.contacts.keys.firstOrNull { it.startsWith(reste.removePrefix("d:"), ignoreCase = true) }?.let { pub ->
                listOf(MeshCore.envoyerMessage(pub, propre, maintenant / 1000))
            }
            else -> null
        } ?: return false
        val ok = liaison.envoyerAdmin(trames)
        ajouter(cle, Message(true, "Moi", texte, maintenant, ok), compter = false)
        return ok
    }

    /** Une notification par conversation, mise à jour à chaque message (Alertes.conversation). */
    private fun alerter(cle: String, titre: String, texte: String) {
        if (app.premierPlan && ouverte == cle) return
        app.alertes.conversation(idNotification(cle), titre, texte, fr.assistacrise.mobile.domaine.Alerte.Genre.MESSAGE, CIBLE + cle)
    }

    // Les canaux qu'on a fait taire : un choix d'affichage, pas une donnée personnelle. Tous les
    // canaux sonnent par défaut (23/11/2026) ; les messages directs sonnent toujours.
    private val preferences by lazy { app.getSharedPreferences("radio", android.content.Context.MODE_PRIVATE) }
    private fun muets(): Set<String> = preferences.getStringSet("canaux-muets", emptySet()) ?: emptySet()
    fun notifie(cle: String) = cle.contains("|d:") || cle !in muets()
    fun notifier(cle: String, oui: Boolean) {
        preferences.edit().putStringSet("canaux-muets", if (oui) muets() - cle else muets() + cle).apply()
    }

    fun marquerLue(cle: String) {
        _nonLus.value = _nonLus.value - cle
        app.alertes.retirerConversation(idNotification(cle))
    }

    fun effacer(cle: String) {
        _conversations.value = _conversations.value - cle
        _nonLus.value = _nonLus.value - cle
        sauver()
    }

    suspend fun toutEffacer() { _conversations.value = emptyMap(); _nonLus.value = emptyMap(); app.magasin.effacer(FICHIER) }

    /** Le nom d'un contact, d'après sa clé de conversation directe. */
    fun nomDuContact(cleConversation: String): String {
        val (protocole, reste) = lireCle(cleConversation) ?: return cleConversation
        val contact = reste.removePrefix("d:")
        val a = app.radio.pour(protocole).avance.value
        return when (protocole) {
            Protocole.MESHTASTIC -> a.noeuds.values.firstOrNull { it.identifiant == contact }?.let { it.nomLong.ifBlank { it.nomCourt } }
            Protocole.MESHCORE -> a.contacts.values.firstOrNull { it.pubkeyHex.startsWith(contact, ignoreCase = true) }?.nom
        }?.ifBlank { null } ?: contact.take(12)
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

    companion object {
        /** Préfixe de la cible d'une notification qui ouvre une conversation radio. */
        const val CIBLE = "radio:"
        fun idNotification(cle: String) = "radio-conv:$cle"
        fun cle(protocole: Protocole, reste: String) = "${protocole.name}|$reste"
        fun lireCle(cle: String): Pair<Protocole, String>? {
            val (p, reste) = cle.split("|", limit = 2).takeIf { it.size == 2 } ?: return null
            return (Protocole.entries.firstOrNull { it.name == p } ?: return null) to reste
        }
        private const val FICHIER = "radio-conversations"
        private const val MAX = 200
        private val FORME = MapSerializer(String.serializer(), ListSerializer(Message.serializer()))
    }
}
