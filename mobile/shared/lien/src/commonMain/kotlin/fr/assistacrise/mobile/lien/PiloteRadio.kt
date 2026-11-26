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

/**
 * Comment un message est arrivé (26/11/2026, « voir le nombre de sauts n'est pas implanté ») :
 * nombre de sauts (relais traversés), signal du dernier saut, passage par Internet. Ce que les
 * applications officielles affichent sous chaque message.
 * - MeshCore : `path_len` des trames V3 (6 bits bas = sauts ; 0xFF = arrivé par route directe) et SNR ;
 * - Meshtastic : `hop_start - hop_limit`, `rx_snr`, `rx_rssi`, `via_mqtt`.
 */
data class Reception(
    val sauts: Int? = null,
    val snr: Float? = null,
    val rssi: Int? = null,
    /** MeshCore : arrivé par une route directe connue (le nombre de sauts n'est pas transmis). */
    val routeDirecte: Boolean = false,
    /** Meshtastic : passé par un serveur MQTT (Internet) en chemin. */
    val parInternet: Boolean = false,
)

/** Un message entendu par la radio sur un canal. */
/** `de` : l'émetteur quand le protocole le dit (Meshtastic : « !1a2b3c4d ») ; MeshCore l'écrit dans le texte (« Nom: … »).
 * `id` : identifiant Meshtastic du paquet (0 en MeshCore) ; `repondA` : le message auquel il répond (Meshtastic `reply_id`) ;
 * `reaction` : vrai si le texte est un émoji posé sur `repondA` (Meshtastic `emoji`). */
data class MessageRadio(
    val canal: Int, val texte: String, val de: String? = null, val reception: Reception? = null,
    val id: Long = 0, val repondA: Long = 0, val reaction: Boolean = false,
    /** MeshCore : heure d'émission (secondes Unix) portée par la trame ; sert aux réactions. */
    val horodatageS: Long = 0,
)

/** Un message direct reçu (22/11/2026). `de` : « !1a2b3c4d » (Meshtastic) ou le préfixe de clé (MeshCore). */
data class MessageDirect(
    val de: String, val texte: String, val reception: Reception? = null,
    val id: Long = 0, val repondA: Long = 0, val reaction: Boolean = false,
    val horodatageS: Long = 0,
)

/** Ce que devient un message envoyé (26/11/2026). */
enum class StatutAccuse { RELAYE, RECU, ECHEC }

/** Un accusé pour un message envoyé : `id` est celui donné à l'envoi (paquet Meshtastic, ou
 * identifiant local d'un message direct MeshCore). `delaiMs` : aller-retour, quand la radio le dit. */
data class Accuse(val id: Long, val statut: StatutAccuse, val delaiMs: Long? = null, val raison: String? = null)

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
        val accuses: List<Accuse> = emptyList(),
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
        /** Batterie de la radio connectée, en millivolts (MeshCore : demandée ; Meshtastic : fiche de mon nœud). */
        val batterieMv: Int? = null,
        /** Meshtastic : niveau de batterie de mon nœud, en % (101 = sur secteur). */
        val batteriePourcent: Int? = null,
        /** Meshtastic : dernières routes tracées, par nœud (26/11/2026). */
        val trajets: Map<Long, Meshtastic.Evenement.Trajet> = emptyMap(),
        /** MeshCore : dernières traces de chemin, par clé publique du contact (26/11/2026). */
        val tracesMeshCore: Map<String, TraceMeshCore> = emptyMap(),
        /** MeshCore : répéteurs et salons administrés à distance, par clé publique (26/11/2026). */
        val repeteurs: Map<String, SessionRepeteur> = emptyMap(),
        /** Dernière réponse à une commande (« OK », « refusée par la radio »). */
        val derniereReponse: String? = null,
    )

    /** Une trace MeshCore demandée : où elle en est, et ce qu'elle a rapporté. `jusquALaCible` :
     * faux pour un compagnon (il ne relaie pas) — la trace s'arrête alors à son dernier relais. */
    data class TraceMeshCore(
        val etat: EtatTrace, val demandeeMs: Long, val jusquALaCible: Boolean,
        val delaiEstimeMs: Long? = null, val resultat: AdminMeshCore.Trace? = null, val raison: String? = null,
    )

    enum class EtatTrace { DEMANDEE, PARTIE, REVENUE, ECHEC }

    /** Une session d'administration d'un répéteur MeshCore : connexion, dernier statut, console. */
    data class SessionRepeteur(
        val etat: EtatSession, val depuisMs: Long, val admin: Boolean = false, val role: Int? = null,
        val statut: AdminMeshCore.StatutRepeteur? = null, val statutDemandeMs: Long? = null,
        val console: List<LigneConsole> = emptyList(), val raison: String? = null,
    )

    enum class EtatSession { CONNEXION, CONNECTEE, REFUSEE, FERMEE }

    /** Une ligne de la console : commande envoyée (`moi`) ou réponse du répéteur. */
    data class LigneConsole(val moi: Boolean, val texte: String, val ms: Long)

    var avance: Avance = Avance(); protected set

    protected fun noter(maj: (Avance) -> Avance) { avance = maj(avance).let { it.copy(version = it.version + 1) } }
}

