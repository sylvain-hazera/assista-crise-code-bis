package fr.assistacrise.mobile

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.IBinder
import fr.assistacrise.mobile.domaine.Releve
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * Le service de terrain (22/11/2026), qui remplace le seul suivi de position. Un service de
 * premier plan, avec deux raisons d'exister, chacune visible dans la notification :
 *
 * - **la radio** : tant qu'une radio Meshtastic ou MeshCore est choisie, la liaison reste
 *   ouverte écran éteint et application fermée (« ça ne doit pas s'interrompre ») ;
 * - **la mission** : tant qu'une de mes équipes est engagée, la position est relevée et
 *   partagée — et seulement alors. « La géolocalisation doit rester activée le temps de la
 *   mission, elle se redésactive dès que l'intervenant est libéré. »
 *
 * Sans l'une ni l'autre, il s'arrête. Il ne décide de rien : démarrage et arrêt du suivi sont
 * dans `ChefDeMission` (et derrière, `ReglesSuivi`), la radio dans `LiaisonRadio`. Lui tient
 * le processus en vie, relève le serveur à intervalle régulier (c'est ainsi qu'il apprend un
 * engagement ou une libération application fermée), lit le GPS, envoie la file.
 *
 * Règle du dossier § 6, inchangée : le démarrage du suivi exige le serveur, l'arrêt jamais.
 */
class ServiceTerrain : Service(), LocationListener {
    private val app get() = application as Application
    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val positions by lazy { getSystemService(LocationManager::class.java) }
    private var boucle: Job? = null
    private var ecoute = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_ARRETER_SUIVI) {
            portee.launch {
                app.suivi.arreterALaMain(app.equipes.equipes.value)
                mettreAJour()
            }
            return START_STICKY
        }
        // Android exige l'appel à startForeground dans les secondes qui suivent : d'abord la
        // notification, avec ce qu'on sait déjà, puis l'état relu du disque.
        if (!passerAuPremierPlan()) { stopSelf(); return START_NOT_STICKY }
        if (boucle == null) boucle = portee.launch { vivre() }
        return START_STICKY
    }

    private suspend fun vivre() {
        // Relancé par Android après avoir été tué, ou au redémarrage du téléphone : l'état est
        // sur disque, pas en mémoire.
        app.restaurer()
        app.radio.reprendre()
        portee.launch { app.radio.etat.collectLatest { mettreAJour() } }
        portee.launch { app.suivi.etat.collectLatest { mettreAJour() } }
        while (true) {
            // Le serveur dit si une de mes équipes est engagée, ou libérée. Hors réseau, seul
            // le plafond peut arrêter le suivi (ChefDeMission le vérifie à chaque tour).
            runCatching { app.chef.releverEtPiloter() }
            runCatching { app.synchro.envoyerLaFile() }
            runCatching { app.veille.relever { app.alertes.afficher(it) } }
            if (!mettreAJour()) break
            delay(if (app.suivi.etat.value.actif) PERIODE_MISSION_MS else PERIODE_RADIO_MS)
        }
    }

    /** Adapte le service à l'état : position en mission seulement, radio si choisie. @return faux s'il s'arrête. */
    private fun mettreAJour(): Boolean {
        val mission = app.suivi.etat.value.actif && positionAutorisee(this)
        val radio = app.radio.choisie()
        if (!mission && !radio) { eteindre(); return false }
        if (mission && !ecoute) ecouter()
        if (!mission && ecoute) { positions.removeUpdates(this); ecoute = false }
        passerAuPremierPlan()
        return true
    }

    private fun passerAuPremierPlan(): Boolean {
        val mission = app.suivi.etat.value.actif && positionAutorisee(this)
        val radio = app.radio.choisie() && radioAutorisee(this)
        if (!mission && !radio) return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            var types = 0
            if (mission) types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
            if (radio) types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            runCatching { startForeground(ID_NOTIFICATION, notification(mission), types) }
                .onFailure { return false }
        } else {
            startForeground(ID_NOTIFICATION, notification(mission))
        }
        return true
    }

    /**
     * Cadence adaptée au déplacement (budget batterie, dossier § 6) : le GPS ne rend une
     * position que tous les 30 s ET 50 m ; immobile, le réseau en donne une toutes les 5 min.
     */
    @Suppress("MissingPermission")   // vérifiée par `positionAutorisee` avant d'arriver ici
    private fun ecouter() {
        if (positions.allProviders.contains(LocationManager.GPS_PROVIDER)) {
            positions.requestLocationUpdates(LocationManager.GPS_PROVIDER, PERIODE_GPS_MS, DISTANCE_GPS_M, this)
        }
        if (positions.allProviders.contains(LocationManager.NETWORK_PROVIDER)) {
            positions.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, PERIODE_IMMOBILE_MS, 0f, this)
        }
        ecoute = true
    }

    override fun onLocationChanged(position: Location) {
        portee.launch {
            val retenu = app.suivi.relever(Releve(position.latitude, position.longitude, System.currentTimeMillis(), position.accuracy))
            // Envoi tout de suite si possible ; sinon la position attend dans la file, et seule
            // la dernière y reste.
            if (retenu) app.synchro.envoyerLaFile(force = true)
            mettreAJour()
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
    override fun onProviderEnabled(provider: String) = Unit
    override fun onProviderDisabled(provider: String) = Unit

    private fun eteindre() {
        if (ecoute) { positions.removeUpdates(this); ecoute = false }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        if (ecoute) positions.removeUpdates(this)
        portee.cancel()
        super.onDestroy()
    }

    private fun notification(mission: Boolean): Notification {
        val gestionnaire = getSystemService(NotificationManager::class.java)
        gestionnaire.createNotificationChannel(
            NotificationChannel(CANAL, "Terrain : radio et suivi en mission", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Affichée tant que la radio est connectée ou que votre position est partagée."
            },
        )
        val ouvrir = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val radio = app.radio.etat.value
        val texteRadio = when {
            !app.radio.choisie() -> null
            radio.phase == LiaisonRadio.Phase.PRETE -> "Radio ${radio.protocole?.libelle ?: ""} connectée : ${radio.nom ?: ""}".trim()
            else -> "Radio : reconnexion en cours…"
        }
        val constructeur = Notification.Builder(this, CANAL)
            .setOngoing(true)
            .setContentIntent(ouvrir)
        if (mission) {
            val equipe = app.equipes.equipes.value.firstOrNull { it.engagementDebut != null }?.nom
            val arreter = PendingIntent.getService(
                this, 1, Intent(this, ServiceTerrain::class.java).setAction(ACTION_ARRETER_SUIVI), PendingIntent.FLAG_IMMUTABLE,
            )
            constructeur
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentTitle(if (app.session.enFormation) "Formation — votre position est partagée" else "En mission — votre position est partagée")
                .setContentText(listOfNotNull(equipe?.let { "Équipe $it" }, texteRadio).joinToString(" · ")
                    .ifEmpty { "Le suivi s'arrête seul à votre libération." })
                .addAction(Notification.Action.Builder(null, "Arrêter le suivi", arreter).build())
        } else {
            constructeur
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setContentTitle(texteRadio ?: "Radio")
                .setContentText("Position non partagée : vous n'êtes pas en mission.")
        }
        return constructeur.build()
    }

    companion object {
        private const val CANAL = "terrain"
        private const val ID_NOTIFICATION = 1
        private const val ACTION_ARRETER_SUIVI = "fr.assistacrise.mobile.ARRETER_SUIVI"
        private const val PERIODE_GPS_MS = 30_000L
        private const val DISTANCE_GPS_M = 50f
        private const val PERIODE_IMMOBILE_MS = 300_000L
        /** Relève du serveur : en mission, une libération doit couper la position vite. */
        private const val PERIODE_MISSION_MS = 60_000L
        private const val PERIODE_RADIO_MS = 300_000L

        fun positionAutorisee(contexte: Context): Boolean =
            contexte.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                contexte.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        /** Ancien nom, gardé pour les écrans qui lisent la position à la demande. */
        fun autorise(contexte: Context): Boolean = positionAutorisee(contexte)

        fun radioAutorisee(contexte: Context): Boolean =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
                contexte.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED

        /** La position peut-elle être relevée application fermée ? (Android 10+ : permission à part.) */
        fun positionEnArrierePlan(contexte: Context): Boolean =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.Q ||
                contexte.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED

        /**
         * Démarre le service s'il a une raison d'être (mission en cours ou radio choisie), ou le
         * laisse s'arrêter de lui-même. Appelé après chaque changement : consentement, radio,
         * engagement, libération. @return faux si Android a refusé le démarrage (application
         * en arrière-plan sans exemption) : l'appelant prévient alors la personne.
         */
        fun actualiser(contexte: Context): Boolean {
            val app = contexte.applicationContext as Application
            val utile = (app.suivi.etat.value.actif && positionAutorisee(contexte)) || app.radio.choisie()
            if (!utile) { contexte.stopService(Intent(contexte, ServiceTerrain::class.java)); return true }
            return runCatching { contexte.startForegroundService(Intent(contexte, ServiceTerrain::class.java)) }.isSuccess
        }

        fun arreter(contexte: Context) {
            contexte.stopService(Intent(contexte, ServiceTerrain::class.java))
        }
    }
}
