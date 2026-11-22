package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.AdminMeshCore
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.AdminMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.CanalMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.Conteneur
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import fr.assistacrise.mobile.lien.meshtastic.NoeudMeshtastic

/** Un canal configuré sur la radio de l'intervenant. */
data class CanalRadio(val index: Int, val nom: String)

/** Un message entendu par la radio sur un canal. */
data class MessageRadio(val canal: Int, val texte: String)

/** Un message direct reçu (22/11/2026). `de` : « !1a2b3c4d » (Meshtastic) ou le préfixe de clé (MeshCore). */
data class MessageDirect(val de: String, val texte: String)

enum class Protocole(val libelle: String) { MESHCORE("MeshCore"), MESHTASTIC("Meshtastic") }

/**
 * Le dialogue avec une radio, sans rien savoir du Bluetooth.
 *
 * Un pilote est **passif** : on lui donne ce que la radio a dit, il rend ce qu'il faut lui
 * répondre. Aucune attente, aucun fil d'exécution — donc tout se teste sans radio, et la
 * couche Bluetooth n'a qu'à transporter des octets dans les deux sens.
 *
 * C'est aussi ici que s'arrête ce que l'application sait des deux protocoles : au-dessus,
 * on ne parle plus que de canaux et de messages (dossier § 4).
 */
abstract class PiloteRadio(val protocole: Protocole) {
    /** Le nom ou le numéro que la radio donne d'elle-même. */
    var identite: String? = null; protected set

    /** Vrai quand la radio a fini de se décrire : ses canaux sont connus. */
    var prete: Boolean = false; protected set

    protected val canauxConnus = LinkedHashMap<Int, String>()
    val canaux: List<CanalRadio> get() = canauxConnus.map { CanalRadio(it.key, it.value) }

    /** Ce qu'il faut écrire à la radio juste après la connexion. */
    abstract fun ouverture(secondesUnix: Long): List<ByteArray>

    /** Une trame arrive : ce qu'il faut répondre, et les messages de canal qu'elle porte. */
    abstract fun recevoir(trame: ByteArray): Reaction

    /** À écrire toutes les `periodeBattementMs`, ou rien si le protocole n'en veut pas. */
    open fun battement(): ByteArray? = null
    open val periodeBattementMs: Long get() = 0

    /** Les trames qui portent ce texte sur ce canal. Plusieurs si le texte est long. */
    abstract fun envoyerSurCanal(index: Int, texte: String, secondesUnix: Long): List<ByteArray>

    /** Le canal de la radio qui porte ce nom, à la casse et au « # » près. */
    fun canalNomme(nom: String?): CanalRadio? {
        val cherche = nom?.trim()?.removePrefix("#")?.lowercase()?.takeIf { it.isNotEmpty() } ?: return null
        return canaux.firstOrNull { it.nom.trim().removePrefix("#").lowercase() == cherche }
    }

    class Reaction(
        val aEcrire: List<ByteArray> = emptyList(),
        val messages: List<MessageRadio> = emptyList(),
        val directs: List<MessageDirect> = emptyList(),
    )

    /**
     * « Utilisateur radio avancé » (22/11/2026) : tout ce que la radio a décrit d'elle-même,
     * réglages, canaux complets, contacts. `version` augmente à chaque nouveauté : la liaison
     * s'en sert pour rafraîchir l'écran.
     */
    data class Avance(
        val version: Int = 0,
        // Meshtastic
        val monNoeud: Long? = null,
        val reglages: Map<Pair<Conteneur, Int>, ByteArray> = emptyMap(),
        val canauxMeshtastic: Map<Int, CanalMeshtastic> = emptyMap(),
        val noeuds: Map<Long, NoeudMeshtastic> = emptyMap(),
        val proprietaire: Pair<String, String>? = null,
        // MeshCore
        val moi: AdminMeshCore.Moi? = null,
        val canauxMeshCore: Map<Int, AdminMeshCore.CanalComplet> = emptyMap(),
        val contacts: Map<String, AdminMeshCore.Contact> = emptyMap(),
        val carte: ByteArray? = null,
        /** Dernière réponse à une commande (« OK », « refusée par la radio »). */
        val derniereReponse: String? = null,
    )

    var avance: Avance = Avance(); protected set

    protected fun noter(maj: (Avance) -> Avance) { avance = maj(avance).let { it.copy(version = it.version + 1) } }
}

