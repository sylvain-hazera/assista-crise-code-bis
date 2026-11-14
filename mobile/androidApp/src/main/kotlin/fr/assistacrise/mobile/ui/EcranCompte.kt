package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.BuildConfig
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.ActionEnAttente
import fr.assistacrise.mobile.domaine.Compte
import fr.assistacrise.mobile.domaine.EtatAction
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun EcranCompte(modele: ModeleApplication, compte: Compte) {
    val file by modele.file.collectAsStateWithLifecycle()
    val lien by modele.lien.collectAsStateWithLifecycle()
    var confirmer by rememberSaveable { mutableStateOf(false) }
    val enAttente = file.count { it.etat == EtatAction.EN_ATTENTE }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(start = 4.dp, end = 16.dp, top = 4.dp)) {
            IconButton(onClick = { modele.aller(Ecran.MISSIONS) }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour aux missions")
            }
            Text("Mon compte", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            PastilleLien(lien)
        }

        Column(Modifier.padding(horizontal = 20.dp)) {
            Spacer(Modifier.height(8.dp))
            Text(compte.nomComplet, style = MaterialTheme.typography.headlineSmall)
            Text(compte.email, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                compte.institutionNom ?: if (compte.reserveAVerifier) "Candidature en cours d'examen" else "Aucun rattachement",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(24.dp))
            Text("En attente d'envoi", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            if (file.isEmpty()) {
                Text("Rien n'attend : tout ce que vous avez déclaré est arrivé au serveur.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
                    file.forEachIndexed { rang, action ->
                        if (rang > 0) HorizontalDivider()
                        LigneAction(action) { modele.ecarter(action.id) }
                    }
                }
                if (enAttente > 0) {
                    TextButton(onClick = modele::actualiser, enabled = !modele.synchronisation) { Text("Réessayer maintenant") }
                }
            }

            Spacer(Modifier.height(28.dp))
            OutlinedButton(onClick = { confirmer = true }, modifier = Modifier.fillMaxWidth().height(50.dp)) { Text("Se déconnecter") }
            Spacer(Modifier.height(16.dp))
            Text(
                "Version ${BuildConfig.VERSION_NAME} · ${BuildConfig.URL_SITE.removePrefix("https://")}",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    if (confirmer) {
        AlertDialog(
            onDismissRequest = { confirmer = false },
            title = { Text("Se déconnecter ?") },
            text = {
                // On ne laisse pas partir quelqu'un sans lui dire ce qu'il abandonne.
                Text(
                    if (enAttente == 0) "Les missions gardées sur ce téléphone seront effacées."
                    else if (enAttente == 1) "1 changement n'a pas encore été envoyé : il sera perdu."
                    else "$enAttente changements n'ont pas encore été envoyés : ils seront perdus.",
                )
            },
            confirmButton = { TextButton(onClick = { confirmer = false; modele.deconnecter() }) { Text("Se déconnecter") } },
            dismissButton = { TextButton(onClick = { confirmer = false }) { Text("Annuler") } },
        )
    }
}

@Composable
private fun LigneAction(action: ActionEnAttente, surEcart: () -> Unit) {
    val refusee = action.etat == EtatAction.REFUSEE
    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp, top = 10.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(action.libelle, style = MaterialTheme.typography.bodyLarge)
            Text(
                if (refusee) "Refusé : ${action.erreur ?: "sans motif"}"
                else "Déclaré à ${heure(action.creeLe)}" + if (action.tentatives > 0) " · ${action.tentatives} essai(s)" else "",
                style = MaterialTheme.typography.bodySmall,
                color = if (refusee) Refus else Attente,
            )
        }
        TextButton(onClick = surEcart) { Text(if (refusee) "Écarter" else "Annuler") }
    }
}

private fun heure(instant: Long): String = SimpleDateFormat("HH:mm", Locale.FRANCE).format(Date(instant))
