package fr.assistacrise.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.LiaisonRadio
import fr.assistacrise.mobile.ModeleApplication

/**
 * La radio de l'intervenant : la connecter, voir ce qu'elle sait faire, la quitter.
 *
 * Elle ne se configure pas ici (dossier § 2) : l'application se sert d'une radio déjà
 * réglée, et dit seulement si le canal de chaque équipe s'y trouve.
 */
@Composable
fun SectionRadio(modele: ModeleApplication) {
    val contexte = LocalContext.current
    val etat by modele.radio.collectAsStateWithLifecycle()
    val trouvees by modele.radiosTrouvees.collectAsStateWithLifecycle()
    val equipes by modele.equipes.collectAsStateWithLifecycle()
    var choix by rememberSaveable { mutableStateOf(false) }
    val demande = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { accordees ->
        if (accordees.values.all { it }) { choix = true; modele.chercherDesRadios() }
    }
    if (equipes.isEmpty() && etat.phase == LiaisonRadio.Phase.ABSENTE) return   // un citoyen n'a pas de canal d'équipe

    Spacer(Modifier.height(24.dp))
    Text("Radio", style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(6.dp))
    when (etat.phase) {
        LiaisonRadio.Phase.PRETE -> {
            Text("${etat.nom ?: "Radio"} · ${etat.protocole?.libelle ?: ""}", style = MaterialTheme.typography.bodyLarge)
            Text(
                "Sans réseau, vos messages d'équipe partent par cette radio, sur le canal de l'équipe.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            equipes.forEach { equipe ->
                val canal = modele.canalRadioDe(equipe)
                Text(
                    if (canal != null) "${equipe.nom} : canal « ${canal.nom} » présent sur la radio"
                    else "${equipe.nom} : son canal n'est pas sur cette radio — sans réseau, ses messages attendront",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (canal != null) EnLigne else Attente,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            OutlinedButton(onClick = modele::deconnecterLaRadio, modifier = Modifier.padding(top = 8.dp)) { Text("Déconnecter la radio") }
        }
        LiaisonRadio.Phase.CONNEXION -> {
            Text("Connexion à ${etat.nom ?: "la radio"}…", style = MaterialTheme.typography.bodyMedium, color = Attente)
            Text("Si la radio affiche un code, saisissez-le quand le téléphone le demande.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = modele::deconnecterLaRadio) { Text("Annuler") }
        }
        else -> {
            Text(
                "Connectez votre radio MeshCore ou Meshtastic : sans réseau, vos messages d'équipe passeront par elle.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            etat.erreur?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Refus, modifier = Modifier.padding(top = 4.dp)) }
            Button(
                onClick = {
                    if (LiaisonRadio.autorise(contexte)) { choix = true; modele.chercherDesRadios() }
                    else demande.launch(LiaisonRadio.PERMISSIONS)
                },
                modifier = Modifier.padding(top = 8.dp),
            ) { Text("Connecter une radio") }
        }
    }

    if (choix) {
        AlertDialog(
            onDismissRequest = { choix = false; modele.arreterLaRecherche() },
            title = { Text("Radios à portée") },
            text = {
                Column {
                    if (trouvees.isEmpty()) {
                        Text("Recherche… Allumez votre radio et fermez l'application qui y serait déjà connectée : une radio ne parle qu'à un téléphone à la fois.")
                    }
                    trouvees.forEachIndexed { rang, radio ->
                        if (rang > 0) HorizontalDivider()
                        Column(Modifier.fillMaxWidth().clickable { choix = false; modele.connecterLaRadio(radio) }.padding(vertical = 10.dp)) {
                            Text(radio.nom, style = MaterialTheme.typography.bodyLarge)
                            Text(radio.protocole.libelle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { choix = false; modele.arreterLaRecherche() }) { Text("Fermer") } },
        )
    }
}