class PiloteMeshCore(private val horloge: () -> Long = { 0L }) : PiloteRadio(Protocole.MESHCORE) {
    /** Messages directs envoyés, dans l'ordre, en attente de leur `MSG_SENT` : (id local, heure). */
    private val directsEnAttente = ArrayDeque<Pair<Long, Long>>()
    /** Code d'accusé attendu → id local du message direct. */
    private val accusesAttendus = LinkedHashMap<Long, Long>()

    /** Un message direct : la trame, et l'id local qu'on retrouvera dans l'accusé de réception. */
    fun envoyerDirect(pubkeyHex: String, texte: String, secondesUnix: Long, idLocal: Long): ByteArray =
        MeshCore.envoyerMessage(pubkeyHex, texte, secondesUnix).also { directsEnAttente.addLast(idLocal to horloge()) }

    /** Tension de la batterie de la radio (réponse : `batterieMv`). */
    fun demanderBatterie() = MeshCore.commandeSimple(MeshCore.Cmd.GET_BATT_AND_STORAGE)

    /** Repères dans la file des envois en attente de `RESP_CODE_SENT` : ces commandes y répondent
     * comme un message direct, mais n'attendent pas d'accusé. (marque, clé du contact). */
    private val marques = LinkedHashMap<Long, String>()
    private var prochaineMarque = -1L
    private fun marquer(pubkeyHex: String): Long {
        val m = prochaineMarque--
        if (prochaineMarque < -1_000_000) prochaineMarque = -1
        marques[m] = pubkeyHex
        while (marques.size > 32) marques.remove(marques.keys.first())
        directsEnAttente.addLast(m to horloge())
        return m
    }

    private fun session(pubkeyHex: String, maj: (SessionRepeteur?) -> SessionRepeteur) =
        noter { it.copy(repeteurs = it.repeteurs + (pubkeyHex to maj(it.repeteurs[pubkeyHex]))) }

    private fun parPrefixe(prefixeHex: String): String? =
        avance.contacts.keys.firstOrNull { it.startsWith(prefixeHex, ignoreCase = true) }

    /** Connexion à un répéteur ou un salon (mot de passe d'administration ou d'invité). Le mot de
     * passe n'est gardé nulle part : il part dans la trame, la radio le chiffre. */
    fun seConnecter(pubkeyHex: String, motDePasse: String): ByteArray {
        marquer(pubkeyHex)
        session(pubkeyHex) { (it ?: SessionRepeteur(EtatSession.CONNEXION, horloge())).copy(etat = EtatSession.CONNEXION, depuisMs = horloge(), raison = null) }
        return AdminMeshCore.connexion(pubkeyHex, motDePasse)
    }

    fun demanderStatutRepeteur(pubkeyHex: String): ByteArray {
        marquer(pubkeyHex)
        session(pubkeyHex) { (it ?: SessionRepeteur(EtatSession.FERMEE, horloge())).copy(statutDemandeMs = horloge()) }
        return AdminMeshCore.demanderStatut(pubkeyHex)
    }

    /** Une commande pour la ligne de commande du répéteur (il faut y être connecté en administrateur). */
    fun commandeRepeteur(pubkeyHex: String, texte: String, secondesUnix: Long): ByteArray {
        marquer(pubkeyHex)
        session(pubkeyHex) { s -> (s ?: SessionRepeteur(EtatSession.FERMEE, horloge())).let { it.copy(console = (it.console + LigneConsole(true, texte, horloge())).takeLast(100)) } }
        return MeshCore.envoyerMessage(pubkeyHex, texte, secondesUnix, typeTexte = 1)
    }

    fun seDeconnecter(pubkeyHex: String): ByteArray {
        session(pubkeyHex) { (it ?: SessionRepeteur(EtatSession.FERMEE, horloge())).copy(etat = EtatSession.FERMEE, depuisMs = horloge()) }
        return AdminMeshCore.deconnexion(pubkeyHex)
    }

