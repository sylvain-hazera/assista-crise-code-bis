package fr.assistacrise.mobile

import fr.assistacrise.mobile.lien.Accuse
import fr.assistacrise.mobile.lien.MessageDirect
import fr.assistacrise.mobile.lien.MessageRadio
import fr.assistacrise.mobile.lien.PiloteMeshCore
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import fr.assistacrise.mobile.lien.PiloteRadio
import fr.assistacrise.mobile.lien.Protocole
import fr.assistacrise.mobile.lien.Reception
import fr.assistacrise.mobile.lien.StatutAccuse
import fr.assistacrise.mobile.domaine.ReactionsRadio
import fr.assistacrise.mobile.domaine.StatutEnvoiRadio
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
    /** Parmi les non-lus, ceux où l'on me mentionne (« @Léa »), par conversation (23/11/2026). */
    private val _mentions = MutableStateFlow<Map<String, Int>>(emptyMap())
    val mentions: StateFlow<Map<String, Int>> = _mentions
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
            // Une réaction émoji (Meshtastic) se pose sur le message visé, sans faire de bruit.
            if (m.reaction && m.repondA != 0L && reagir(k, m.repondA, texte, auteur)) continue
            // MeshCore (26/11/2026) : la réaction est un texte qui désigne le message par une empreinte.
            val rMc = if (pr == fr.assistacrise.mobile.lien.Protocole.MESHCORE) ReactionsRadio.lire(texte) else null
            if (rMc != null && (reagirMeshCore(k, rMc, auteur, canal = true, pilote) || rMc.format == ReactionsRadio.Format.OPEN)) continue
            val mention = app.alertes.estUneMention(texte)
            ajouter(k, recu(auteur, texte, maintenant, m.reception, m.id, m.repondA, m.horodatageS, nomRadio = auteur.ifBlank { null }), mention = mention)
            // Un canal d'équipe sonne déjà par la messagerie de l'équipe ; les autres sonnent
            // aussi, sauf ceux qu'on a fait taire (cloche) — 23/11/2026 : « un message reçu
            // n'émet pas de notification, il en faut ».
            // Canal de crise (23/11/2026) : ce qui est adressé à mon équipe sonne par sa messagerie,
            // ce qui est adressé à une autre équipe ne sonne pas ; un message sans adresse, si.
            val equipeDuCanal = app.radio.equipeDuCanal(pr, m.canal)
            val canalDeCrise = equipeDuCanal?.canalCrise?.let { cc ->
                pilote.canalNomme(cc.nomPour(pr == fr.assistacrise.mobile.lien.Protocole.MESHCORE))?.index == m.canal } == true
            val sansAdresse = !Regex("""(?:^|:\s)@[A-Za-z0-9]{2,8}\b""").containsMatchIn(m.texte)
            // Une mention sonne toujours, même sur un canal muet ou adressé à une autre équipe.
            if (mention || (k !in muets() && (equipeDuCanal == null || (canalDeCrise && sansAdresse)))) {
                val nom = pilote.canaux.firstOrNull { it.index == m.canal }?.nom ?: "Canal ${m.canal}"
                alerter(k, "« $nom » · ${pr.libelle}", FormatNotification.ligneRadio(auteur, texte))
                FormatNotification.urgenceTerrain(app, auteur, texte, CIBLE + k)
            }
        }
        for (d in directs) {
            val k = cle(pr, "d:${d.de}")
            val nom = nomDuContact(k)
            if (d.reaction && d.repondA != 0L && reagir(k, d.repondA, d.texte, nom)) continue
            val rMc = if (pr == fr.assistacrise.mobile.lien.Protocole.MESHCORE) ReactionsRadio.lire(d.texte) else null
            if (rMc != null && (reagirMeshCore(k, rMc, nom, canal = false, pilote) || rMc.format == ReactionsRadio.Format.OPEN)) continue
            ajouter(k, recu(nom, d.texte, maintenant, d.reception, d.id, d.repondA, d.horodatageS), mention = app.alertes.estUneMention(d.texte))
            alerter(k, "$nom · message direct ${pr.libelle}", FormatNotification.ligneRadio("", d.texte))
            FormatNotification.urgenceTerrain(app, nom, d.texte, CIBLE + k)
        }
    }

    /** Envoie sur la conversation désignée par sa clé (canal ou direct, sur la radio de son protocole).
     * `repondA` : le message auquel on répond (réponse native Meshtastic, en plus du `@[Nom]`). */
    suspend fun envoyer(cle: String, texte: String, repondA: Long = 0): Boolean {
        val (protocole, reste) = lireCle(cle) ?: return false
        val liaison = app.radio.pour(protocole)
        val p = liaison.piloteCourant?.takeIf { it.prete } ?: return false
        val propre = app.radio.texteSelonLaZone(texte)
        val maintenant = System.currentTimeMillis()
        var id = 0L
        val direct = reste.startsWith("d:")
        val secondes = maintenant / 1000
        val trames = when {
            reste.startsWith("c:") -> reste.removePrefix("c:").toIntOrNull()?.let { index ->
                if (p is PiloteMeshtastic) p.envoyerSurCanal(index, propre, repondA) else p.envoyerSurCanal(index, propre, maintenant / 1000)
            }
            p is PiloteMeshtastic -> reste.removePrefix("d:").removePrefix("!").toLongOrNull(16)?.let { num ->
                p.envoyerDirect(num, propre, repondA).let { (i, t) -> id = i; t }
            }
            p is PiloteMeshCore -> p.avance.contacts.keys.firstOrNull { it.startsWith(reste.removePrefix("d:"), ignoreCase = true) }?.let { pub ->
                id = (1L..Long.MAX_VALUE).random()
                listOf(p.envoyerDirect(pub, propre, maintenant / 1000, id))
            }
            else -> null
        } ?: return false
        val ok = liaison.envoyerAdmin(trames)
        // Un message direct attend son accusé ; sur un canal, personne n'accuse réception.
        val statut = if (!ok) StatutEnvoiRadio.ECHEC else StatutEnvoiRadio.PARTI
        // MeshCore : ce qu'il faut pour qu'une réaction à ce message nous revienne (heure
        // d'émission, mon nom radio sur un canal, texte tel qu'il est parti).
        val emis = when {
            p !is PiloteMeshCore -> null
            direct -> propre
            else -> p.morceaux(propre).firstOrNull()
        }
        ajouter(cle, Message(true, "Moi", texte, maintenant, ok, idRadio = if (direct) id else 0, repondA = repondA, statut = statut,
            horodatageRadio = if (p is PiloteMeshCore) secondes else 0, nomRadio = if (p is PiloteMeshCore && !direct) p.identite else null,
            texteEmis = emis?.takeIf { it != texte }), compter = false)
        return ok
    }

    /** Peut-on réagir à ce message ? Meshtastic : il faut son identifiant de paquet ; MeshCore :
     * son heure d'émission (les messages gardés avant le 26/11/2026 ne l'ont pas). */
    fun reactionPossible(cle: String, m: Message): Boolean = when (lireCle(cle)?.first) {
        Protocole.MESHTASTIC -> m.idRadio != 0L
        Protocole.MESHCORE -> m.horodatageRadio != 0L && (!cle.contains("|c:") || !(if (m.moi) app.radio.pour(Protocole.MESHCORE).piloteCourant?.identite else m.nomRadio).isNullOrBlank())
        null -> false
    }

    /** Réagit à un message par un émoji (26/11/2026) : réaction native en Meshtastic, texte au
     * format MeshCoreOne en MeshCore. Posée tout de suite sous le message, sans nouveau message. */
    suspend fun reagirA(cle: String, m: Message, emoji: String): Boolean {
        val (protocole, reste) = lireCle(cle) ?: return false
        if (!reactionPossible(cle, m)) return false
        val liaison = app.radio.pour(protocole)
        val p = liaison.piloteCourant?.takeIf { it.prete } ?: return false
        val canal = reste.startsWith("c:")
        val trames = when (p) {
            is PiloteMeshtastic ->
                if (canal) reste.removePrefix("c:").toIntOrNull()?.let { p.envoyerSurCanal(it, emoji, m.idRadio, reaction = true) }
                else reste.removePrefix("d:").removePrefix("!").toLongOrNull(16)?.let { p.envoyerDirect(it, emoji, m.idRadio, reaction = true).second }
            is PiloteMeshCore -> {
                val texte = ReactionsRadio.ecrire(emoji, m.texteRadio, m.horodatageRadio,
                    if (canal) (if (m.moi) p.identite else m.nomRadio) else null)
                val secondes = System.currentTimeMillis() / 1000
                if (canal) reste.removePrefix("c:").toIntOrNull()?.let { p.envoyerSurCanal(it, texte, secondes) }
                else p.avance.contacts.keys.firstOrNull { it.startsWith(reste.removePrefix("d:"), ignoreCase = true) }
                    ?.let { listOf(p.envoyerDirect(it, texte, secondes, (1L..Long.MAX_VALUE).random())) }
            }
            else -> null
        } ?: return false
        val ok = liaison.envoyerAdmin(trames)
        if (ok) {
            val liste = _conversations.value[cle] ?: return true
            val i = liste.indexOfLast { it === m || it == m }
            if (i >= 0) poser(cle, liste, i, emoji, "Moi")
        }
        return ok
    }

    /** Ce que la radio dit des messages envoyés : relayé, reçu (avec l'aller-retour) ou non remis. */
    fun accuser(accuses: List<Accuse>) {
        if (accuses.isEmpty()) return
        var change = false
        val maj = _conversations.value.mapValues { (_, liste) ->
            liste.map { m ->
                val a = accuses.firstOrNull { it.id == m.idRadio && m.moi && m.idRadio != 0L } ?: return@map m
                val statut = when (a.statut) { StatutAccuse.RECU -> StatutEnvoiRadio.RECU; StatutAccuse.RELAYE -> StatutEnvoiRadio.RELAYE; StatutAccuse.ECHEC -> StatutEnvoiRadio.ECHEC }
                // Un accusé de relais arrivé après la réception ne la défait pas.
                if (m.statut == StatutEnvoiRadio.RECU && statut != StatutEnvoiRadio.RECU) return@map m
                change = true
                m.copy(statut = statut, delaiMs = a.delaiMs ?: m.delaiMs)
            }
        }
        if (change) { _conversations.value = maj; sauver() }
    }

    private fun recu(auteur: String, texte: String, quand: Long, r: Reception?, id: Long, repondA: Long,
                     horodatageS: Long = 0, nomRadio: String? = null) = Message(
        false, auteur, texte, quand, sauts = r?.sauts, snr = r?.snr, rssi = r?.rssi,
        routeDirecte = r?.routeDirecte == true, parInternet = r?.parInternet == true, idRadio = id, repondA = repondA,
        horodatageRadio = horodatageS, nomRadio = nomRadio,
    )

    /** Pose une réaction sur le message `id` de la conversation ; faux si le message n'y est plus. */
    private fun reagir(cle: String, id: Long, emoji: String, auteur: String): Boolean {
        val liste = _conversations.value[cle] ?: return false
        val i = liste.indexOfLast { it.idRadio == id }.takeIf { it >= 0 } ?: return false
        poser(cle, liste, i, emoji, auteur)
        return true
    }

    /** MeshCore : retrouve le message que désigne l'empreinte (texte, heure d'émission et, sur un
     * canal, nom radio de l'auteur) et y pose la réaction ; faux s'il n'est pas (ou plus) là. */
    private fun reagirMeshCore(cle: String, r: ReactionsRadio.Lue, auteur: String, canal: Boolean, pilote: PiloteRadio): Boolean {
        val liste = _conversations.value[cle] ?: return false
        val i = liste.indexOfLast { m ->
            m.horodatageRadio != 0L && ReactionsRadio.vise(r, m.texteRadio, m.horodatageRadio,
                if (canal) (if (m.moi) m.nomRadio ?: pilote.identite else m.nomRadio) else null)
        }.takeIf { it >= 0 } ?: return false
        poser(cle, liste, i, r.emoji, auteur.ifBlank { "?" })
        return true
    }

    /** Ajoute l'auteur sous l'émoji du message `i` (une seule fois : une réaction relayée par
     * plusieurs répéteurs ne compte qu'une fois). */
    private fun poser(cle: String, liste: List<Message>, i: Int, emoji: String, auteur: String) {
        val m = liste[i]
        val qui = (m.reactions[emoji] ?: emptyList()).let { if (auteur in it) it else it + auteur }
        _conversations.value = _conversations.value + (cle to liste.toMutableList().also { it[i] = m.copy(reactions = m.reactions + (emoji to qui)) })
        sauver()
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
        _mentions.value = _mentions.value - cle
        app.alertes.retirerConversation(idNotification(cle))
    }

    fun effacer(cle: String) {
        _conversations.value = _conversations.value - cle
        _nonLus.value = _nonLus.value - cle
        _mentions.value = _mentions.value - cle
        sauver()
    }

    suspend fun toutEffacer() { _conversations.value = emptyMap(); _nonLus.value = emptyMap(); _mentions.value = emptyMap(); app.magasin.effacer(FICHIER) }

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

    private fun ajouter(cle: String, m: Message, compter: Boolean = true, mention: Boolean = false) {
        _conversations.value = _conversations.value + (cle to ((_conversations.value[cle] ?: emptyList()) + m).takeLast(MAX))
        if (compter && cle != ouverte) _nonLus.value = _nonLus.value + (cle to ((_nonLus.value[cle] ?: 0) + 1))
        if (mention && compter && cle != ouverte) _mentions.value = _mentions.value + (cle to ((_mentions.value[cle] ?: 0) + 1))
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
