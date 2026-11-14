package fr.assistacrise.mobile

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.exifinterface.media.ExifInterface
import fr.assistacrise.mobile.domaine.PhotoEnAttente
import fr.assistacrise.mobile.domaine.Releve
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * De la prise de vue aux octets qui partiront : réduire, dater, situer, sceller.
 *
 * Le serveur a déjà son circuit de traçabilité (`DocumentViewSet`) : il calcule l'empreinte
 * SHA-256 du fichier reçu, lit la position dans les métadonnées de la photo (et la range
 * parmi les données réservées à l'équipe), et journalise le dépôt puis chaque consultation.
 * Ce fichier fait la moitié « téléphone » de ce circuit, de sorte qu'il s'applique à
 * l'identique à une photo prise ici :
 *
 * - la position est **inscrite dans la photo**, au moment de la prise, par l'application —
 *   l'appareil photo du téléphone ne l'écrit que si la personne a activé un réglage, et la
 *   réduction d'image l'effacerait de toute façon ;
 * - l'empreinte est calculée **ici**, sur les octets définitifs, pour être comparée à celle du
 *   serveur : si elles diffèrent, ce qu'il a reçu n'est pas ce qui a été pris.
 *
 * La prise ne passe par la galerie à aucun moment. Elle séjourne quelques secondes en clair
 * dans le cache privé de l'application (l'appareil photo ne sait écrire qu'un fichier), puis
 * ce fichier est effacé et seuls restent les octets chiffrés du magasin.
 */
object Photographe {
    private const val COTE_MAX = 2048
    private const val QUALITE = 85

    /** Où l'appareil photo écrira : un fichier du cache, et l'adresse qu'on lui prête. */
    fun nouvellePrise(contexte: Context): Pair<File, Uri> {
        val dossier = File(contexte.cacheDir, "prises").apply { mkdirs() }
        // Une prise abandonnée (application tuée pendant la photo) ne traîne pas.
        dossier.listFiles()?.forEach { it.delete() }
        val fichier = File(dossier, "prise-${System.currentTimeMillis()}.jpg")
        return fichier to FileProvider.getUriForFile(contexte, "${contexte.packageName}.prises", fichier)
    }

    /**
     * @param position là où se trouve le téléphone au moment de la prise, ou `null` si la
     * personne n'a pas autorisé la position — la photo part alors sans lieu, et l'écran le dit.
     * @return les octets définitifs et leur fiche, ou `null` si la prise est illisible.
     */
    suspend fun preparer(fichier: File, position: Releve?, commentaire: String, version: String): Pair<ByteArray, PhotoEnAttente>? =
        withContext(Dispatchers.IO) {
            val sortie = File(fichier.parentFile, "sortie-${fichier.name}")
            try {
                val image = reduire(fichier) ?: return@withContext null
                sortie.outputStream().use { image.compress(Bitmap.CompressFormat.JPEG, QUALITE, it) }
                image.recycle()

                val maintenant = System.currentTimeMillis()
                ExifInterface(sortie).apply {
                    setAttribute(ExifInterface.TAG_DATETIME_ORIGINAL, format("yyyy:MM:dd HH:mm:ss", maintenant, TimeZone.getDefault()))
                    // La même heure dans le champ principal : c'est celui que le serveur relève.
                    setAttribute(ExifInterface.TAG_DATETIME, format("yyyy:MM:dd HH:mm:ss", maintenant, TimeZone.getDefault()))
                    setAttribute(ExifInterface.TAG_SOFTWARE, "Reserve Resilience $version")
                    if (position != null) {
                        setLatLong(position.latitude, position.longitude)
                        // Heure du relevé en temps universel, comme le veut la norme : c'est elle
                        // qui dit si la position est bien celle du moment de la photo.
                        setAttribute(ExifInterface.TAG_GPS_DATESTAMP, format("yyyy:MM:dd", position.instant, UTC))
                        setAttribute(ExifInterface.TAG_GPS_TIMESTAMP, format("HH:mm:ss", position.instant, UTC))
                        setAttribute(ExifInterface.TAG_GPS_H_POSITIONING_ERROR, "${(position.precisionM * 100).toInt()}/100")
                    }
                    saveAttributes()
                }
                val octets = sortie.readBytes()
                octets to PhotoEnAttente(
                    cle = "", empreinte = empreinte(octets), commentaire = commentaire.trim(), priseLe = maintenant,
                    latitude = position?.latitude, longitude = position?.longitude, precisionM = position?.precisionM,
                )
            } catch (e: Exception) {
                null
            } finally {
                fichier.delete(); sortie.delete()
            }
        }

    fun empreinte(octets: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(octets).joinToString("") { "%02x".format(it) }

    /** Réduite à 2048 px de grand côté, et remise droite : l'orientation n'est plus dans le fichier final. */
    private fun reduire(fichier: File): Bitmap? {
        val bornes = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(fichier.path, bornes)
        if (bornes.outWidth <= 0) return null
        var pas = 1
        while (maxOf(bornes.outWidth, bornes.outHeight) / (pas * 2) >= COTE_MAX) pas *= 2
        val brute = BitmapFactory.decodeFile(fichier.path, BitmapFactory.Options().apply { inSampleSize = pas }) ?: return null
        val echelle = minOf(1f, COTE_MAX.toFloat() / maxOf(brute.width, brute.height))
        val rotation = when (ExifInterface(fichier).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
        if (echelle == 1f && rotation == 0f) return brute
        val matrice = Matrix().apply { postScale(echelle, echelle); postRotate(rotation) }
        return Bitmap.createBitmap(brute, 0, 0, brute.width, brute.height, matrice, true).also { if (it !== brute) brute.recycle() }
    }

    /** Une vignette pour l'écran, décodée petite : on n'affiche pas douze photos pleine taille. */
    fun vignette(octets: ByteArray, cote: Int = 480): Bitmap? {
        val bornes = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(octets, 0, octets.size, bornes)
        if (bornes.outWidth <= 0) return null
        var pas = 1
        while (maxOf(bornes.outWidth, bornes.outHeight) / (pas * 2) >= cote) pas *= 2
        return BitmapFactory.decodeByteArray(octets, 0, octets.size, BitmapFactory.Options().apply { inSampleSize = pas })
    }

    private val UTC = TimeZone.getTimeZone("UTC")
    private fun format(motif: String, instant: Long, fuseau: TimeZone): String =
        SimpleDateFormat(motif, Locale.US).apply { timeZone = fuseau }.format(Date(instant))
}
