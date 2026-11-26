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

    /** Mes noms (compte, nœuds radio), pour reconnaître une mention « @Léa » (23/11/2026). */
    var mesNoms: () -> Collection<String> = { emptyList() }

    fun estUneMention(texte: String): Boolean = fr.assistacrise.mobile.domaine.Mentions.mentionne(texte, mesNoms())

    /**
     * On m'a mentionné : une notification à part, sur son propre canal Android (plus insistant que
     * les messages), qui sonne même si la conversation a déjà sonné ou si le canal radio est muet.
     */
    @Suppress("MissingPermission")   // vérifiée par `autorisees`
    fun mention(id: String, ou: String, texte: String, genre: Alerte.Genre, cible: String): Boolean {
        if (!autorisees) return false
        creerLesCanaux()
        val ouvrir = Intent(contexte, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_GENRE, genre.name)
            putExtra(EXTRA_CIBLE, cible)
        }
        val n = NotificationCompat.Builder(contexte, CANAL_MENTION)
            .setSmallIcon(R.drawable.ic_alerte)
            .setContentTitle("Vous êtes mentionné · $ou")
            .setContentText(texte.take(160))
            .setStyle(NotificationCompat.BigTextStyle().bigText(texte.take(400)))
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(PendingIntent.getActivity(contexte, "mention:$id".hashCode(), ouvrir, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
            .build()
        return runCatching { gestionnaire.notify("mention:$id".hashCode(), n) }.isSuccess
    }

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
        if (alerte.genre == Alerte.Genre.MESSAGE && estUneMention(alerte.texte)) {
            return mention(alerte.cle, alerte.titre, alerte.texte, alerte.genre, alerte.cible)
        }
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
    /**
     * « Prévenir que la géolocalisation est activée » (22/11/2026) : une notification sonore, en
     * plus de la notification permanente du service, au moment où le suivi démarre. Si Android a
     * refusé de démarrer le service depuis l'arrière-plan, un toucher rouvre l'application, qui
     * le démarre.
     */
    @Suppress("MissingPermission")   // vérifiée par `autorisees`
    fun geolocActivee(equipe: String?, ouvrirPourDemarrer: Boolean = false) {
        if (!autorisees) return
        val ouvrir = PendingIntent.getActivity(contexte, 2, Intent(contexte, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val texte = if (ouvrirPourDemarrer) "Votre équipe est engagée. Touchez pour activer le partage de votre position."
                    else "Votre position est partagée${equipe?.let { " avec l'équipe $it" } ?: ""} pendant la mission. Elle s'arrêtera à votre libération."
        gestionnaire.notify(ID_GEOLOC, NotificationCompat.Builder(contexte, CANAL_URGENT)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentTitle("Géolocalisation activée — en mission")
            .setContentText(texte)
            .setStyle(NotificationCompat.BigTextStyle().bigText(texte))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(ouvrir)
            .build())
    }

    /** La position n'est plus partagée : libération, ou plafond de douze heures. */
    @Suppress("MissingPermission")   // vérifiée par `autorisees`
    fun geolocCoupee(plafond: Boolean = false) {
        if (!autorisees) return
        val texte = if (plafond) "Le partage de votre position s'est arrêté après douze heures."
                    else "Vous êtes libéré : votre position n'est plus partagée."
        gestionnaire.notify(ID_GEOLOC, NotificationCompat.Builder(contexte, CANAL)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentTitle("Géolocalisation désactivée")
            .setContentText(texte)
            .setAutoCancel(true)
            .build())
    }

    // --- Conversations (radio, équipes) et état de l'application (23/11/2026) -----------------

    private val lignesParConversation = java.util.concurrent.ConcurrentHashMap<String, MutableList<String>>()

    /**
     * Une notification PAR conversation, mise à jour à chaque message : les derniers messages en
     * liste, le nombre en titre, et une seule sonnerie jusqu'à ce qu'on l'ouvre (un canal bavard
     * ne fait pas vibrer le téléphone à chaque trame). `cible` : ce qu'un toucher ouvre.
     */
    @Suppress("MissingPermission")   // vérifiée par `autorisees`
    fun conversation(id: String, titre: String, ligne: String, genre: Alerte.Genre, cible: String, radio: Boolean = true): Boolean {
        if (!autorisees) return false
        creerLesCanaux()
        if (estUneMention(ligne)) mention("$id:${ligne.hashCode()}", titre, ligne, genre, cible)
        val lignes = lignesParConversation.getOrPut(id) { mutableListOf() }
        synchronized(lignes) { lignes += ligne.take(160); while (lignes.size > 6) lignes.removeAt(0) }
        val total = (compteParConversation.merge(id, 1, Int::plus) ?: 1)
        val ouvrir = Intent(contexte, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_GENRE, genre.name)
            putExtra(EXTRA_CIBLE, cible)
        }
        val style = NotificationCompat.InboxStyle().also { s -> synchronized(lignes) { lignes.forEach { s.addLine(it) } } }
        if (total > 1) style.setSummaryText("$total messages")
        val constructeur = NotificationCompat.Builder(contexte, if (radio) CANAL_RADIO else CANAL)
        // Conversation radio : « Répondre » sans ouvrir l'application (26/11/2026).
        if (cible.startsWith(MessagerieRadio.CIBLE)) {
            val cle = cible.removePrefix(MessagerieRadio.CIBLE)
            val envoi = Intent(contexte, ReponseNotification::class.java).apply {
                action = ReponseNotification.ACTION
                putExtra(ReponseNotification.EXTRA_CLE, cle)
            }
            // MUTABLE : Android y écrit le texte saisi.
            val pi = PendingIntent.getBroadcast(contexte, id.hashCode(), envoi, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
            val saisie = androidx.core.app.RemoteInput.Builder(ReponseNotification.CHAMP).setLabel("Réponse par la radio").build()
            constructeur.addAction(NotificationCompat.Action.Builder(R.drawable.ic_alerte, "Répondre", pi)
                .addRemoteInput(saisie).setAllowGeneratedReplies(false)
                .setSemanticAction(NotificationCompat.Action.SEMANTIC_ACTION_REPLY).build())
        }
        val notification = constructeur
            .setSmallIcon(R.drawable.ic_alerte)
            .setContentTitle(if (total > 1) "$titre ($total)" else titre)
            .setContentText(ligne.take(160))
            .setStyle(style)
            .setNumber(total)
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(PendingIntent.getActivity(contexte, id.hashCode(), ouvrir, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
            .build()
        return runCatching { gestionnaire.notify(id.hashCode(), notification) }.isSuccess
    }

    private val compteParConversation = java.util.concurrent.ConcurrentHashMap<String, Int>()

    /** La conversation est ouverte : sa notification disparaît, son compte repart de zéro. */
    fun retirerConversation(id: String) {
        lignesParConversation.remove(id); compteParConversation.remove(id)
        gestionnaire.cancel(id.hashCode())
    }

    /** Une information sur l'application elle-même (synchronisation, radio perdue) : sans bruit. */
    @Suppress("MissingPermission")   // vérifiée par `autorisees`
    fun etat(id: String, titre: String, texte: String) {
        if (!autorisees) return
        creerLesCanaux()
        val ouvrir = PendingIntent.getActivity(contexte, id.hashCode(), Intent(contexte, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        runCatching {
            gestionnaire.notify(id.hashCode(), NotificationCompat.Builder(contexte, CANAL_ETAT)
                .setSmallIcon(R.drawable.ic_alerte).setContentTitle(titre).setContentText(texte)
                .setStyle(NotificationCompat.BigTextStyle().bigText(texte))
                .setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_DEFAULT).setContentIntent(ouvrir).build())
        }
    }

    fun retirerEtat(id: String) = gestionnaire.cancel(id.hashCode())

    fun retirer(cle: String) = gestionnaire.cancel(cle.hashCode())

    fun toutRetirer() = gestionnaire.cancelAll()

    fun creerLesCanaux() {
        val systeme = contexte.getSystemService(NotificationManager::class.java)
        systeme.createNotificationChannel(
            NotificationChannel(CANAL, "Messages et missions", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Demandes de disponibilités, messages de vos équipes, nouvelles missions."
            },
        )
        systeme.createNotificationChannel(
            NotificationChannel(CANAL_MENTION, "Mentions", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Quelqu'un vous mentionne (« @votre nom ») dans une équipe ou un canal radio."
            },
        )
        systeme.createNotificationChannel(
            NotificationChannel(CANAL_RADIO, "Messages radio", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Messages reçus par la radio Meshtastic ou MeshCore : canaux, équipes, messages directs."
            },
        )
        systeme.createNotificationChannel(
            NotificationChannel(CANAL_ETAT, "État de l'application", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Envois partis au retour du réseau, envois refusés, radio perdue puis retrouvée."
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
        private const val CANAL_RADIO = "radio"
        private const val CANAL_MENTION = "mention"
        private const val CANAL_ETAT = "etat"
        private const val TACHE = "veille"
        private const val ID_GEOLOC = 7_001

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
        // Un engagement ou une libération, application fermée : le suivi démarre ou s'arrête
        // ici même si le service de terrain ne tourne pas (22/11/2026).
        runCatching { app.chef.releverEtPiloter() }
        app.veille.relever(relire = false) { app.alertes.afficher(it) }
        // Une radio choisie mais le service tué : on le relance.
        app.radio.reprendreSiChoisie()
        ServiceTerrain.actualiser(app)
        return Result.success()
    }
}
