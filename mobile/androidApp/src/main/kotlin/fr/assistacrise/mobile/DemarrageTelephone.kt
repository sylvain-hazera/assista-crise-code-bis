package fr.assistacrise.mobile

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Au redémarrage du téléphone (ou après une mise à jour de l'application) : si une mission
 * était en cours ou une radio choisie, le service de terrain reprend seul (22/11/2026).
 * Android autorise ce démarrage depuis l'arrière-plan pour cette raison précise.
 */
class DemarrageTelephone : BroadcastReceiver() {
    override fun onReceive(contexte: Context, intent: Intent) {
        if (intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED)) return
        val app = contexte.applicationContext as Application
        val attente = goAsync()
        CoroutineScope(Dispatchers.Default).launch {
            try {
                app.restaurer()
                if (app.session.compte.value != null) {
                    app.radio.reprendreSiChoisie()
                    ServiceTerrain.actualiser(app)
                    Alertes.planifierLaVeille(app)
                }
            } finally {
                attente.finish()
            }
        }
    }
}
