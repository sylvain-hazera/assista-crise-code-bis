package fr.assistacrise.mobile.lien.meshcore

import fr.assistacrise.mobile.lien.depuisHex
import fr.assistacrise.mobile.lien.enHex
import fr.assistacrise.mobile.lien.poserU32
import fr.assistacrise.mobile.lien.u32

/**
 * « Utilisateur radio avancé », côté MeshCore (22/11/2026) : canaux, contacts, réglages et
 * outils du protocole « companion ». Formats relevés dans la bibliothèque `meshcore` (MIT) du
 * pont de la plateforme — `commands/device.py`, `commands/contact.py`, `reader.py` — et non
 * devinés : chaque trame a son test, octet pour octet.
 */
object AdminMeshCore {
    object Cmd {
        const val GET_CONTACTS = 0x04
        const val SEND_SELF_ADVERT = 0x07
        const val SET_ADVERT_NAME = 0x08
        const val ADD_UPDATE_CONTACT = 0x09
        const val SET_RADIO_PARAMS = 0x0b
        const val SET_RADIO_TX_POWER = 0x0c
        const val RESET_PATH = 0x0d
        const val SET_ADVERT_LATLON = 0x0e
        const val REMOVE_CONTACT = 0x0f
        const val SHARE_CONTACT = 0x10
        const val EXPORT_CONTACT = 0x11
        const val IMPORT_CONTACT = 0x12
        const val REBOOT = 0x13
        const val SET_CHANNEL = 0x20
        /** Trace d'un chemin (26/11/2026) : tag (4), code d'accès (4), drapeaux, empreintes des relais. */
        const val SEND_TRACE_PATH = 36
        /** Administration d'un répéteur ou d'un salon à distance (26/11/2026) : clé (32) + mot de passe. */
        const val SEND_LOGIN = 26
        /** Statut d'un répéteur : clé (32). */
        const val SEND_STATUS_REQ = 27
        /** Fin de la session (la radio cesse d'entretenir la connexion) : clé (32). */
        const val LOGOUT = 29
        const val SET_DEVICE_PIN = 0x25
        const val SET_OTHER_PARAMS = 0x26
        const val FACTORY_RESET = 0x33
    }

    object Rep {
        const val CONTACT_START = 2
        const val CONTACT = 3
        const val CONTACT_END = 4
        const val CONTACT_URI = 11
        const val NEW_ADVERT = 0x8A
        /** Réponse d'une trace : empreintes des relais et signal reçu à chaque saut. */
        const val TRACE_DATA = 0x89
        const val LOGIN_SUCCESS = 0x85
        const val LOGIN_FAIL = 0x86
        const val STATUS_RESPONSE = 0x87
    }

    /** Ce que la radio dit d'elle-même (réponse SELF_INFO), complet. */
    data class Moi(
        val typeAnnonce: Int, val puissance: Int, val puissanceMax: Int, val pubkeyHex: String,
        val latitude: Double, val longitude: Double, val multiAcks: Int, val politiquePosition: Int,
        val telemetrieBase: Int, val telemetriePosition: Int, val telemetrieEnv: Int, val ajoutManuel: Boolean,
        val frequenceMhz: Double, val bandeKhz: Double, val facteurEtalement: Int, val tauxCodage: Int, val nom: String,
    )

    data class Contact(
        val pubkeyHex: String, val type: Int, val drapeaux: Int, val longueurChemin: Int, val nom: String,
        val derniereAnnonce: Long, val latitude: Double, val longitude: Double,
        /** Chemin de sortie connu (26/11/2026) : empreintes des relais, `largeurChemin` octets chacune. */
        val chemin: ByteArray = ByteArray(0), val largeurChemin: Int = 1,
    ) {
        val genre: String get() = when (type) { 1 -> "Compagnon"; 2 -> "Répéteur"; 3 -> "Salon"; 4 -> "Capteur"; else -> "Nœud" }
        val libelleChemin: String get() = if (longueurChemin < 0) "inondation" else "$longueurChemin saut(s)"
        /** Les relais du chemin, en hexadécimal. */
        val relais: List<String> get() = (0 until chemin.size / largeurChemin).map { chemin.copyOfRange(it * largeurChemin, (it + 1) * largeurChemin).enHex() }
        override fun equals(other: Any?) = other is Contact && pubkeyHex == other.pubkeyHex && type == other.type &&
            drapeaux == other.drapeaux && longueurChemin == other.longueurChemin && nom == other.nom &&
            derniereAnnonce == other.derniereAnnonce && latitude == other.latitude && longitude == other.longitude &&
            chemin.contentEquals(other.chemin) && largeurChemin == other.largeurChemin
        override fun hashCode() = pubkeyHex.hashCode()
    }

