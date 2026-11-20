package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.MeshCore

/*
 * La radio jointe par le réseau (TCP/IP) plutôt que par le Bluetooth (demande du 20/11/2026) :
 * un nœud Meshtastic ou MeshCore relié au Wi-Fi (Heltec V3, T-Deck…) ouvre un port TCP où
 * passent EXACTEMENT les mêmes trames qu'en Bluetooth ; seul change le cadrage, puisqu'un flux
 * TCP n'a pas de frontières de messages. Les pilotes (`PiloteRadio`) servent tels quels.
 *
 * Vérifié dans le code des firmwares le 20/11/2026 :
 * - MeshCore (`src/helpers/wifi/SerialWifiInterface.cpp`, variantes `*_companion_radio_wifi`) :
 *   port 5000 par défaut (`TCP_PORT`), même en-tête que la liaison série — `<` (0x3c) puis la
 *   longueur sur deux octets petit-boutistes vers la radio, `>` (0x3e) dans l'autre sens. Un seul
 *   client à la fois : une nouvelle connexion coupe la précédente.
 * - Meshtastic (`src/mesh/StreamAPI.cpp`, `src/mesh/api/ServerAPI.h`) : port 4403, 0x94 0xC3 puis
 *   la longueur sur deux octets GROS-boutistes, 512 octets au plus. Tant qu'aucun protobuf n'a été
 *   reçu, le nœud peut écrire du texte de journal dans le flux : on se recale sur 0x94 0xC3.
 *
 * Ce fichier est commun à Android et iOS : chaque plateforme n'a qu'à ouvrir une prise TCP.
 */

/** Le cadrage d'une liaison en flux, propre à chaque protocole. */
sealed class CadrageFlux(val portParDefaut: Int) {
    /** La trame, prête à écrire dans le flux. */
    abstract fun encadrer(trame: ByteArray): ByteArray

    /** Un découpeur neuf, à garder pour toute la durée d'une connexion. */
    abstract fun decoupeur(): DecoupeurFlux

    /** À écrire dès l'ouverture, avant la première trame. */
    open fun reveil(): ByteArray = ByteArray(0)

    data object MeshCoreTcp : CadrageFlux(5000) {
        override fun encadrer(trame: ByteArray) = MeshCore.encadrer(trame)
        override fun decoupeur(): DecoupeurFlux = DecoupeurMeshCore()
    }

    data object MeshtasticTcp : CadrageFlux(4403) {
        const val DEBUT1 = 0x94
        const val DEBUT2 = 0xc3
        const val TRAME_MAX = 512

        override fun encadrer(trame: ByteArray): ByteArray {
            require(trame.size <= TRAME_MAX) { "Trame Meshtastic trop longue : ${trame.size} octets." }
            return ByteArray(4 + trame.size).also {
                it[0] = DEBUT1.toByte(); it[1] = DEBUT2.toByte()
                it[2] = ((trame.size shr 8) and 0xff).toByte(); it[3] = (trame.size and 0xff).toByte()
                trame.copyInto(it, 4)
            }
        }

        override fun decoupeur(): DecoupeurFlux = DecoupeurMeshtastic()

        /** Ce qu'envoient les clients de référence à l'ouverture : de quoi réveiller un nœud
         * endormi et remettre à zéro un découpage resté en plan (32 fois 0xC3, que le nœud jette
         * faute d'un 0x94 devant). */
        override fun reveil(): ByteArray = ByteArray(32) { DEBUT2.toByte() }
    }

    companion object {
        fun pour(protocole: Protocole): CadrageFlux = when (protocole) {
            Protocole.MESHCORE -> MeshCoreTcp
            Protocole.MESHTASTIC -> MeshtasticTcp
        }
    }
}

/** Reçoit le flux par morceaux, quelle que soit leur taille, et rend les trames entières. */
interface DecoupeurFlux {
    fun pousser(octets: ByteArray, longueur: Int = octets.size): List<ByteArray>
}

/** Tampon commun : on accumule, on cherche un en-tête, on coupe. */
private abstract class DecoupeurTampon : DecoupeurFlux {
    private var tampon = ByteArray(0)

    protected abstract val longueurEntete: Int
    protected abstract fun estDebut(octet: Int): Boolean
    /** Taille de la trame que cet en-tête annonce, ou null si ce n'en est pas un. */
    protected abstract fun lireEntete(t: ByteArray): Int?

