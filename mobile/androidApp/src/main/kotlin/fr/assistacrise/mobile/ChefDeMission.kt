package fr.assistacrise.mobile

import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.MotifArret
import fr.assistacrise.mobile.donnees.Reponse
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Qui démarre et qui arrête le suivi en mission, le même code partout (22/11/2026) : l'écran,
 * le service de terrain, la tâche de fond application fermée. Avant, la décision vivait dans
 * le modèle de l'écran : application fermée, un engagement ne démarrait rien, et une libération
 * ne coupait la position qu'au retour à l'écran.
 */
class ChefDeMission(private val app: Application) {
    enum class Evenement { DEMARRE, FIN_D_ENGAGEMENT, PLAFOND, PERMISSION_MANQUANTE, SERVICE_REFUSE, RIEN }

    private val verrou = Mutex()

    /** Relit mes équipes au serveur, puis décide. Hors réseau, seul le plafond peut arrêter. */
    suspend fun releverEtPiloter(): Evenement {
        val reponse = app.equipes.rafraichir()
        return piloter(if (reponse is Reponse.Ok) app.equipes.equipes.value else null)
    }

    /** `connues` : mes équipes telles que le serveur vient de les donner, ou `null` s'il n'a pas répondu. */
    suspend fun piloter(equipesConnues: List<Equipe>?): Evenement = verrou.withLock {
        // Présences en manifestation comprises (27/11/2026).
        val connues = app.engagementsPourLeSuivi(equipesConnues)
        when (app.suivi.arreterSiBesoin(connues)) {
            MotifArret.FIN_D_ENGAGEMENT -> { ServiceTerrain.actualiser(app); app.alertes.geolocCoupee(); return@withLock Evenement.FIN_D_ENGAGEMENT }
            MotifArret.PLAFOND -> { ServiceTerrain.actualiser(app); app.alertes.geolocCoupee(plafond = true); return@withLock Evenement.PLAFOND }
            else -> Unit
        }
        if (connues != null && app.suivi.demarrerSiBesoin(connues)) {
            if (!ServiceTerrain.positionAutorisee(app)) {
                // Consentement donné, mais permission retirée depuis dans les réglages.
                app.suivi.arreterALaMain(connues)
                return@withLock Evenement.PERMISSION_MANQUANTE
            }
            val equipe = connues.firstOrNull { it.engagee }?.nom
            if (!ServiceTerrain.actualiser(app)) {
                // Android refuse de démarrer un service de premier plan depuis l'arrière-plan
                // sans exemption : on prévient, un toucher rouvre l'application qui le démarre.
                app.alertes.geolocActivee(equipe, ouvrirPourDemarrer = true)
                return@withLock Evenement.SERVICE_REFUSE
            }
            app.alertes.geolocActivee(equipe)
            return@withLock Evenement.DEMARRE
        }
        Evenement.RIEN
    }
}
