package fr.assistacrise.mobile.lien.meshcore

import fr.assistacrise.mobile.lien.depuisHex
import fr.assistacrise.mobile.lien.enHex
import fr.assistacrise.mobile.lien.poserU32
import fr.assistacrise.mobile.lien.u32

/**
 * Le protocole « companion » de MeshCore, réduit à ce que l'application en dit.
 *
 * Porté de `frontend/src/app/shared/mesh/meshcore-trames.ts`, écrit pour le relais
 * navigateur et vérifié octet pour octet contre la bibliothèque `meshcore` 2.3.15. Les
 * tests reprennent les mêmes vecteurs.
 *
 * En Bluetooth (service UART Nordic), il n'y a **pas de cadrage** : une trame par écriture
 * GATT. `encadrer` sert aux liaisons en flux : série et TCP (voir `LiaisonReseau.kt`).
 */
object MeshCore {
    const val SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    /** L'application écrit ici. */
    const val RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
    /** La radio notifie ici. */
    const val TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    /** Taille maximale d'une trame (mesurée dans MeshCrossway ; la doc annonce 184). */
    const val TRAME_MAX = 176

    const val DEBUT_VERS_RADIO = 0x3c
    const val DEBUT_DE_RADIO = 0x3e
    const val VERSION_PROTOCOLE = 3

    object Cmd {
        const val APP_START = 1
        const val SEND_TXT_MSG = 2
        const val SEND_CHANNEL_TXT_MSG = 3
        const val GET_CHANNEL = 31
        const val SET_DEVICE_TIME = 6
        const val SYNC_NEXT_MESSAGE = 10
        const val DEVICE_QUERY = 22
        const val GET_BATT_AND_STORAGE = 20
    }

    object Rep {
        const val OK = 0
        const val ERROR = 1
        const val SELF_INFO = 5
        const val MSG_SENT = 6
        const val CONTACT_MSG_RECV = 7
        const val CHANNEL_MSG_RECV = 8
        const val CHANNEL_MSG_RECV_V3 = 17
        const val CHANNEL_INFO = 18
        const val NO_MORE_MSGS = 10
        const val CONTACT_MSG_RECV_V3 = 16
        const val MESSAGES_WAITING = 0x83
        /** Accusé de réception d'un message direct : code (4) + aller-retour en ms (4). */
        const val SEND_CONFIRMED = 0x82
        /** Batterie (mV, 2 octets) et stockage. */
        const val BATTERIE = 12
    }

    data class Identite(val pubkeyHex: String, val nom: String)
    data class MessageRecu(val prefixeExpediteurHex: String, val texte: String, val horodatageS: Long,
                           val reception: fr.assistacrise.mobile.lien.Reception? = null,
                           /** 0 : texte ; 1 : réponse de la ligne de commande d'un répéteur ; 2 : signé. */
                           val typeTexte: Int = 0)

    /** `path_len` reçu (26/11/2026) : 0xFF = arrivé par une route directe ; sinon les 6 bits bas
     * sont le nombre de sauts (les 2 hauts, la taille des empreintes de chemin). */
    internal fun reception(longueurChemin: Int, snrQuarts: Int?): fr.assistacrise.mobile.lien.Reception =
        fr.assistacrise.mobile.lien.Reception(
            sauts = if (longueurChemin == 0xff) null else longueurChemin and 0x3f,
            snr = snrQuarts?.let { (if (it > 127) it - 256 else it) / 4f },
            routeDirecte = longueurChemin == 0xff,
        )

    /** `MSG_SENT` : envoyé en inondation ou non, code d'accusé attendu, délai estimé. */
    data class Envoi(val inondation: Boolean, val codeAccuse: Long, val delaiEstimeMs: Long)

    fun lireEnvoi(t: ByteArray): Envoi? =
        if (t.size < 10 || (t[0].toInt() and 0xff) != Rep.MSG_SENT) null
        else Envoi(t[1].toInt() != 0, t.u32(2), t.u32(6))

    /** `SEND_CONFIRMED` : (code d'accusé, aller-retour en ms). */
    fun lireConfirmation(t: ByteArray): Pair<Long, Long>? =
        if (t.size < 9 || (t[0].toInt() and 0xff) != Rep.SEND_CONFIRMED) null else t.u32(1) to t.u32(5)

    fun lireBatterie(t: ByteArray): Int? =
        if (t.size < 3 || (t[0].toInt() and 0xff) != Rep.BATTERIE) null
        else (t[1].toInt() and 0xff) or ((t[2].toInt() and 0xff) shl 8)

    fun commandeSimple(code: Int) = byteArrayOf(code.toByte())

    fun appStart(nomApplication: String = "assista"): ByteArray {
        val nom = nomApplication.encodeToByteArray()
        return ByteArray(8 + nom.size).also {
            it[0] = Cmd.APP_START.toByte()
            it[1] = 0x03
            it.fill(0x20, 2, 8)
            nom.copyInto(it, 8)
        }
    }

    fun requeteAppareil() = byteArrayOf(Cmd.DEVICE_QUERY.toByte(), VERSION_PROTOCOLE.toByte())

    fun reglerHeure(secondesUnix: Long) = ByteArray(5).also {
        it[0] = Cmd.SET_DEVICE_TIME.toByte()
        it.poserU32(1, secondesUnix)
    }

