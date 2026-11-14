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
 * GATT. `encadrer` et `Decoupeur` ne servent qu'à la liaison série.
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
        const val SET_DEVICE_TIME = 6
        const val SYNC_NEXT_MESSAGE = 10
        const val DEVICE_QUERY = 22
    }

    object Rep {
        const val OK = 0
        const val ERROR = 1
        const val SELF_INFO = 5
        const val MSG_SENT = 6
        const val CONTACT_MSG_RECV = 7
        const val NO_MORE_MSGS = 10
        const val CONTACT_MSG_RECV_V3 = 16
        const val MESSAGES_WAITING = 0x83
    }

    data class Identite(val pubkeyHex: String, val nom: String)
    data class MessageRecu(val prefixeExpediteurHex: String, val texte: String, val horodatageS: Long)

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

    /** Message direct. La radio chiffre ; l'application lui passe le texte en clair. */
    fun envoyerMessage(pubkeyHex: String, texte: String, secondesUnix: Long): ByteArray {
        val destination = pubkeyHex.depuisHex()
        require(destination.size >= 6) { "Clé publique du destinataire trop courte : 6 octets au minimum." }
        val corps = texte.encodeToByteArray()
        return ByteArray(13 + corps.size).also {
            it[0] = Cmd.SEND_TXT_MSG.toByte()
            // [1] type de texte : simple ; [2] première et unique tentative.
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
        if (type == Rep.CONTACT_MSG_RECV_V3) i += 3          // SNR (1) + réservé (2)
        if (charge.size < i + 12) return null
        val prefixe = charge.copyOfRange(i, i + 6).enHex(); i += 6
        i += 1                                               // longueur ou mode de chemin
        val typeTexte = charge[i].toInt() and 0xff; i += 1
        val horodatage = charge.u32(i); i += 4
        if (typeTexte == 2) i += 4                           // signature
        if (i > charge.size) return null
        return MessageRecu(prefixe, charge.copyOfRange(i, charge.size).decodeToString(), horodatage)
    }

    /** Liaison série seulement : `0x3c`, longueur sur deux octets petit-boutistes, charge. */
    fun encadrer(charge: ByteArray): ByteArray = ByteArray(3 + charge.size).also {
        it[0] = DEBUT_VERS_RADIO.toByte()
        it[1] = (charge.size and 0xff).toByte()
        it[2] = ((charge.size shr 8) and 0xff).toByte()
        charge.copyInto(it, 3)
    }
}
