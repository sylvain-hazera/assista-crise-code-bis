package fr.assistacrise.mobile.lien

/** Petits outils d'octets, communs aux deux protocoles radio. */

fun ByteArray.enHex(): String = joinToString("") { (it.toInt() and 0xff).toString(16).padStart(2, '0') }

fun String.depuisHex(): ByteArray {
    val propre = filter { it.isDigit() || it.lowercaseChar() in 'a'..'f' }
    return ByteArray(propre.length / 2) { propre.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
}

/** Entier non signé de 32 bits, petit-boutiste, lu à `position`. */
fun ByteArray.u32(position: Int): Long =
    (this[position].toLong() and 0xff) or
        ((this[position + 1].toLong() and 0xff) shl 8) or
        ((this[position + 2].toLong() and 0xff) shl 16) or
        ((this[position + 3].toLong() and 0xff) shl 24)

/** Écrit un entier de 32 bits, petit-boutiste, à `position`. */
fun ByteArray.poserU32(position: Int, valeur: Long) {
    for (i in 0..3) this[position + i] = ((valeur shr (8 * i)) and 0xff).toByte()
}