    /** Message direct. La radio chiffre ; l'application lui passe le texte en clair.
     * `typeTexte` 1 : commande pour la ligne de commande d'un répéteur où l'on est connecté. */
    fun envoyerMessage(pubkeyHex: String, texte: String, secondesUnix: Long, typeTexte: Int = 0): ByteArray {
        val destination = pubkeyHex.depuisHex()
        require(destination.size >= 6) { "Clé publique du destinataire trop courte : 6 octets au minimum." }
        val corps = texte.encodeToByteArray()
        return ByteArray(13 + corps.size).also {
            it[0] = Cmd.SEND_TXT_MSG.toByte()
            // [1] type de texte ; [2] première et unique tentative.
            it[1] = typeTexte.toByte()
            it.poserU32(3, secondesUnix)
            destination.copyInto(it, 7, 0, 6)
            corps.copyInto(it, 13)
        }.also { require(it.size <= TRAME_MAX) { "Message trop long pour une trame MeshCore." } }
    }

    fun lireSelfInfo(charge: ByteArray): Identite? {
        if (charge.isEmpty() || (charge[0].toInt() and 0xff) != Rep.SELF_INFO || charge.size < 58) return null
        return Identite(
            pubkeyHex = charge.copyOfRange(4, 36).enHex(),
            nom = charge.copyOfRange(58, charge.size).decodeToString().trimEnd('\u0000').trim(),
        )
    }

    fun lireMessageRecu(charge: ByteArray): MessageRecu? {
        if (charge.isEmpty()) return null
        val type = charge[0].toInt() and 0xff
        if (type != Rep.CONTACT_MSG_RECV && type != Rep.CONTACT_MSG_RECV_V3) return null
        var i = 1
        val snr = if (type == Rep.CONTACT_MSG_RECV_V3) charge[1].toInt() and 0xff else null
        if (type == Rep.CONTACT_MSG_RECV_V3) i += 3          // SNR (1) + réservé (2)
        if (charge.size < i + 12) return null
        val prefixe = charge.copyOfRange(i, i + 6).enHex(); i += 6
        val chemin = charge[i].toInt() and 0xff; i += 1
        val typeTexte = charge[i].toInt() and 0xff; i += 1
        val horodatage = charge.u32(i); i += 4
        if (typeTexte == 2) i += 4                           // signature
        if (i > charge.size) return null
        return MessageRecu(prefixe, charge.copyOfRange(i, charge.size).decodeToString().trimEnd('\u0000'), horodatage, reception(chemin, snr), typeTexte)
    }

    /** Nombre d'emplacements de canal d'une radio companion. */
    const val EMPLACEMENTS = 40

    data class Canal(val index: Int, val nom: String)
    data class MessageCanal(val canal: Int, val texte: String, val horodatageS: Long,
                            val reception: fr.assistacrise.mobile.lien.Reception? = null)

    fun demanderCanal(index: Int) = byteArrayOf(Cmd.GET_CHANNEL.toByte(), index.toByte())

    /** `nom` vide : l'emplacement est libre. */
    fun lireCanal(charge: ByteArray): Canal? {
        if (charge.size < 34 || (charge[0].toInt() and 0xff) != Rep.CHANNEL_INFO) return null
        val nom = charge.copyOfRange(2, 34)
        val fin = nom.indexOf(0).let { if (it < 0) nom.size else it }
        return Canal(charge[1].toInt() and 0xff, nom.copyOf(fin).decodeToString())
    }

    /** Message sur un canal. La radio y ajoute elle-même le nom de l'expéditeur. */
    fun envoyerSurCanal(index: Int, texte: String, secondesUnix: Long): ByteArray {
        val corps = texte.encodeToByteArray()
        return ByteArray(7 + corps.size).also {
            it[0] = Cmd.SEND_CHANNEL_TXT_MSG.toByte()
            // [1] type de texte : simple.
            it[2] = index.toByte()
            it.poserU32(3, secondesUnix)
            corps.copyInto(it, 7)
        }.also { require(it.size <= TRAME_MAX) { "Message trop long pour une trame MeshCore." } }
    }

    fun lireMessageCanal(charge: ByteArray): MessageCanal? {
        if (charge.isEmpty()) return null
        val type = charge[0].toInt() and 0xff
        if (type != Rep.CHANNEL_MSG_RECV && type != Rep.CHANNEL_MSG_RECV_V3) return null
        var i = 1
        val snr = if (type == Rep.CHANNEL_MSG_RECV_V3) charge[1].toInt() and 0xff else null
        if (type == Rep.CHANNEL_MSG_RECV_V3) i += 3          // SNR (1) + réservé (2)
        if (charge.size < i + 7) return null
        val canal = charge[i].toInt() and 0xff; i += 1
        val chemin = charge[i].toInt() and 0xff; i += 2      // chemin, type de texte
        val horodatage = charge.u32(i); i += 4
        return MessageCanal(canal, charge.copyOfRange(i, charge.size).decodeToString().trimEnd('\u0000'), horodatage, reception(chemin, snr))
    }

    /** Liaisons en flux (série, TCP) : `0x3c`, longueur sur deux octets petit-boutistes, charge. */
    fun encadrer(charge: ByteArray): ByteArray = ByteArray(3 + charge.size).also {
        it[0] = DEBUT_VERS_RADIO.toByte()
        it[1] = (charge.size and 0xff).toByte()
        it[2] = ((charge.size shr 8) and 0xff).toByte()
        charge.copyInto(it, 3)
    }
}
