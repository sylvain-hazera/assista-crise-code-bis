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
    ) {
        val genre: String get() = when (type) { 1 -> "Compagnon"; 2 -> "Répéteur"; 3 -> "Salon"; 4 -> "Capteur"; else -> "Nœud" }
        val chemin: String get() = if (longueurChemin < 0) "inondation" else "$longueurChemin saut(s)"
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
        i += 64
        val nom = t.copyOfRange(i, i + 32).let { n -> n.copyOf(n.indexOf(0).let { if (it < 0) n.size else it }) }.decodeToString(); i += 32
        val derniere = t.u32(i); i += 4
        val lat = t.u32(i).toInt() / 1e6; i += 4
        val lon = t.u32(i).toInt() / 1e6
        return Contact(pub, type, drapeaux, if (plen == 255) -1 else plen and 0x3f, nom, derniere, lat, lon)
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