class PiloteMeshCore : PiloteRadio(Protocole.MESHCORE) {
    override fun ouverture(secondesUnix: Long): List<ByteArray> = listOf(
        MeshCore.appStart(),
        MeshCore.reglerHeure(secondesUnix),
        MeshCore.demanderCanal(0),
    )

    override fun recevoir(trame: ByteArray): Reaction {
        if (trame.isEmpty()) return Reaction()
        return when (trame[0].toInt() and 0xff) {
            MeshCore.Rep.SELF_INFO -> {
                identite = MeshCore.lireSelfInfo(trame)?.nom
                AdminMeshCore.lireMoi(trame)?.let { moi -> noter { it.copy(moi = moi) } }
                Reaction()
            }
            AdminMeshCore.Rep.CONTACT_START -> { noter { it.copy(contacts = emptyMap()) }; Reaction() }
            AdminMeshCore.Rep.CONTACT, AdminMeshCore.Rep.NEW_ADVERT -> {
                AdminMeshCore.lireContact(trame)?.let { c -> noter { it.copy(contacts = it.contacts + (c.pubkeyHex to c)) } }
                Reaction()
            }
            AdminMeshCore.Rep.CONTACT_URI -> { AdminMeshCore.lireCarte(trame)?.let { c -> noter { it.copy(carte = c) } }; Reaction() }
            MeshCore.Rep.OK -> { if (prete) noter { it.copy(derniereReponse = "OK") }; Reaction() }
            MeshCore.Rep.CHANNEL_INFO -> {
                val canal = MeshCore.lireCanal(trame) ?: return Reaction()
                AdminMeshCore.lireCanalComplet(trame)?.let { c ->
                    noter { it.copy(canauxMeshCore = if (c.nom.isBlank()) it.canauxMeshCore - c.index else it.canauxMeshCore + (c.index to c)) }
                }
                if (canal.nom.isNotBlank()) canauxConnus[canal.index] = canal.nom else canauxConnus.remove(canal.index)
                // Après l'ouverture, une relecture isolée d'un emplacement ne relance pas le balayage.
                if (prete) return Reaction()
                // On lit les emplacements un par un : un emplacement vide n'arrête rien, les
                // canaux ne sont pas forcément rangés à la suite.
                if (canal.index + 1 < MeshCore.EMPLACEMENTS) Reaction(listOf(MeshCore.demanderCanal(canal.index + 1)))
                else finDeLecture()
            }
            // La radio refuse l'emplacement suivant : elle en a moins que prévu.
            MeshCore.Rep.ERROR -> if (!prete) finDeLecture() else { noter { it.copy(derniereReponse = "Refusée par la radio") }; Reaction() }
            MeshCore.Rep.MESSAGES_WAITING -> Reaction(listOf(suivant()))
            MeshCore.Rep.CHANNEL_MSG_RECV, MeshCore.Rep.CHANNEL_MSG_RECV_V3 -> {
                val m = MeshCore.lireMessageCanal(trame)
                Reaction(listOf(suivant()), listOfNotNull(m?.let { MessageRadio(it.canal, it.texte) }))
            }
            // Un message direct : il entre dans la messagerie radio, et on continue de vider.
            MeshCore.Rep.CONTACT_MSG_RECV, MeshCore.Rep.CONTACT_MSG_RECV_V3 -> {
                val m = MeshCore.lireMessageRecu(trame)
                Reaction(listOf(suivant()), directs = listOfNotNull(m?.let { MessageDirect(it.prefixeExpediteurHex, it.texte) }))
            }
            else -> Reaction()
        }
    }

    /** Les canaux sont connus : on vide ce que la radio a reçu pendant qu'on n'écoutait pas. */
    private fun finDeLecture(): Reaction { prete = true; return Reaction(listOf(suivant(), AdminMeshCore.demanderContacts())) }

    private fun suivant() = MeshCore.commandeSimple(MeshCore.Cmd.SYNC_NEXT_MESSAGE)

    /** Relit tout ce que l'écran avancé affiche : identité et réglages, canaux, contacts. */
    fun relireTout(): List<ByteArray> =
        listOf(MeshCore.appStart(), AdminMeshCore.demanderContacts()) + (0 until MeshCore.EMPLACEMENTS).map { MeshCore.demanderCanal(it) }