    /** Trace en cours : (tag, clé du contact). Une seule à la fois, comme dans meshcore-open. */
    private var traceEnCours: Pair<Long, String>? = null

    /**
     * Trace le chemin vers un contact (réponse : `avance.tracesMeshCore[clé]`). Un répéteur ou
     * un salon est tracé jusqu'à lui ; un compagnon, jusqu'à son dernier relais. Null si le chemin
     * n'est pas connu (contact joint en inondation) ou contient un relais inconnu.
     */
    fun tracer(pubkeyHex: String): ByteArray? {
        val cible = avance.contacts[pubkeyHex] ?: return null
        val jusquALaCible = cible.type == 2 || cible.type == 3
        val (chemin, largeur) = AdminMeshCore.cheminDeTrace(cible, avance.contacts.values, jusquALaCible) ?: return null
        val tag = ((horloge() / 1000) and 0xffffffffL).takeIf { it != 0L } ?: 1L
        traceEnCours = tag to pubkeyHex
        noter { it.copy(tracesMeshCore = it.tracesMeshCore + (pubkeyHex to TraceMeshCore(EtatTrace.DEMANDEE, horloge(), jusquALaCible))) }
        return AdminMeshCore.traceroute(tag, chemin, largeur)
    }

    private fun majTrace(maj: (TraceMeshCore) -> TraceMeshCore) {
        val cle = traceEnCours?.second ?: return
        noter { a -> a.tracesMeshCore[cle]?.let { a.copy(tracesMeshCore = a.tracesMeshCore + (cle to maj(it))) } ?: a }
    }

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
            MeshCore.Rep.ERROR -> if (!prete) finDeLecture() else {
                noter { it.copy(derniereReponse = "Refusée par la radio") }
                // Un refus juste après une demande de trace la concerne (chemin trop long, file pleine).
                val cle = traceEnCours?.second
                val t = cle?.let { avance.tracesMeshCore[it] }
                if (t != null && t.etat == EtatTrace.DEMANDEE && horloge() - t.demandeeMs < 5_000) {
                    majTrace { it.copy(etat = EtatTrace.ECHEC, raison = "refusée par la radio") }
                    traceEnCours = null
                    return Reaction()
                }
                // Un refus juste après un message direct le concerne (contact inconnu, file pleine).
                val envoi = directsEnAttente.firstOrNull()?.takeIf { horloge() - it.second < 5_000 }
                if (envoi != null && envoi.first < 0) {
                    directsEnAttente.removeFirst()
                    marques.remove(envoi.first)?.let { cle ->
                        session(cle) { s -> (s ?: SessionRepeteur(EtatSession.FERMEE, horloge())).let {
                            if (it.etat == EtatSession.CONNEXION) it.copy(etat = EtatSession.REFUSEE, raison = "refusée par la radio (contact inconnu ou file pleine)")
                            else it.copy(statutDemandeMs = null, raison = "commande refusée par la radio") } }
                    }
                    Reaction()
                }
                else if (envoi != null) { directsEnAttente.removeFirst(); Reaction(accuses = listOf(Accuse(envoi.first, StatutAccuse.ECHEC, raison = "refusé par la radio"))) }
                else Reaction()
            }
            MeshCore.Rep.MESSAGES_WAITING -> Reaction(listOf(suivant()))
            MeshCore.Rep.CHANNEL_MSG_RECV, MeshCore.Rep.CHANNEL_MSG_RECV_V3 -> {
                val m = MeshCore.lireMessageCanal(trame)
                Reaction(listOf(suivant()), listOfNotNull(m?.let { MessageRadio(it.canal, it.texte, reception = it.reception, horodatageS = it.horodatageS) }))
            }
            // Un message direct : il entre dans la messagerie radio, et on continue de vider.
            MeshCore.Rep.CONTACT_MSG_RECV, MeshCore.Rep.CONTACT_MSG_RECV_V3 -> {
                val m = MeshCore.lireMessageRecu(trame)
                // Réponse de la ligne de commande d'un répéteur : dans sa console, pas dans la messagerie.
                if (m != null && m.typeTexte == 1) {
                    val cle = parPrefixe(m.prefixeExpediteurHex)
                    if (cle != null) session(cle) { s -> (s ?: SessionRepeteur(EtatSession.CONNECTEE, horloge())).let { it.copy(console = (it.console + LigneConsole(false, m.texte, horloge())).takeLast(100)) } }
                    return Reaction(listOf(suivant()))
                }
                Reaction(listOf(suivant()), directs = listOfNotNull(m?.let { MessageDirect(it.prefixeExpediteurHex, it.texte, it.reception, horodatageS = it.horodatageS) }))
            }
            // Message direct parti : la radio donne le code d'accusé attendu (26/11/2026).
            MeshCore.Rep.MSG_SENT -> {
                // La même réponse sert à la trace : on la reconnaît à son tag.
                traceEnCours?.let { (tag, _) ->
                    if (trame.size >= 10 && trame.u32(2) == tag) {
                        majTrace { it.copy(etat = EtatTrace.PARTIE, delaiEstimeMs = trame.u32(6)) }
                        return Reaction()
                    }
                }
                val envoi = directsEnAttente.removeFirstOrNull() ?: return Reaction()
                // Connexion, statut, commande : partis, rien d'autre à attendre ici.
                if (envoi.first < 0) { marques.remove(envoi.first); return Reaction() }
                MeshCore.lireEnvoi(trame)?.let { e -> if (e.codeAccuse != 0L) accusesAttendus[e.codeAccuse] = envoi.first }
                if (accusesAttendus.size > 64) accusesAttendus.remove(accusesAttendus.keys.first())
                Reaction()
            }
            // Le destinataire a accusé réception, avec l'aller-retour.
            MeshCore.Rep.SEND_CONFIRMED -> {
                val (code, delai) = MeshCore.lireConfirmation(trame) ?: return Reaction()
                val id = accusesAttendus.remove(code) ?: return Reaction()
                Reaction(accuses = listOf(Accuse(id, StatutAccuse.RECU, delai)))
            }
            AdminMeshCore.Rep.LOGIN_SUCCESS, AdminMeshCore.Rep.LOGIN_FAIL -> {
                val c = AdminMeshCore.lireConnexion(trame) ?: return Reaction()
                val cle = parPrefixe(c.prefixeHex) ?: return Reaction()
                session(cle) { s -> (s ?: SessionRepeteur(EtatSession.CONNEXION, horloge())).copy(
                    etat = if (c.reussie) EtatSession.CONNECTEE else EtatSession.REFUSEE, depuisMs = horloge(),
                    admin = c.admin, role = c.role, raison = if (c.reussie) null else "mot de passe refusé") }
                Reaction()
            }
            AdminMeshCore.Rep.STATUS_RESPONSE -> {
                val st = AdminMeshCore.lireStatut(trame) ?: return Reaction()
                val cle = parPrefixe(st.prefixeHex) ?: return Reaction()
                session(cle) { s -> (s ?: SessionRepeteur(EtatSession.FERMEE, horloge())).copy(statut = st, statutDemandeMs = null, raison = null) }
                Reaction()
            }
            AdminMeshCore.Rep.TRACE_DATA -> {
                val r = AdminMeshCore.lireTrace(trame) ?: return Reaction()
                if (traceEnCours?.first == r.tag) {
                    majTrace { it.copy(etat = EtatTrace.REVENUE, resultat = r) }
                    traceEnCours = null
                }
                Reaction()
            }
            MeshCore.Rep.BATTERIE -> { MeshCore.lireBatterie(trame)?.let { mv -> noter { it.copy(batterieMv = mv) } }; Reaction() }
            else -> Reaction()
        }
    }

    /** Les canaux sont connus : on vide ce que la radio a reçu pendant qu'on n'écoutait pas. */
    private fun finDeLecture(): Reaction { prete = true; return Reaction(listOf(suivant(), AdminMeshCore.demanderContacts(), demanderBatterie())) }

    private fun suivant() = MeshCore.commandeSimple(MeshCore.Cmd.SYNC_NEXT_MESSAGE)

    /** Relit tout ce que l'écran avancé affiche : identité et réglages, canaux, contacts. */
    fun relireTout(): List<ByteArray> =
        listOf(MeshCore.appStart(), AdminMeshCore.demanderContacts(), demanderBatterie()) + (0 until MeshCore.EMPLACEMENTS).map { MeshCore.demanderCanal(it) }

    override fun envoyerSurCanal(index: Int, texte: String, secondesUnix: Long): List<ByteArray> =
        morceaux(texte).map { MeshCore.envoyerSurCanal(index, it, secondesUnix) }

    /** Les morceaux d'un texte de canal : 7 octets d'en-tête, et de la marge pour le nom que la radio ajoute. */
    fun morceaux(texte: String): List<String> = Meshtastic.decouper(texte, MeshCore.TRAME_MAX - 7 - 40)
}

