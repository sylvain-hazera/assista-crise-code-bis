package fr.assistacrise.mobile.domaine

/**
 * Le calcul que le serveur demande avant de créer un compte (core/defi_inscription.py côté
 * serveur, defi-calcul.ts côté site) : retrouver le nombre dont l'empreinte SHA-256, précédée
 * d'un sel, vaut celle du défi, en essayant 0, 1, 2… jusqu'à `maximum`.
 *
 * La personne n'a rien à lire ni à résoudre : c'est l'application qui calcule, le temps
 * d'envoyer le formulaire. SHA-256 est écrit ici parce que le code commun n'a pas accès aux
 * bibliothèques de chiffrement d'une plateforme.
 */
data class Defi(
    val sel: String,
    val empreinte: String,
    val maximum: Int,
    val emis: Long,
    val expire: Long,
    val signature: String,
)

private val K = intArrayOf(
    0x428a2f98, 0x71374491, -0x4a3f0431, -0x164a245b, 0x3956c25b, 0x59f111f1, -0x6dc07d5c, -0x54e3a12b,
    -0x27f85568, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, -0x7f214e02, -0x6423f959, -0x3e640e8c,
    -0x1b64963f, -0x1041b87a, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    -0x67c1aeae, -0x57ce3993, -0x4ffcd838, -0x40a68039, -0x391ff40d, -0x2a586eb9, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, -0x7e3d36d2, -0x6d8dd37b,
    -0x5d40175f, -0x57e599b5, -0x3db47490, -0x3893ae5d, -0x2e6d17e7, -0x2966f9dc, -0xbf1ca7b, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, -0x7b3787ec, -0x7338fdf8, -0x6f410006, -0x5baf9315, -0x41065c09, -0x398e870e,
)

/** Empreinte SHA-256 d'un message de 55 octets au plus (un seul bloc), rangée dans `sortie`. */
private fun sha256UnBloc(bloc: ByteArray, longueur: Int, w: IntArray, sortie: IntArray) {
    bloc[longueur] = 0x80.toByte()
    for (i in longueur + 1 until 62) bloc[i] = 0
    bloc[62] = ((longueur * 8) ushr 8).toByte()
    bloc[63] = (longueur * 8).toByte()

    for (i in 0 until 16) {
        val j = i * 4
        w[i] = ((bloc[j].toInt() and 0xff) shl 24) or ((bloc[j + 1].toInt() and 0xff) shl 16) or
            ((bloc[j + 2].toInt() and 0xff) shl 8) or (bloc[j + 3].toInt() and 0xff)
    }
    for (i in 16 until 64) {
        val a = w[i - 15]
        val b = w[i - 2]
        val s0 = a.rotateRight(7) xor a.rotateRight(18) xor (a ushr 3)
        val s1 = b.rotateRight(17) xor b.rotateRight(19) xor (b ushr 10)
        w[i] = w[i - 16] + s0 + w[i - 7] + s1
    }

    var a = 0x6a09e667; var b = -0x4498517b; var c = 0x3c6ef372; var d = -0x5ab00ac6
    var e = 0x510e527f; var f = -0x64fa9774; var g = 0x1f83d9ab; var h = 0x5be0cd19
    for (i in 0 until 64) {
        val t1 = h + (e.rotateRight(6) xor e.rotateRight(11) xor e.rotateRight(25)) +
            ((e and f) xor (e.inv() and g)) + K[i] + w[i]
        val t2 = (a.rotateRight(2) xor a.rotateRight(13) xor a.rotateRight(22)) +
            ((a and b) xor (a and c) xor (b and c))
        h = g; g = f; f = e; e = d + t1
        d = c; c = b; b = a; a = t1 + t2
    }
    sortie[0] = a + 0x6a09e667; sortie[1] = b + -0x4498517b; sortie[2] = c + 0x3c6ef372; sortie[3] = d + -0x5ab00ac6
    sortie[4] = e + 0x510e527f; sortie[5] = f + -0x64fa9774; sortie[6] = g + 0x1f83d9ab; sortie[7] = h + 0x5be0cd19
}

/** SHA-256 en hexadécimal d'un texte court (55 octets au plus). */
fun sha256Hex(texte: String): String {
    val octets = texte.encodeToByteArray()
    require(octets.size <= 55) { "texte trop long pour un seul bloc" }
    val bloc = ByteArray(64)
    octets.copyInto(bloc)
    val mots = IntArray(8)
    sha256UnBloc(bloc, octets.size, IntArray(64), mots)
    return mots.joinToString("") { it.toUInt().toString(16).padStart(8, '0') }
}

/**
 * Cherche le nombre du défi. `null` si aucune valeur ne convient : un défi mal formé, jamais
 * un défi du serveur. `maximum` est borné : un serveur compromis ne fait pas tourner le
 * téléphone sans fin.
 */
fun resoudreDefi(defi: Defi): Int? {
    val sel = defi.sel.encodeToByteArray()
    if (sel.size > 40 || defi.empreinte.length != 64 || defi.maximum !in 0..20_000_000) return null
    val cible = IntArray(8)
    for (i in 0 until 8) {
        cible[i] = defi.empreinte.substring(i * 8, i * 8 + 8).toUIntOrNull(16)?.toInt() ?: return null
    }
    val bloc = ByteArray(64)
    sel.copyInto(bloc)
    val w = IntArray(64)
    val mots = IntArray(8)
    val chiffres = ByteArray(12)
    for (nombre in 0..defi.maximum) {
        var n = nombre
        var k = 0
        do { chiffres[k++] = (48 + n % 10).toByte(); n /= 10 } while (n > 0)
        for (i in 0 until k) bloc[sel.size + i] = chiffres[k - 1 - i]
        sha256UnBloc(bloc, sel.size + k, w, mots)
        if (mots.contentEquals(cible)) return nombre
    }
    return null
}
