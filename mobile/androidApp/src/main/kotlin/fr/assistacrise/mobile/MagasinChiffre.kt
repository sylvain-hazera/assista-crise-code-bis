package fr.assistacrise.mobile

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import fr.assistacrise.mobile.donnees.Magasin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * La règle du projet, transposée au téléphone : on ne stocke rien en clair.
 *
 * Chaque fichier est chiffré en AES-256-GCM par une clé créée dans le Keystore Android, qui
 * n'en sort jamais — ni l'application ni une sauvegarde ne peuvent la lire. Le nom du
 * fichier est lié au contenu (données authentifiées) : on ne peut pas faire passer un
 * fichier pour un autre en les intervertissant.
 */
class MagasinChiffre(private val dossier: File) : Magasin {

    init { dossier.mkdirs() }

    override suspend fun lire(nom: String): String? = withContext(Dispatchers.IO) {
        val fichier = File(dossier, nom)
        if (!fichier.exists()) return@withContext null
        // Illisible = absent. Une clé perdue (restauration, réinitialisation du Keystore)
        // doit ramener à l'écran de connexion, pas faire planter le démarrage.
        runCatching {
            val octets = fichier.readBytes()
            val chiffre = Cipher.getInstance(TRANSFORMATION)
            chiffre.init(Cipher.DECRYPT_MODE, cle(), GCMParameterSpec(128, octets, 0, TAILLE_IV))
            chiffre.updateAAD(nom.toByteArray())
            String(chiffre.doFinal(octets, TAILLE_IV, octets.size - TAILLE_IV), Charsets.UTF_8)
        }.getOrNull()
    }

    override suspend fun ecrire(nom: String, contenu: String) = withContext(Dispatchers.IO) {
        val chiffre = Cipher.getInstance(TRANSFORMATION)
        chiffre.init(Cipher.ENCRYPT_MODE, cle())   // le Keystore tire lui-même un IV neuf
        chiffre.updateAAD(nom.toByteArray())
        val octets = chiffre.iv + chiffre.doFinal(contenu.toByteArray(Charsets.UTF_8))
        // Écriture à côté puis renommage : une coupure de courant laisse l'ancien fichier
        // entier, jamais un fichier à moitié écrit.
        val provisoire = File(dossier, "$nom.tmp")
        provisoire.writeBytes(octets)
        if (!provisoire.renameTo(File(dossier, nom))) error("Écriture impossible : $nom")
    }

    override suspend fun effacer(nom: String) {
        withContext(Dispatchers.IO) { File(dossier, nom).delete() }
    }

    private fun cle(): SecretKey {
        val coffre = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (coffre.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generateur = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generateur.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generateur.generateKey()
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "assista-crise-magasin"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val TAILLE_IV = 12
    }
}
