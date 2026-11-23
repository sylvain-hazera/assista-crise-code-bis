package fr.assistacrise.mobile.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.compose.ui.platform.LocalContext
import androidx.compose.runtime.remember
import fr.assistacrise.mobile.ServiceTerrain
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Equipe
import fr.assistacrise.mobile.domaine.EtatSuivi
import fr.assistacrise.mobile.domaine.ReglesSuivi

@Composable
fun EcranEquipes(modele: ModeleApplication) {
    val equipes by modele.equipes.collectAsStateWithLifecycle()
    val suivi by modele.suivi.collectAsStateWithLifecycle()
    val lien by modele.lien.collectAsStateWithLifecycle()
    val nonLus by modele.nonLusEquipes.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Mes équipes", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            PastilleLien(lien)
        }
        // La radio du nœud : canaux, contacts, messages directs.
        if (equipes.isEmpty()) {
            Column(Modifier.padding(16.dp)) { PanneauRadio(modele) }
        }
        if (equipes.isEmpty()) {
            Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Aucune équipe pour l'instant", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Text(
                    "Quand vous serez affecté à une équipe, sa messagerie apparaîtra ici.",
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center,
                )
            }
        } else {
            LazyColumn(
                Modifier.fillMaxSize().padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                contentPadding = PaddingValues(vertical = 12.dp),
            ) {
                item { CarteSuivi(modele, suivi, equipes) }
                // La messagerie des équipes d'abord, la radio du nœud ensuite (23/11/2026) ;
                // chaque niveau dit ce qui n'est pas lu : le moyen, puis l'équipe ou le canal.
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Chat", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        PastilleNonLus(nonLus.values.sumOf { it.messages }, nonLus.values.sumOf { it.mentions })
                    }
                }
                items(equipes, key = { it.id }) { equipe ->
                    CarteEquipe(equipe, nonLus[equipe.id] ?: ModeleApplication.NonLus(), { modele.quitterEquipe(equipe) }) { modele.ouvrirMessagerie(equipe) }
                }
                item { PanneauRadio(modele) }
            }
        }
    }
}

@Composable
private fun CarteEquipe(equipe: Equipe, nonLus: ModeleApplication.NonLus, surQuitter: () -> Unit, surClic: () -> Unit) {
    var confirmer by rememberSaveable { mutableStateOf(false) }
    if (confirmer) androidx.compose.material3.AlertDialog(
        onDismissRequest = { confirmer = false },
        title = { Text("Quitter « ${equipe.nom} » ?") },
        text = { Text("Vous ne recevrez plus ses messages, ses missions ni ses dossiers. L'équipe, ses missions et ses dossiers restent : rien n'est supprimé. Un responsable pourra vous y remettre.") },
        confirmButton = { androidx.compose.material3.TextButton(onClick = { confirmer = false; surQuitter() }) { Text("Quitter l'équipe") } },
        dismissButton = { androidx.compose.material3.TextButton(onClick = { confirmer = false }) { Text("Annuler") } },
    )
    Card(
        onClick = surClic,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(equipe.nom, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                PastilleNonLus(nonLus.messages, nonLus.mentions)
                if (nonLus.messages > 0) Spacer(Modifier.width(8.dp))
                if (equipe.engagee) {
                    Surface(color = EnLigne.copy(alpha = 0.14f), shape = RoundedCornerShape(50)) {
                        Text("Engagée", style = MaterialTheme.typography.labelMedium, color = EnLigne, modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp))
                    }
                }
            }
            equipe.institutionNom?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            equipe.missionTitre?.let { Text("Mission : $it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Ouvrir la messagerie", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary, modifier = Modifier.weight(1f))
                androidx.compose.material3.TextButton(onClick = { confirmer = true }) { Text("Quitter") }
            }
        }
    }
}

/**
 * Le suivi en mission : ce qu'il fait, s'il est actif, et comment l'arrêter. Toujours en
 * tête de l'écran — on ne cache pas à quelqu'un que sa position est partagée.
 */
