package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic

/** Un canal configuré sur la radio de l'intervenant. */
data class CanalRadio(val index: Int, val nom: String)

/** Un message entendu par la radio sur un canal. */
data class MessageRadio(val canal: Int, val texte: String)

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

    class Reaction(val aEcrire: List<ByteArray> = emptyList(), val messages: List<MessageRadio> = emptyList())
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
            MeshCore.Rep.SELF_INFO -> { identite = MeshCore.lireSelfInfo(trame)?.nom; Reaction() }
            MeshCore.Rep.CHANNEL_INFO -> {
                val canal = MeshCore.lireCanal(trame) ?: return Reaction()
                if (canal.nom.isNotBlank()) canauxConnus[canal.index] = canal.nom
                // On lit les emplacements un par un : un emplacement vide n'arrête rien, les
                // canaux ne sont pas forcément rangés à la suite.
                if (canal.index + 1 < MeshCore.EMPLACEMENTS) Reaction(listOf(MeshCore.demanderCanal(canal.index + 1)))
                else finDeLecture()
            }
            // La radio refuse l'emplacement suivant : elle en a moins que prévu.
            MeshCore.Rep.ERROR -> if (!prete) finDeLecture() else Reaction()
            MeshCore.Rep.MESSAGES_WAITING -> Reaction(listOf(suivant()))
            MeshCore.Rep.CHANNEL_MSG_RECV, MeshCore.Rep.CHANNEL_MSG_RECV_V3 -> {
                val m = MeshCore.lireMessageCanal(trame)
                Reaction(listOf(suivant()), listOfNotNull(m?.let { MessageRadio(it.canal, it.texte) }))
            }
            // Un message direct : pas notre affaire ici, mais il faut continuer de vider.
            MeshCore.Rep.CONTACT_MSG_RECV, MeshCore.Rep.CONTACT_MSG_RECV_V3 -> Reaction(listOf(suivant()))
            else -> Reaction()
        }
    }

    /** Les canaux sont connus : on vide ce que la radio a reçu pendant qu'on n'écoutait pas. */
    private fun finDeLecture(): Reaction { prete = true; return Reaction(listOf(suivant())) }

    private fun suivant() = MeshCore.commandeSimple(MeshCore.Cmd.SYNC_NEXT_MESSAGE)

    override fun envoyerSurCanal(index: Int, texte: String, secondesUnix: Long): List<ByteArray> =
        // 7 octets d'en-tête ; on garde de la marge pour le nom que la radio ajoute.
        Meshtastic.decouper(texte, MeshCore.TRAME_MAX - 7 - 40).map { MeshCore.envoyerSurCanal(index, it, secondesUnix) }
}

class PiloteMeshtastic(private val identifiant: () -> Long) : PiloteRadio(Protocole.MESHTASTIC) {
    private var nonce = Meshtastic.PREMIER_NONCE_BATTEMENT

    override fun ouverture(secondesUnix: Long): List<ByteArray> = listOf(Meshtastic.veutConfig(Meshtastic.NONCE_CONFIG))

    override fun recevoir(trame: ByteArray): Reaction {
        val evenement = runCatching { Meshtastic.lire(trame) }.getOrNull() ?: return Reaction()
        return when (evenement) {
            is Meshtastic.Evenement.MonNoeud -> { identite = "!" + evenement.numero.toString(16).padStart(8, '0'); Reaction() }
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
                // Seuls les messages de canal nous intéressent : adressés à tous.
                if (evenement.vers == Meshtastic.DIFFUSION) Reaction(messages = listOf(MessageRadio(evenement.canal, evenement.texte)))
                else Reaction()
            else -> Reaction()
        }
    }

    override fun battement(): ByteArray = Meshtastic.battement(nonce).also { nonce = Meshtastic.nonceSuivant(nonce) }
    override val periodeBattementMs: Long get() = Meshtastic.PERIODE_BATTEMENT_MS

    override fun envoyerSurCanal(index: Int, texte: String, secondesUnix: Long): List<ByteArray> =
        Meshtastic.decouper(texte).map { Meshtastic.texte(Meshtastic.DIFFUSION, it, identifiant(), canal = index, accuse = false) }
}