    /** Une trace reçue : (empreinte du relais, signal en dB auquel il a reçu) pour chaque saut,
     * puis le signal auquel ma radio a reçu le retour. */
    data class Trace(val tag: Long, val sauts: List<Pair<String, Float>>, val snrFinal: Float?)

    /** `PUSH_CODE_TRACE_DATA` (companion_radio/MyMesh.cpp, onTraceRecv) : code, réservé,
     * longueur du chemin (octets), drapeaux (2 bits bas : taille d'empreinte 1 << n), tag (4),
     * code d'accès (4), empreintes, un SNR par saut (quarts de dB, signé), SNR final. */
    fun lireTrace(t: ByteArray): Trace? {
        if (t.size < 12 || (t[0].toInt() and 0xff) != Rep.TRACE_DATA) return null
        val longueur = t[2].toInt() and 0xff
        val largeur = 1 shl (t[3].toInt() and 3)
        val nb = longueur / largeur
        if (t.size < 12 + longueur + nb) return null
        fun snr(i: Int) = t[i].toFloat() / 4f
        val sauts = (0 until nb).map { k -> t.copyOfRange(12 + k * largeur, 12 + (k + 1) * largeur).enHex() to snr(12 + longueur + k) }
        val fin = 12 + longueur + nb
        return Trace(t.u32(4), sauts, if (t.size > fin) snr(fin) else null)
    }

    /**
     * Le chemin à tracer vers `cible`, comme meshcore-open (path_trace_map.dart, `buildPath`) :
     * les relais du chemin connu, puis la cible elle-même si `jusquALaCible`, et le retour en
     * miroir (A, B, cible, B, A). Les empreintes de 3 octets n'existent pas dans une trace : elles
     * sont allongées à 4 d'après la clé d'un contact connu. Rend (empreintes, largeur), ou null si
     * un relais est inconnu ou s'il n'y a rien à tracer.
     */
    fun cheminDeTrace(cible: Contact, contacts: Collection<Contact>, jusquALaCible: Boolean): Pair<ByteArray, Int>? {
        val largeurChemin = cible.largeurChemin.coerceIn(1, 3)
        val largeur = when (largeurChemin) { 1 -> 1; 2 -> 2; else -> 4 }
        val aller = mutableListOf<String>()
        for (r in cible.relais) {
            aller += if (r.length == largeur * 2) r
                     else contacts.firstOrNull { it.pubkeyHex.startsWith(r, ignoreCase = true) }?.pubkeyHex?.take(largeur * 2) ?: return null
        }
        if (jusquALaCible) cible.pubkeyHex.take(largeur * 2).let { if (aller.lastOrNull() != it) aller += it }
        if (aller.isEmpty()) return null
        val tout = aller + aller.dropLast(1).reversed()
        return tout.joinToString("").depuisHex() to largeur
    }

    // --- Répéteurs à distance (26/11/2026), comme « Gérer le répéteur » de meshcore-open ---------
    // Formats : companion_radio/MyMesh.cpp (CMD_SEND_LOGIN, CMD_SEND_STATUS_REQ, onContactResponse)
    // et simple_repeater/MyMesh.h (RepeaterStats).

    fun connexion(pubkeyHex: String, motDePasse: String) =
        byteArrayOf(Cmd.SEND_LOGIN.toByte()) + pubkeyHex.depuisHex().copyOf(32) + motDePasse.encodeToByteArray()
    fun demanderStatut(pubkeyHex: String) = avecCle(Cmd.SEND_STATUS_REQ, pubkeyHex)
    fun deconnexion(pubkeyHex: String) = avecCle(Cmd.LOGOUT, pubkeyHex)

    /** Réponse de connexion : préfixe de clé (6 octets), réussite, rôle (0 invité, 1 lecture,
     * 2 lecture-écriture, 3 administrateur ; ancien micrologiciel : administrateur ou non). */
    data class Connexion(val prefixeHex: String, val reussie: Boolean, val admin: Boolean, val role: Int?)

    fun lireConnexion(t: ByteArray): Connexion? {
        if (t.size < 8) return null
        val code = t[0].toInt() and 0xff
        if (code != Rep.LOGIN_SUCCESS && code != Rep.LOGIN_FAIL) return null
        val ok = code == Rep.LOGIN_SUCCESS
        return Connexion(t.copyOfRange(2, 8).enHex(), ok, ok && t[1].toInt() != 0, if (ok && t.size >= 13) (t[12].toInt() and 3) else null)
    }

