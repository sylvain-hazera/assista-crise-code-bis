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
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Le suivi en mission (dossier § 6). Un service de premier plan : Android le garde en vie
 * écran éteint, et impose une notification permanente — c'est exactement ce qu'on veut,
 * « votre position est partagée » ne doit jamais pouvoir être oublié.
 *
 * Il ne décide de rien : démarrage, cadence et arrêt sont dans `ReglesSuivi` et `DepotSuivi`.
 * Lui lit le GPS, passe les relevés, et s'éteint quand on le lui dit.
 *
 * Positionnement par le système (`LocationManager`), sans les services Google : l'application
 * doit fonctionner sur un téléphone qui ne les a pas.
 */
class ServiceSuivi : Service(), LocationListener {
    private val app get() = application as Application
    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val positions by lazy { getSystemService(LocationManager::class.java) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_ARRETER) {
            portee.launch {
                app.suivi.arreterALaMain(app.equipes.equipes.value)
                eteindre()
            }
            return START_NOT_STICKY
        }
        if (!autorise(this)) { stopSelf(); return START_NOT_STICKY }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(ID_NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else {
            startForeground(ID_NOTIFICATION, notification())
        }
        ecouter()
        portee.launch {
            // Relancé par Android après avoir été tué : l'état est sur disque, pas en mémoire.
            app.session.restaurer(); app.file.restaurer(); app.equipes.restaurer(); app.suivi.restaurer()
            if (!app.suivi.etat.value.actif) { eteindre(); return@launch }
            // Le plafond joue même sans relevé ni réseau.
            while (true) {
                if (app.suivi.arreterSiBesoin(null) != null) { eteindre(); break }
                delay(60_000)
            }
        }
        return START_STICKY
    }

    @Suppress("MissingPermission")   // vérifiée par `autorise` avant d'arriver ici
    private fun ecouter() {
        for (source in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
            if (positions.allProviders.contains(source)) {
                positions.requestLocationUpdates(source, PERIODE_MS, 0f, this)
            }
        }
    }

    override fun onLocationChanged(position: Location) {
        portee.launch {
            val retenu = app.suivi.relever(Releve(position.latitude, position.longitude, System.currentTimeMillis(), position.accuracy))
            // Envoi tout de suite si possible ; sinon la position attend dans la file, et
            // seule la dernière y reste.
            if (retenu) app.synchro.envoyerLaFile(force = true)
            if (!app.suivi.etat.value.actif) eteindre()
        }
    }

    // Requis par l'interface sur les anciennes versions d'Android.
    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
    override fun onProviderEnabled(provider: String) = Unit
    override fun onProviderDisabled(provider: String) = Unit

    private fun eteindre() {
        positions.removeUpdates(this)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        positions.removeUpdates(this)
        portee.cancel()
        super.onDestroy()
    }

    private fun notification(): Notification {
        val gestionnaire = getSystemService(NotificationManager::class.java)
        gestionnaire.createNotificationChannel(
            NotificationChannel(CANAL, "Suivi en mission", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Affichée tant que votre position est partagée avec votre équipe."
            },
        )
        val ouvrir = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val arreter = PendingIntent.getService(
            this, 1, Intent(this, ServiceSuivi::class.java).setAction(ACTION_ARRETER), PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CANAL)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentTitle("Votre position est partagée")
            .setContentText("Suivi en mission actif. Il s'arrête à la fin de l'engagement.")
            .setOngoing(true)
            .setContentIntent(ouvrir)
            .addAction(Notification.Action.Builder(null, "Arrêter le suivi", arreter).build())
            .build()
    }

    companion object {
        private const val CANAL = "suivi"
        private const val ID_NOTIFICATION = 1
        private const val ACTION_ARRETER = "fr.assistacrise.mobile.ARRETER_SUIVI"
        private const val PERIODE_MS = 15_000L

        fun autorise(contexte: Context): Boolean =
            contexte.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                contexte.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        fun demarrer(contexte: Context) {
            if (autorise(contexte)) contexte.startForegroundService(Intent(contexte, ServiceSuivi::class.java))
        }

        fun arreter(contexte: Context) {
            contexte.stopService(Intent(contexte, ServiceSuivi::class.java))
        }
    }
}