    override fun pousser(octets: ByteArray, longueur: Int): List<ByteArray> {
        tampon += octets.copyOf(longueur)
        val trames = mutableListOf<ByteArray>()
        var i = 0
        while (true) {
            // Ce qui précède un début de trame (journal, octets perdus) est jeté.
            while (i < tampon.size && !estDebut(tampon[i].toInt() and 0xff)) i++
            if (tampon.size - i < longueurEntete) break
            val entete = tampon.copyOfRange(i, i + longueurEntete)
            val taille = lireEntete(entete)
            if (taille == null) { i++; continue }                        // faux départ : on se recale
            if (tampon.size - i - longueurEntete < taille) break             // la suite n'est pas arrivée
            trames += tampon.copyOfRange(i + longueurEntete, i + longueurEntete + taille)
            i += longueurEntete + taille
        }
        tampon = tampon.copyOfRange(i, tampon.size)
        return trames
    }
}

private class DecoupeurMeshCore : DecoupeurTampon() {
    override val longueurEntete = 3
    override fun estDebut(octet: Int) = octet == MeshCore.DEBUT_DE_RADIO
    override fun lireEntete(t: ByteArray): Int? {
        val taille = (t[1].toInt() and 0xff) or ((t[2].toInt() and 0xff) shl 8)
        // Le firmware n'envoie rien de vide ni au-delà de sa taille de trame (172 à 184 selon
        // les versions) : au-delà de 300, c'est un faux départ.
        return taille.takeIf { it in 1..300 }
    }
}

private class DecoupeurMeshtastic : DecoupeurTampon() {
    override val longueurEntete = 4
    override fun estDebut(octet: Int) = octet == CadrageFlux.MeshtasticTcp.DEBUT1
    override fun lireEntete(t: ByteArray): Int? {
        if ((t[1].toInt() and 0xff) != CadrageFlux.MeshtasticTcp.DEBUT2) return null
        val taille = ((t[2].toInt() and 0xff) shl 8) or (t[3].toInt() and 0xff)
        return taille.takeIf { it <= CadrageFlux.MeshtasticTcp.TRAME_MAX }
    }
}

/**
 * L'adresse d'une radio sur le réseau. Le lien TCP n'est pas chiffré (contrairement au
 * Bluetooth appairé) : on n'accepte qu'une adresse du réseau local — privée, de lien local,
 * d'un VPN d'opérateur (100.64.0.0/10), ou un nom local (« tdeck.local », « radio ») —, jamais
 * une adresse d'Internet, par où les messages d'équipe passeraient en clair.
 */
data class AdresseReseau(val hote: String, val port: Int) {
    override fun toString() = if (':' in hote) "[$hote]:$port" else "$hote:$port"

    companion object {
        sealed class Lecture {
            data class Valide(val adresse: AdresseReseau) : Lecture()
            data class Refusee(val motif: String) : Lecture()
        }

        fun lire(texte: String, portParDefaut: Int): Lecture {
            val brut = texte.trim().removePrefix("tcp://").trimEnd('/')
            if (brut.isEmpty()) return Lecture.Refusee("Saisissez l'adresse de la radio, par exemple 192.168.4.1.")
            val (hote, portTexte) = when {
                brut.startsWith("[") -> brut.substringAfter("[").substringBefore("]") to brut.substringAfter("]", "").removePrefix(":")
                brut.count { it == ':' } == 1 -> brut.substringBefore(":") to brut.substringAfter(":")
                else -> brut to ""
            }
            val port = if (portTexte.isEmpty()) portParDefaut else portTexte.toIntOrNull()
            if (port == null || port !in 1..65535) return Lecture.Refusee("Le port doit être un nombre entre 1 et 65535.")
            if (!estLocale(hote.lowercase())) {
                return Lecture.Refusee("Seule une adresse du réseau local est acceptée : la liaison n'est pas chiffrée.")
            }
            return Lecture.Valide(AdresseReseau(hote, port))
        }

        private fun estLocale(hote: String): Boolean {
            val ipv4 = hote.split(".").takeIf { it.size == 4 }?.map { it.toIntOrNull() ?: -1 }
            if (ipv4 != null && ipv4.all { it in 0..255 }) {
                val (a, b) = ipv4[0] to ipv4[1]
                return a == 10 || (a == 172 && b in 16..31) || (a == 192 && b == 168) ||
                    (a == 169 && b == 254) || (a == 100 && b in 64..127)
            }
            if (':' in hote) {                                              // IPv6
                return hote.startsWith("fe8") || hote.startsWith("fe9") || hote.startsWith("fea") ||
                    hote.startsWith("feb") || hote.startsWith("fc") || hote.startsWith("fd")
            }
            if (!hote.all { it.isLetterOrDigit() || it == '-' || it == '.' } || hote.startsWith("-")) return false
            if (hote.all { it.isDigit() || it == '.' }) return false        // IPv4 mal formée
            return '.' !in hote || SUFFIXES_LOCAUX.any { hote.endsWith(it) }
        }

        private val SUFFIXES_LOCAUX = listOf(".local", ".lan", ".home", ".internal", ".home.arpa")
    }
}