@Composable
private fun CarteSuivi(modele: ModeleApplication, suivi: EtatSuivi, equipes: List<Equipe>) {
    var expliquer by rememberSaveable { mutableStateOf(false) }
    val demande = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { accordees ->
        val position = accordees[Manifest.permission.ACCESS_FINE_LOCATION] == true || accordees[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        if (position) modele.consentirAuSuivi(true)
    }
    val engagement = ReglesSuivi.engagementCourant(equipes)

    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("Suivi en mission", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
            Spacer(Modifier.height(4.dp))
            val texte = when {
                suivi.actif -> "Votre position est partagée avec votre équipe depuis ${duree(suivi.depuis ?: 0)}. Le suivi s'arrêtera seul à la fin de l'engagement."
                !suivi.consentement -> "Désactivé. Votre position n'est partagée que si vous l'acceptez, et seulement pendant qu'une de vos équipes est engagée."
                engagement != null && engagement == suivi.engagementArrete -> "Vous avez arrêté le suivi pour cet engagement."
                else -> "Accepté. Le suivi démarrera quand une de vos équipes sera engagée, et s'arrêtera seul à la fin."
            }
            Text(texte, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
            Spacer(Modifier.height(10.dp))
            if (suivi.consentement) ReglagesArrierePlan()
            Row {
                when {
                    suivi.actif -> Button(onClick = modele::arreterLeSuivi) { Text("Arrêter le suivi") }
                    !suivi.consentement -> Button(onClick = { expliquer = true }) { Text("Accepter le suivi") }
                    engagement != null && engagement == suivi.engagementArrete -> {
                        Button(onClick = modele::reprendreLeSuivi) { Text("Reprendre") }
                        Spacer(Modifier.width(8.dp))
                        OutlinedButton(onClick = { modele.consentirAuSuivi(false) }) { Text("Ne plus accepter") }
                    }
                    else -> OutlinedButton(onClick = { modele.consentirAuSuivi(false) }) { Text("Ne plus accepter") }
                }
            }
        }
    }

    if (expliquer) {
        AlertDialog(
            onDismissRequest = { expliquer = false },
            title = { Text("Partager ma position en mission") },
            text = {
                Text(
                    "Si vous acceptez, votre position sera envoyée à votre équipe et à sa cellule de crise pendant qu'une de vos équipes est engagée sur le terrain.\n\n" +
                        "• Le suivi ne démarre que lorsqu'un responsable engage l'équipe.\n" +
                        "• Il s'arrête seul à la fin de l'engagement, et au plus tard après douze heures.\n" +
                        "• Une notification reste affichée tant qu'il est actif.\n" +
                        "• Vous pouvez l'arrêter à tout moment.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    expliquer = false
                    val permissions = buildList {
                        add(Manifest.permission.ACCESS_FINE_LOCATION)
                        add(Manifest.permission.ACCESS_COARSE_LOCATION)
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) add(Manifest.permission.POST_NOTIFICATIONS)
                    }
                    demande.launch(permissions.toTypedArray())
                }) { Text("J'accepte") }
            },
            dismissButton = { TextButton(onClick = { expliquer = false }) { Text("Pas maintenant") } },
        )
    }
}


/**
 * Ce qu'il faut accorder pour que le suivi démarre application fermée quand l'équipe est
 * engagée (22/11/2026) : la position « Toujours » et l'exemption d'économie d'énergie. Chaque
 * point manquant est dit, avec son bouton ; rien n'est demandé en silence.
 */
@Composable
private fun ReglagesArrierePlan() {
    val contexte = LocalContext.current
    var verifier by remember { mutableStateOf(0) }
    val arrierePlan = remember(verifier) { ServiceTerrain.positionEnArrierePlan(contexte) }
    val energie = remember(verifier) {
        contexte.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(contexte.packageName) == true
    }
    val demandeArrierePlan = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { verifier++ }
    if (arrierePlan && energie) return
    Spacer(Modifier.height(8.dp))
    Text(
        "Pour que votre position soit partagée même application fermée, dès que votre équipe est engagée :",
        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onPrimaryContainer,
    )
    if (!arrierePlan && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        TextButton(onClick = { demandeArrierePlan.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION) }) {
            Text("Autoriser la position « Toujours » (en mission seulement)")
        }
    }
    if (!energie) {
        TextButton(onClick = {
            runCatching {
                contexte.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${contexte.packageName}")))
            }
            verifier++
        }) { Text("Ne pas mettre l'application en sommeil") }
    }
}