    /** `RepeaterStats` : 56 octets, petit-boutiste, sans bourrage. */
    data class StatutRepeteur(
        val prefixeHex: String, val batterieMv: Int, val fileEmission: Int, val bruitDbm: Int, val dernierRssi: Int,
        val paquetsRecus: Long, val paquetsEmis: Long, val tempsEmissionS: Long, val enMarcheS: Long,
        val emisInondation: Long, val emisDirect: Long, val recusInondation: Long, val recusDirect: Long,
        val erreurs: Int, val dernierSnr: Float, val doublonsDirect: Int, val doublonsInondation: Int,
        val tempsReceptionS: Long?, val erreursReception: Long?,
    )

    fun lireStatut(t: ByteArray): StatutRepeteur? {
        if (t.size < 8 + 48 || (t[0].toInt() and 0xff) != Rep.STATUS_RESPONSE) return null
        val b = 8
        fun u16(i: Int) = (t[b + i].toInt() and 0xff) or ((t[b + i + 1].toInt() and 0xff) shl 8)
        fun i16(i: Int) = u16(i).toShort().toInt()
        fun u32(i: Int) = t.u32(b + i)
        return StatutRepeteur(t.copyOfRange(2, 8).enHex(), u16(0), u16(2), i16(4), i16(6), u32(8), u32(12), u32(16), u32(20),
            u32(24), u32(28), u32(32), u32(36), u16(40), i16(42) / 4f, u16(44), u16(46),
            if (t.size >= b + 52) u32(48) else null, if (t.size >= b + 56) u32(52) else null)
    }

    /** `CMD_SEND_TRACE_PATH` : la radio envoie la trace en route directe ; elle répond
     * `RESP_CODE_SENT` (réservé, tag, délai estimé) puis, si la trace revient, `TRACE_DATA`. */
    fun traceroute(tag: Long, chemin: ByteArray, largeur: Int): ByteArray {
        val drapeaux = when (largeur) { 1 -> 0; 2 -> 1; else -> 2 }
        return byteArrayOf(Cmd.SEND_TRACE_PATH.toByte()) + i32le(tag) + i32le(0) + byteArrayOf(drapeaux.toByte()) + chemin
    }

    data class CanalComplet(val index: Int, val nom: String, val secret: ByteArray)

    private fun i32le(v: Long) = ByteArray(4).also { it.poserU32(0, v and 0xffffffffL) }

    fun lireMoi(t: ByteArray): Moi? {
        if (t.size < 58 || (t[0].toInt() and 0xff) != MeshCore.Rep.SELF_INFO) return null
        var i = 1
        fun o() = t[i++].toInt() and 0xff
        val typeAnnonce = o(); val puissance = o(); val puissanceMax = o()
        val pub = t.copyOfRange(i, i + 32).enHex(); i += 32
        val lat = t.u32(i).toInt() / 1e6; i += 4
        val lon = t.u32(i).toInt() / 1e6; i += 4
        val multi = o(); val politique = o(); val tele = o(); val manuel = o() > 0
        if (t.size < i + 10) return null
        val freq = t.u32(i) / 1000.0; i += 4
        val bande = t.u32(i) / 1000.0; i += 4
        val sf = o(); val cr = o()
        val nom = t.copyOfRange(i, t.size).decodeToString().trimEnd('\u0000')
        return Moi(typeAnnonce, puissance, puissanceMax, pub, lat, lon, multi, politique, tele and 3, (tele shr 2) and 3,
            (tele shr 4) and 3, manuel, freq, bande, sf, cr, nom)
    }

    /** CHANNEL_INFO avec le secret (16 octets après le nom). */
    fun lireCanalComplet(t: ByteArray): CanalComplet? {
        if (t.size < 34 || (t[0].toInt() and 0xff) != MeshCore.Rep.CHANNEL_INFO) return null
        val nom = t.copyOfRange(2, 34).let { n -> n.copyOf(n.indexOf(0).let { if (it < 0) n.size else it }) }.decodeToString()
        val secret = if (t.size >= 50) t.copyOfRange(34, 50) else ByteArray(0)
        return CanalComplet(t[1].toInt() and 0xff, nom, secret)
    }

    fun lireContact(t: ByteArray): Contact? {
        val type0 = t.firstOrNull()?.toInt()?.and(0xff) ?: return null
        if ((type0 != Rep.CONTACT && type0 != Rep.NEW_ADVERT) || t.size < 1 + 32 + 3 + 64 + 32 + 12) return null
        var i = 1
        val pub = t.copyOfRange(i, i + 32).enHex(); i += 32
        val type = t[i++].toInt() and 0xff
        val drapeaux = t[i++].toInt() and 0xff
        val plen = t[i++].toInt() and 0xff
        val largeurChemin = (plen shr 6) + 1
        val chemin = if (plen == 255) ByteArray(0) else t.copyOfRange(i, i + ((plen and 0x3f) * largeurChemin).coerceAtMost(64))
        i += 64
        val nom = t.copyOfRange(i, i + 32).let { n -> n.copyOf(n.indexOf(0).let { if (it < 0) n.size else it }) }.decodeToString(); i += 32
        val derniere = t.u32(i); i += 4
        val lat = t.u32(i).toInt() / 1e6; i += 4
        val lon = t.u32(i).toInt() / 1e6
        return Contact(pub, type, drapeaux, if (plen == 255) -1 else plen and 0x3f, nom, derniere, lat, lon,
            chemin, if (plen == 255) 1 else largeurChemin)
    }