    override fun envoyerSurCanal(index: Int, texte: String, secondesUnix: Long): List<ByteArray> =
        // 7 octets d'en-tête ; on garde de la marge pour le nom que la radio ajoute.
        Meshtastic.decouper(texte, MeshCore.TRAME_MAX - 7 - 40).map { MeshCore.envoyerSurCanal(index, it, secondesUnix) }
}

class PiloteMeshtastic(private val identifiant: () -> Long) : PiloteRadio(Protocole.MESHTASTIC) {
    private var nonce = Meshtastic.PREMIER_NONCE_BATTEMENT

    override fun ouverture(secondesUnix: Long): List<ByteArray> = listOf(Meshtastic.veutConfig(Meshtastic.NONCE_CONFIG))

    override fun recevoir(trame: ByteArray): Reaction {
        when (val lu = AdminMeshtastic.lire(trame)) {
            is AdminMeshtastic.Lu.Config -> noter { it.copy(reglages = it.reglages + ((lu.conteneur to lu.numero) to lu.contenu)) }
            is AdminMeshtastic.Lu.Canal -> noter { it.copy(canauxMeshtastic = it.canauxMeshtastic + (lu.canal.index to lu.canal)) }
            is AdminMeshtastic.Lu.Noeud -> noter { it.copy(noeuds = it.noeuds + (lu.noeud.numero to lu.noeud)) }
            is AdminMeshtastic.Lu.Proprietaire -> noter { it.copy(proprietaire = lu.nomLong to lu.nomCourt) }
            null -> Unit
        }
        val evenement = runCatching { Meshtastic.lire(trame) }.getOrNull() ?: return Reaction()
        return when (evenement) {
            is Meshtastic.Evenement.MonNoeud -> {
                identite = "!" + evenement.numero.toString(16).padStart(8, '0')
                noter { it.copy(monNoeud = evenement.numero) }
                Reaction()
            }
            is Meshtastic.Evenement.Canal -> {
                // Le canal primaire n'a souvent pas de nom : c'est celui du préréglage radio.
                if (evenement.role != 0) canauxConnus[evenement.index] = evenement.nom.ifBlank { "Primaire" }
                Reaction()
            }
            is Meshtastic.Evenement.ConfigTerminee -> when (evenement.identifiant) {
                // Deux temps, un battement entre les deux, et jamais deux fois la même demande.
                Meshtastic.NONCE_CONFIG -> Reaction(listOf(battement(), Meshtastic.veutConfig(Meshtastic.NONCE_NOEUDS)))
                Meshtastic.NONCE_NOEUDS -> { prete = true; Reaction() }
                else -> Reaction()
            }
            is Meshtastic.Evenement.Texte ->
                if (evenement.vers == Meshtastic.DIFFUSION) Reaction(messages = listOf(MessageRadio(evenement.canal, evenement.texte)))
                // Adressé à mon nœud : un message direct.
                else if (evenement.vers == avance.monNoeud) Reaction(directs = listOf(MessageDirect("!" + evenement.de.toString(16).padStart(8, '0'), evenement.texte)))
                else Reaction()
            else -> Reaction()
        }
    }

    /** Un message d'administration pour la radio connectée, enveloppé pour le nœud local. */
    fun admin(message: ByteArray): ByteArray? = avance.monNoeud?.let { AdminMeshtastic.paquet(it, message, identifiant()) }

    /** Écrire des réglages : encadré par « début / validation d'édition », comme les applications officielles. */
    fun adminGroupe(messages: List<ByteArray>): List<ByteArray> =
        (listOf(AdminMeshtastic.commencerEdition()) + messages + AdminMeshtastic.validerEdition()).mapNotNull(::admin)

    /** Relit toute la configuration (la radio la redécrit, nœuds compris). */
    fun relireTout(): List<ByteArray> = listOf(Meshtastic.veutConfig(Meshtastic.NONCE_CONFIG))

    override fun battement(): ByteArray = Meshtastic.battement(nonce).also { nonce = Meshtastic.nonceSuivant(nonce) }
    override val periodeBattementMs: Long get() = Meshtastic.PERIODE_BATTEMENT_MS

    override fun envoyerSurCanal(index: Int, texte: String, secondesUnix: Long): List<ByteArray> =
        Meshtastic.decouper(texte).map { Meshtastic.texte(Meshtastic.DIFFUSION, it, identifiant(), canal = index, accuse = false) }
}
