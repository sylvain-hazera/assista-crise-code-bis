package fr.assistacrise.mobile.lien

import kotlin.math.roundToLong

/**
 * La position d'un intervenant, en seize octets, pour la radio (dossier § 14).
 *
 * Un paquet LoRa porte moins de 200 octets utiles et le temps d'émission est compté : la
 * position ne voyage pas en JSON. Tous les entiers sont petit-boutistes.
 *
 * | Octets | Champ |
 * |---|---|
 * | 0 | version (4 bits de poids fort) et genre (4 bits de poids faible) |
 * | 1–4 | latitude, entier signé, degrés × 10⁷ |
 * | 5–8 | longitude, entier signé, degrés × 10⁷ |
 * | 9–12 | instant du relevé, secondes depuis 1970 (UTC) |
 * | 13 | statut |
 * | 14 | batterie du téléphone, en % (255 = inconnue) |
 * | 15 | précision du relevé, en mètres, plafonnée à 255 |
 *
 * L'expéditeur n'y figure pas : c'est le nœud radio, déjà dans l'en-tête du paquet.
 */
data class TramePosition(
    val genre: Genre,
    val latitude: Double,
    val longitude: Double,
    val instantS: Long,
    val statut: Int = 0,
    val batterie: Int = BATTERIE_INCONNUE,
    val precisionM: Int = 0,
) {
    enum class Genre(val code: Int) { POSITION(1), SOS(2), STATUT(3) }

    fun enOctets(): ByteArray {
        val octets = ByteArray(TAILLE)
        octets[0] = ((VERSION shl 4) or genre.code).toByte()
        octets.poserU32(1, (latitude * 1e7).roundToLong())
        octets.poserU32(5, (longitude * 1e7).roundToLong())
        octets.poserU32(9, instantS)
        octets[13] = statut.coerceIn(0, 255).toByte()
        octets[14] = batterie.coerceIn(0, 255).toByte()
        octets[15] = precisionM.coerceIn(0, 255).toByte()
        return octets
    }

    companion object {
        const val TAILLE = 16
        const val VERSION = 1
        const val BATTERIE_INCONNUE = 255

        /** `null` si ce n'est pas une trame de position que cette version sait lire. */
        fun lire(octets: ByteArray): TramePosition? {
            if (octets.size != TAILLE) return null
            val tete = octets[0].toInt() and 0xff
            if (tete shr 4 != VERSION) return null
            val genre = Genre.entries.firstOrNull { it.code == (tete and 0x0f) } ?: return null
            return TramePosition(
                genre = genre,
                latitude = octets.u32(1).toInt() / 1e7,     // toInt() : retrouve le signe
                longitude = octets.u32(5).toInt() / 1e7,
                instantS = octets.u32(9),
                statut = octets[13].toInt() and 0xff,
                batterie = octets[14].toInt() and 0xff,
                precisionM = octets[15].toInt() and 0xff,
            )
        }
    }
}
