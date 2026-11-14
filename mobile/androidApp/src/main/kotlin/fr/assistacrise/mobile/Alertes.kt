package fr.assistacrise.mobile

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import fr.assistacrise.mobile.domaine.Alerte
import java.util.concurrent.TimeUnit

/**
 * Les notifications du système : ce qui fait sonner le téléphone.
 *
 * Deux canaux, parce qu'Android laisse la personne régler chacun à part : on peut vouloir
 * couper le son des messages d'équipe sans rater une demande de mobilisation urgente.
 */
class Alertes(private val contexte: Context) {
    private val gestionnaire = NotificationManagerCompat.from(contexte)

    /** Le système affichera-t-il ce qu'on lui confie ? Dit au serveur, qui le montre à l'encadrement. */
    val autorisees: Boolean
        get() = gestionnaire.areNotificationsEnabled() && (
            Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                contexte.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            )

    /**
     * @return vrai si le système a accepté de l'afficher. C'est sur cette réponse qu'une
     * notification est accusée « remise » : on n'affirme pas avoir prévenu sans l'avoir fait.
     */
    @Suppress("MissingPermission")   // vérifiée par `autorisees`
    fun afficher(alerte: Alerte): Boolean {
        if (!autorisees) return false
        creerLesCanaux()
        val ouvrir = Intent(contexte, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_GENRE, alerte.genre.name)
            putExtra(EXTRA_CIBLE, alerte.cible)
        }
        val identifiant = alerte.cle.hashCode()
        val notification = NotificationCompat.Builder(contexte, if (alerte.urgent) CANAL_URGENT else CANAL)
            .setSmallIcon(R.drawable.ic_alerte)
            .setContentTitle(alerte.titre)
            .setContentText(alerte.texte)
            .setStyle(NotificationCompat.BigTextStyle().bigText(alerte.texte))
            .setAutoCancel(true)
            .setCategory(if (alerte.genre == Alerte.Genre.MESSAGE) NotificationCompat.CATEGORY_MESSAGE else NotificationCompat.CATEGORY_EVENT)
            .setPriority(if (alerte.urgent) NotificationCompat.PRIORITY_MAX else NotificationCompat.PRIORITY_HIGH)
            // Écran verrouillé : on montre qu'il y a quelque chose, pas ce que c'est. Le texte
            // d'une mobilisation n'a pas à se lire par-dessus une épaule.
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(PendingIntent.getActivity(contexte, identifiant, ouvrir, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
            .build()
        return runCatching { gestionnaire.notify(identifiant, notification) }.isSuccess
    }

    /** L'alerte a été traitée dans l'application : inutile qu'elle reste dans le volet. */
    fun retirer(cle: String) = gestionnaire.cancel(cle.hashCode())

    fun toutRetirer() = gestionnaire.cancelAll()

    private fun creerLesCanaux() {
        val systeme = contexte.getSystemService(NotificationManager::class.java)
        systeme.createNotificationChannel(
            NotificationChannel(CANAL, "Messages et missions", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Demandes de disponibilités, messages de vos équipes, nouvelles missions."
            },
        )
        systeme.createNotificationChannel(
            NotificationChannel(CANAL_URGENT, "Urgent", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Mobilisation en cours de crise et messages marqués urgents."
                enableVibration(true)
            },
        )
    }

    companion object {
        const val EXTRA_GENRE = "alerte.genre"
        const val EXTRA_CIBLE = "alerte.cible"
        private const val CANAL = "messages"
        private const val CANAL_URGENT = "urgent"
        private const val TACHE = "veille"

        /**
         * Application fermée, c'est cette tâche qui vient relever le serveur. Un quart d'heure
         * est le plus court intervalle qu'Android accorde à une tâche périodique — et il peut
         * l'allonger en économie d'énergie. C'est la limite connue de ce choix (pas de service
         * de réveil d'un fabricant) : une mobilisation urgente se double d'un SMS.
         */
        fun planifierLaVeille(contexte: Context) {
            val tache = PeriodicWorkRequestBuilder<TacheVeille>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(contexte).enqueueUniquePeriodicWork(TACHE, ExistingPeriodicWorkPolicy.KEEP, tache)
        }

        fun arreterLaVeille(contexte: Context) {
            WorkManager.getInstance(contexte).cancelUniqueWork(TACHE)
        }
    }
}

/** Le relevé de fond. Ne décide de rien : tout est dans `Veille`, le même code qu'application ouverte. */
class TacheVeille(contexte: Context, parametres: WorkerParameters) : CoroutineWorker(contexte, parametres) {
    override suspend fun doWork(): Result {
        val app = applicationContext as Application
        app.restaurer()
        if (app.session.compte.value == null) return Result.success()
        // La file d'abord : un message écrit sans réseau part dès que la tâche a du réseau,
        // sans attendre que la personne rouvre l'application.
        app.synchro.envoyerLaFile()
        app.veille.relever { app.alertes.afficher(it) }
        return Result.success()
    }
}
