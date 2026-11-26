package fr.assistacrise.mobile

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.RemoteInput
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * « Répondre » depuis la notification d'un message radio (26/11/2026), comme les applications
 * MeshCore et Meshtastic : le texte part par la radio de la conversation, sans ouvrir
 * l'application. La notification disparaît si la radio a pris le message ; sinon, une
 * notification dit pourquoi rien n'est parti.
 */
class ReponseNotification : BroadcastReceiver() {
    override fun onReceive(contexte: Context, intent: Intent) {
        if (intent.action != ACTION) return
        val cle = intent.getStringExtra(EXTRA_CLE) ?: return
        val texte = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(CHAMP)?.toString()?.trim()
        val app = contexte.applicationContext as Application
        if (texte.isNullOrEmpty()) { app.alertes.retirerConversation(MessagerieRadio.idNotification(cle)); return }
        val attente = goAsync()
        CoroutineScope(Dispatchers.Default).launch {
            try {
                val ok = app.messagerieRadio.envoyer(cle, texte)
                app.messagerieRadio.marquerLue(cle)
                if (!ok) app.alertes.etat("radio-reponse:$cle", "Réponse non partie",
                    "La radio n'a pas pris le message (radio déconnectée, ou contact inconnu). Ouvrez la conversation pour réessayer.")
            } finally {
                attente.finish()
            }
        }
    }

    companion object {
        const val ACTION = "fr.assistacrise.mobile.REPONDRE_RADIO"
        const val EXTRA_CLE = "cle"
        const val CHAMP = "reponse"
    }
}
