package fr.assistacrise.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.assistacrise.mobile.ui.BarreDuBas
import fr.assistacrise.mobile.domaine.Mode
import fr.assistacrise.mobile.ui.EcranAide
import fr.assistacrise.mobile.ui.EcranCarte
import fr.assistacrise.mobile.ui.EcranDepot
import fr.assistacrise.mobile.ui.EcranDisponibilites
import fr.assistacrise.mobile.ui.EcranDossier
import fr.assistacrise.mobile.ui.EcranFiche
import fr.assistacrise.mobile.ui.EcranInterventions
import fr.assistacrise.mobile.ui.EcranNotification
import fr.assistacrise.mobile.ui.EcranNotifications
import fr.assistacrise.mobile.ui.EcranCompte
import fr.assistacrise.mobile.ui.EcranEquipes
import fr.assistacrise.mobile.ui.EcranMessagerie
import fr.assistacrise.mobile.ui.EcranConnexion
import fr.assistacrise.mobile.ui.EcranInscription
import fr.assistacrise.mobile.ui.EcranMissions
import fr.assistacrise.mobile.ui.ThemeApplication

class MainActivity : ComponentActivity() {
    /** La notification du système qu'on vient de toucher, à ouvrir dès que l'écran est prêt. */
    private var alerteTouchee by mutableStateOf<Pair<String?, String?>?>(null)

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        lireAlerte(intent)
    }

    private fun lireAlerte(intent: Intent?) {
        val cible = intent?.getStringExtra(Alertes.EXTRA_CIBLE) ?: return
        alerteTouchee = intent.getStringExtra(Alertes.EXTRA_GENRE) to cible
        // Lue une fois : une rotation d'écran ne doit pas rouvrir la même chose.
        intent.removeExtra(Alertes.EXTRA_CIBLE)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) lireAlerte(intent)
        enableEdgeToEdge()
        setContent {
            ThemeApplication {
                val modele: ModeleApplication = viewModel(factory = ModeleApplication.Fabrique)
                val compte by modele.compte.collectAsStateWithLifecycle()
                val bandeau = remember { SnackbarHostState() }

                LifecycleResumeEffect(Unit) {
                    modele.auPremierPlan()
                    onPauseOrDispose { modele.enArrierePlan() }
                }

                LaunchedEffect(alerteTouchee, modele.pret) {
                    val alerte = alerteTouchee
                    if (alerte != null && modele.pret) { modele.ouvrirDepuisAlerte(alerte.first, alerte.second); alerteTouchee = null }
                }

                // Android 13 et suivants : sans cet accord, rien ne sonne. On le demande une fois,
                // à la première ouverture connectée — pas avant que la personne sache pourquoi.
                val demandeNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { modele.auPremierPlan() }
                LaunchedEffect(compte?.id) {
                    if (compte != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                        checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                    ) demandeNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                }

                LaunchedEffect(modele.message) {
                    modele.message?.let { bandeau.showSnackbar(it); modele.messageLu() }
                }

                // L'écran affiché découle du compte, pas l'inverse : une session qui expire
                // ramène à la connexion sans que personne n'ait à y penser.
                val mesEquipes by modele.equipes.collectAsStateWithLifecycle()
                val intervenant = compte?.mode == Mode.INTERVENANT || mesEquipes.isNotEmpty()
                val ecran = when {
                    compte == null && modele.ecran == Ecran.INSCRIPTION -> Ecran.INSCRIPTION
                    compte == null -> Ecran.CONNEXION
                    // Mode citoyen : rien de l'intervenant n'est visible (dossier § 13).
                    !intervenant && modele.ecran !in setOf(Ecran.AIDE, Ecran.DEPOT, Ecran.COMPTE, Ecran.NOTIFICATIONS, Ecran.NOTIFICATION, Ecran.DISPONIBILITES, Ecran.FICHE) -> Ecran.AIDE
                    modele.ecran == Ecran.CONNEXION || modele.ecran == Ecran.INSCRIPTION -> Ecran.MISSIONS
                    else -> modele.ecran
                }
                BackHandler(enabled = ecran == Ecran.INSCRIPTION) { modele.aller(Ecran.CONNEXION) }
                BackHandler(enabled = ecran == Ecran.MESSAGERIE) { modele.aller(Ecran.EQUIPES) }
                BackHandler(enabled = ecran == Ecran.DEPOT) { modele.fermerDepot() }
                BackHandler(enabled = ecran == Ecran.DOSSIER) { modele.fermerDossier() }
                BackHandler(enabled = ecran in setOf(Ecran.NOTIFICATIONS, Ecran.FICHE, Ecran.INTERVENTIONS)) { modele.aller(Ecran.COMPTE) }
                BackHandler(enabled = ecran == Ecran.NOTIFICATION) { modele.ouvrirNotifications() }
                BackHandler(enabled = ecran == Ecran.DISPONIBILITES) {
                    val ouverte = modele.notificationOuverte
                    if (ouverte != null && modele.grille.value?.campagne != null) modele.ouvrirNotification(ouverte) else modele.aller(Ecran.COMPTE)
                }
                BackHandler(enabled = ecran in setOf(Ecran.EQUIPES, Ecran.CARTE, Ecran.COMPTE) || (ecran == Ecran.AIDE && intervenant)) {
                    modele.aller(if (intervenant) Ecran.MISSIONS else Ecran.AIDE)
                }

                Scaffold(
                    snackbarHost = { SnackbarHost(bandeau) },
                    bottomBar = {
                        if (compte != null && modele.pret && ecran !in ECRANS_SANS_BARRE) BarreDuBas(ecran, intervenant, modele.nonVues, modele::aller)
                    },
                ) { marges ->
                    Box(Modifier.fillMaxSize().padding(marges)) {
                        when {
                            !modele.pret -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                            ecran == Ecran.CONNEXION -> EcranConnexion(modele)
                            ecran == Ecran.INSCRIPTION -> EcranInscription(modele)
                            ecran == Ecran.COMPTE -> EcranCompte(modele, compte!!, intervenant)
                            ecran == Ecran.EQUIPES -> EcranEquipes(modele)
                            ecran == Ecran.MESSAGERIE -> EcranMessagerie(modele)
                            ecran == Ecran.CARTE -> EcranCarte(modele)
                            ecran == Ecran.AIDE -> EcranAide(modele)
                            ecran == Ecran.DEPOT -> EcranDepot(modele, compte!!)
                            ecran == Ecran.NOTIFICATIONS -> EcranNotifications(modele)
                            ecran == Ecran.NOTIFICATION -> EcranNotification(modele)
                            ecran == Ecran.DISPONIBILITES -> EcranDisponibilites(modele)
                            ecran == Ecran.FICHE -> EcranFiche(modele)
                            ecran == Ecran.INTERVENTIONS -> EcranInterventions(modele)
                            ecran == Ecran.DOSSIER -> EcranDossier(modele)
                            else -> EcranMissions(modele, compte!!)
                        }
                    }
                }
            }
        }
    }
}

/** Les écrans qu'on ouvre depuis un autre : ils ont leur flèche de retour, pas la barre. */
private val ECRANS_SANS_BARRE = setOf(
    Ecran.MESSAGERIE, Ecran.DEPOT, Ecran.NOTIFICATIONS, Ecran.NOTIFICATION, Ecran.DISPONIBILITES, Ecran.FICHE, Ecran.INTERVENTIONS, Ecran.DOSSIER,
)
