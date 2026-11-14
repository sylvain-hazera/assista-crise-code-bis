package fr.assistacrise.mobile.lien.meshtastic

/**
 * Le strict nécessaire de protobuf, écrit ici plutôt que généré.
 *
 * Les définitions de Meshtastic sont sous GPL-3.0 : les embarquer contaminerait
 * l'application (dossier § 11). Ce fichier n'en reprend rien — il sait écrire et lire des
 * champs numérotés, et ce sont les appelants qui connaissent les numéros.
 *
 * Porté de `frontend/src/app/shared/mesh/protobuf-mini.ts`.
 */
internal object Fil {
    const val VARINT = 0
    const val I64 = 1
    const val LONGUEUR = 2
    const val I32 = 5
}

internal class Ecrivain {
    private val octets = ArrayList<Byte>()

    private fun varintBrut(valeur: Long) {
        var v = valeur
        while (v >= 0x80) { octets.add(((v and 0x7f) or 0x80).toByte()); v = v ushr 7 }
        octets.add(v.toByte())
    }

    private fun cle(numero: Int, fil: Int) = varintBrut((numero.toLong() shl 3) or fil.toLong())

    /** Comme proto3 : une valeur nulle n'est pas écrite. */
    fun varint(numero: Int, valeur: Long): Ecrivain {
        if (valeur != 0L) { cle(numero, Fil.VARINT); varintBrut(valeur) }
        return this
    }

    fun booleen(numero: Int, valeur: Boolean) = varint(numero, if (valeur) 1 else 0)

    fun fixe32(numero: Int, valeur: Long): Ecrivain {
        if (valeur != 0L) {
            cle(numero, Fil.I32)
            for (i in 0..3) octets.add(((valeur shr (8 * i)) and 0xff).toByte())
        }
        return this
    }

    fun brut(numero: Int, valeur: ByteArray): Ecrivain {
        if (valeur.isNotEmpty()) { cle(numero, Fil.LONGUEUR); varintBrut(valeur.size.toLong()); octets.addAll(valeur.asList()) }
        return this
    }

    /** Un sous-message est écrit même vide : sa présence a un sens (le battement de cœur). */
    fun message(numero: Int, sous: Ecrivain): Ecrivain {
        val contenu = sous.fin()
        cle(numero, Fil.LONGUEUR); varintBrut(contenu.size.toLong()); octets.addAll(contenu.asList())
        return this
    }

    fun fin(): ByteArray = octets.toByteArray()
}

internal class Champ(val numero: Int, val nombre: Long? = null, val octets: ByteArray? = null)

/** Lève `IllegalArgumentException` sur une trame tronquée : mieux vaut rien qu'un numéro faux. */
internal fun lireChamps(octets: ByteArray): List<Champ> {
    val champs = ArrayList<Champ>()
    var i = 0
    fun varint(): Long {
        var resultat = 0L
        for (n in 0 until 10) {
            require(i < octets.size) { "protobuf tronqué" }
            val o = octets[i++].toLong() and 0xff
            resultat = resultat or ((o and 0x7f) shl (7 * n))
            if (o and 0x80 == 0L) return resultat
        }
        throw IllegalArgumentException("varint trop long")
    }
    while (i < octets.size) {
        val cle = varint()
        val numero = (cle ushr 3).toInt()
        when ((cle and 7).toInt()) {
            Fil.VARINT -> champs.add(Champ(numero, nombre = varint()))
            Fil.I32 -> {
                require(i + 4 <= octets.size) { "protobuf tronqué" }
                var v = 0L
                for (k in 0..3) v = v or ((octets[i + k].toLong() and 0xff) shl (8 * k))
                i += 4
                champs.add(Champ(numero, nombre = v))
            }
            Fil.I64 -> { require(i + 8 <= octets.size) { "protobuf tronqué" }; i += 8 }
            Fil.LONGUEUR -> {
                val n = varint().toInt()
                require(n >= 0 && i + n <= octets.size) { "protobuf tronqué" }
                champs.add(Champ(numero, octets = octets.copyOfRange(i, i + n)))
                i += n
            }
            else -> throw IllegalArgumentException("type de fil protobuf inconnu")
        }
    }
    return champs
}

internal fun List<Champ>.champ(numero: Int): Champ? = firstOrNull { it.numero == numero }