class PiloteMeshtastic(private val identifiant: () -> Long) : PiloteRadio(Protocole.MESHTASTIC) {
    private var nonce = Meshtastic.PREMIER_NONCE_BATTEMENT
    /** Paquets de messages directs envoyés avec accusé : id → destinataire (26/11/2026). */
    private val directsEnvoyes = LinkedHashMap<Long, Long>()

    /** Un message direct avec accusé ; `repondA` : id du message auquel on répond (réponse
     * native, affichée comme telle par l'application Meshtastic). Rend (id, trames). */
    fun envoyerDirect(destinataire: Long, texte: String, repondA: Long = 0, reaction: Boolean = false): Pair<Long, List<ByteArray>> {
        val morceaux = Meshtastic.decouper(texte)
        val ids = morceaux.map { identifiant() }
        ids.forEach { directsEnvoyes[it] = destinataire }
        while (directsEnvoyes.size > 64) directsEnvoyes.remove(directsEnvoyes.keys.first())
        // L'accusé suivi est celui du dernier morceau : le message est reçu quand tout l'est.
        return ids.last() to morceaux.mapIndexed { i, m -> Meshtastic.texte(destinataire, m, ids[i], repondA = if (i == 0) repondA else 0, emoji = reaction && i == 0) }
    }

    /** Trace la route vers un nœud (réponse : `avance.trajets[noeud]`). */
    fun traceroute(noeud: Long): ByteArray = Meshtastic.traceroute(noeud, identifiant())

