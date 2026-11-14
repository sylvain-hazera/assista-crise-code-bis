package fr.assistacrise.mobile

import android.os.Bundle
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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.assistacrise.mobile.ui.BarreDuBas
import fr.assistacrise.mobile.domaine.Mode
import fr.assistacrise.mobile.ui.EcranAide
import fr.assistacrise.mobile.ui.EcranCarte
import fr.assistacrise.mobile.ui.EcranDepot
import fr.assistacrise.mobile.ui.EcranCompte
import fr.assistacrise.mobile.ui.EcranEquipes
import fr.assistacrise.mobile.ui.EcranMessagerie
import fr.assistacrise.mobile.ui.EcranConnexion
import fr.assistacrise.mobile.ui.EcranInscription
import fr.assistacrise.mobile.ui.EcranMissions
import fr.assistacrise.mobile.ui.ThemeApplication

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ThemeApplication {
                val modele: ModeleApplication = viewModel(factory = ModeleApplication.Fabrique)
                val compte by modele.compte.collectAsStateWithLifecycle()
                val bandeau = remember { SnackbarHostState() }

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
                    !intervenant && modele.ecran !in setOf(Ecran.AIDE, Ecran.DEPOT, Ecran.COMPTE) -> Ecran.AIDE
                    modele.ecran == Ecran.CONNEXION || modele.ecran == Ecran.INSCRIPTION -> Ecran.MISSIONS
                    else -> modele.ecran
                }
                BackHandler(enabled = ecran == Ecran.INSCRIPTION) { modele.aller(Ecran.CONNEXION) }
                BackHandler(enabled = ecran == Ecran.MESSAGERIE) { modele.aller(Ecran.EQUIPES) }
                BackHandler(enabled = ecran == Ecran.DEPOT) { modele.aller(Ecran.AIDE) }
                BackHandler(enabled = ecran in setOf(Ecran.EQUIPES, Ecran.CARTE, Ecran.COMPTE) || (ecran == Ecran.AIDE && intervenant)) {
                    modele.aller(if (intervenant) Ecran.MISSIONS else Ecran.AIDE)
                }

                Scaffold(
                    snackbarHost = { SnackbarHost(bandeau) },
                    bottomBar = { if (compte != null && modele.pret && ecran != Ecran.MESSAGERIE && ecran != Ecran.DEPOT) BarreDuBas(ecran, intervenant, modele::aller) },
                ) { marges ->
                    Box(Modifier.fillMaxSize().padding(marges)) {
                        when {
                            !modele.pret -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                            ecran == Ecran.CONNEXION -> EcranConnexion(modele)
                            ecran == Ecran.INSCRIPTION -> EcranInscription(modele)
                            ecran == Ecran.COMPTE -> EcranCompte(modele, compte!!)
                            ecran == Ecran.EQUIPES -> EcranEquipes(modele)
                            ecran == Ecran.MESSAGERIE -> EcranMessagerie(modele)
                            ecran == Ecran.CARTE -> EcranCarte(modele)
                            ecran == Ecran.AIDE -> EcranAide(modele)
                            ecran == Ecran.DEPOT -> EcranDepot(modele, compte!!)
                            else -> EcranMissions(modele, compte!!)
                        }
                    }
                }
            }
        }
    }
}