    fun demanderContacts() = byteArrayOf(Cmd.GET_CONTACTS.toByte())

    /** `secret` : 16 octets. Un nom commençant par « # » dérive sa clé du nom (canal public). */
    fun ecrireCanal(index: Int, nom: String, secret: ByteArray): ByteArray {
        require(secret.size == 16) { "Le secret d'un canal MeshCore fait 16 octets." }
        val n = nom.encodeToByteArray().copyOf(32)
        return byteArrayOf(Cmd.SET_CHANNEL.toByte(), index.toByte()) + n + secret
    }

    /** Vider un emplacement : nom vide et secret nul. */
    fun effacerCanal(index: Int) = ecrireCanal(index, "", ByteArray(16))

    fun ecrireNom(nom: String) = byteArrayOf(Cmd.SET_ADVERT_NAME.toByte()) + nom.encodeToByteArray()

    fun ecrirePosition(lat: Double, lon: Double) = byteArrayOf(Cmd.SET_ADVERT_LATLON.toByte()) +
        i32le((lat * 1e6).toLong()) + i32le((lon * 1e6).toLong()) + i32le(0)

    fun ecrirePuissance(dbm: Int) = byteArrayOf(Cmd.SET_RADIO_TX_POWER.toByte()) + i32le(dbm.toLong())

    fun ecrireRadio(frequenceMhz: Double, bandeKhz: Double, sf: Int, cr: Int) = byteArrayOf(Cmd.SET_RADIO_PARAMS.toByte()) +
        i32le(kotlin.math.round(frequenceMhz * 1000).toLong()) + i32le(kotlin.math.round(bandeKhz * 1000).toLong()) +
        byteArrayOf(sf.toByte(), cr.toByte())

    fun ecrireAutresReglages(ajoutManuel: Boolean, telemetrieBase: Int, telemetriePosition: Int, telemetrieEnv: Int,
                             politiquePosition: Int, multiAcks: Int): ByteArray {
        val tele = (telemetrieBase and 3) or ((telemetriePosition and 3) shl 2) or ((telemetrieEnv and 3) shl 4)
        return byteArrayOf(Cmd.SET_OTHER_PARAMS.toByte(), (if (ajoutManuel) 1 else 0).toByte(), tele.toByte(),
            politiquePosition.toByte(), multiAcks.toByte())
    }

    fun ecrireCodeBluetooth(pin: Int) = byteArrayOf(Cmd.SET_DEVICE_PIN.toByte()) + i32le(pin.toLong())

    fun annoncer(inondation: Boolean = false) =
        if (inondation) byteArrayOf(Cmd.SEND_SELF_ADVERT.toByte(), 1) else byteArrayOf(Cmd.SEND_SELF_ADVERT.toByte())

    private fun avecCle(cmd: Int, pubkeyHex: String): ByteArray {
        val cle = pubkeyHex.depuisHex()
        require(cle.size == 32) { "Clé publique complète attendue (32 octets)." }
        return byteArrayOf(cmd.toByte()) + cle
    }

    fun retirerContact(pubkeyHex: String) = avecCle(Cmd.REMOVE_CONTACT, pubkeyHex)
    fun reinitialiserChemin(pubkeyHex: String) = avecCle(Cmd.RESET_PATH, pubkeyHex)
    fun partagerContact(pubkeyHex: String) = avecCle(Cmd.SHARE_CONTACT, pubkeyHex)
    fun exporterContact(pubkeyHex: String? = null) =
        if (pubkeyHex == null) byteArrayOf(Cmd.EXPORT_CONTACT.toByte()) else avecCle(Cmd.EXPORT_CONTACT, pubkeyHex)
    fun importerContact(carte: ByteArray) = byteArrayOf(Cmd.IMPORT_CONTACT.toByte()) + carte
    fun redemarrer() = byteArrayOf(Cmd.REBOOT.toByte()) + "reboot".encodeToByteArray()
    fun retourUsine() = byteArrayOf(Cmd.FACTORY_RESET.toByte())

    /** La carte d'un contact exporté (CONTACT_URI) : les octets bruts, à partager ou réimporter. */
    fun lireCarte(t: ByteArray): ByteArray? =
        if (t.isNotEmpty() && (t[0].toInt() and 0xff) == Rep.CONTACT_URI) t.copyOfRange(1, t.size) else null
}