    /** Sur un canal, en réponse à un message (`repondA`) ou en réaction émoji (`reaction`). */
    fun envoyerSurCanal(index: Int, texte: String, repondA: Long, reaction: Boolean = false): List<ByteArray> =
        Meshtastic.decouper(texte).mapIndexed { i, m ->
            Meshtastic.texte(Meshtastic.DIFFUSION, m, identifiant(), canal = index, accuse = false,
                             repondA = if (i == 0) repondA else 0, emoji = reaction && i == 0)
        }

    override fun ouverture(secondesUnix: Long): List<ByteArray> = listOf(Meshtastic.veutConfig(Meshtastic.NONCE_CONFIG))

    override fun recevoir(trame: ByteArray): Reaction {
        when (val lu = AdminMeshtastic.lire(trame)) {
            is AdminMeshtastic.Lu.Config -> noter { it.copy(reglages = it.reglages + ((lu.conteneur to lu.numero) to lu.contenu)) }
            is AdminMeshtastic.Lu.Canal -> noter { it.copy(canauxMeshtastic = it.canauxMeshtastic + (lu.canal.index to lu.canal)) }
            is AdminMeshtastic.Lu.Noeud -> noter {
                val moi = lu.noeud.numero == it.monNoeud
                it.copy(noeuds = it.noeuds + (lu.noeud.numero to lu.noeud),
                        batteriePourcent = if (moi) lu.noeud.batterie ?: it.batteriePourcent else it.batteriePourcent)
            }
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
            is Meshtastic.Evenement.Texte -> {
                val e = evenement
                val de = "!" + e.de.toString(16).padStart(8, '0')
                val r = Reception(sauts = e.sauts, snr = e.snr, rssi = e.rssi, parInternet = e.parInternet)
                if (e.vers == Meshtastic.DIFFUSION) Reaction(messages = listOf(MessageRadio(e.canal, e.texte, de, r, e.id, e.repondA, e.emoji)))
                // Adressé à mon nœud : un message direct.
                else if (e.vers == avance.monNoeud) Reaction(directs = listOf(MessageDirect(de, e.texte, r, e.id, e.repondA, e.emoji)))
                else Reaction()
            }
            is Meshtastic.Evenement.Trajet -> { noter { it.copy(trajets = it.trajets + (evenement.de to evenement)) }; Reaction() }
            // Accusé d'un paquet envoyé avec accusé (message direct) : du destinataire = reçu ;
            // d'un autre nœud sans erreur = relayé dans le réseau ; avec erreur = échec.
            is Meshtastic.Evenement.Accuse -> {
                val e = evenement
                val destinataire = directsEnvoyes[e.requete] ?: return Reaction()
                val statut = when {
                    e.erreur != 0 -> StatutAccuse.ECHEC
                    e.de == destinataire -> StatutAccuse.RECU
                    else -> StatutAccuse.RELAYE
                }
                if (statut != StatutAccuse.RELAYE) directsEnvoyes.remove(e.requete)
                Reaction(accuses = listOf(Accuse(e.requete, statut, raison = Meshtastic.raisonErreur(e.erreur))))
            }
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
