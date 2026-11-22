package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.EtiquetteTerrain
import fr.assistacrise.mobile.domaine.Mission
import fr.assistacrise.mobile.domaine.StatutMission
import fr.assistacrise.mobile.domaine.TypeMessageTerrain
import fr.assistacrise.mobile.donnees.DepotTerrain
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Les messages de terrain en un geste (22/11/2026) : de gros boutons, à portée de pouce, pour
 * la mission en cours. Un texte n'est demandé que là où il sert ; pour une demande de premiers
 * secours, le motif est demandé aussitôt.
 */
@Composable
fun PanneauTerrain(modele: ModeleApplication, missions: List<Mission>) {
    val enCours = missions.filter { it.statut == StatutMission.EN_COURS }
    if (enCours.isEmpty()) return
    var choisie by rememberSaveable { mutableStateOf(enCours.first().id) }
    val mission = enCours.firstOrNull { it.id == choisie } ?: enCours.first()
    var saisie by rememberSaveable { mutableStateOf<String?>(null) }
    val journal by modele.journalTerrain.collectAsStateWithLifecycle()

    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        Column(Modifier.padding(12.dp)) {
            Text("Sur le terrain", style = MaterialTheme.typography.titleMedium)
            if (enCours.size > 1) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    enCours.take(3).forEach { m ->
                        FilterChip(selected = m.id == mission.id, onClick = { choisie = m.id }, label = { Text(m.titre, maxLines = 1) })
                    }
                }
            } else {
                Text(mission.titre, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(8.dp))
            TypeMessageTerrain.entries.chunked(2).forEach { ligne ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                    ligne.forEach { type ->
                        val geste = {
                            if (type.demandeTexte || type.demandeNombre) saisie = type.name
                            else modele.envoyerMessageTerrain(type, mission)
                        }
                        if (type.prioritaire) {
                            Button(onClick = geste, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                                modifier = Modifier.weight(1f).heightIn(min = 56.dp)) { Text(type.libelle, textAlign = TextAlign.Center) }
                        } else {
                            OutlinedButton(onClick = geste, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) {
                                Text(type.libelle, textAlign = TextAlign.Center)
                            }
                        }
                    }
                }
            }
            journal.take(3).forEach { e ->
                Text("${heure(e.emisLe)} · ${e.libelle} — ${etat(e)}", style = MaterialTheme.typography.bodySmall,
                    color = if (e.etat == DepotTerrain.REFUSE) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSecondaryContainer)
            }
        }
    }

    saisie?.let { nom ->
        val type = TypeMessageTerrain.valueOf(nom)
        var texte by rememberSaveable(nom) { mutableStateOf("") }
        var nombre by rememberSaveable(nom) { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { saisie = null },
            title = { Text(type.libelle) },
            text = {
                Column {
                    if (type.demandeNombre) {
                        OutlinedTextField(nombre, { nombre = it.filter(Char::isDigit).take(3) }, label = { Text("Combien de personnes ? (facultatif)") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true)
                        Spacer(Modifier.height(8.dp))
                    }
                    if (type.demandeTexte) {
                        OutlinedTextField(texte, { texte = it }, label = { Text(type.questionTexte) }, minLines = 2)
                        if (EtiquetteTerrain.estTronque(type, texte, nombre.toIntOrNull())) {
                            Text("Sans réseau, seul le début partira par radio ; le texte entier suivra par les données.",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(enabled = !type.texteObligatoire || texte.isNotBlank(), onClick = {
                    modele.envoyerMessageTerrain(type, mission, texte, nombre.toIntOrNull())
                    saisie = null
                }) { Text("Envoyer") }
            },
            dismissButton = { TextButton(onClick = { saisie = null }) { Text("Annuler") } },
        )
    }
}

private fun heure(millis: Long) = SimpleDateFormat("HH:mm", Locale.FRANCE).format(Date(millis))

private fun etat(e: DepotTerrain.Envoye) = when (e.etat) {
    DepotTerrain.RECU -> "reçu par le poste de commandement"
    DepotTerrain.RADIO -> "parti par radio ${if (e.protocole == "MESHCORE") "MeshCore" else "Meshtastic"}, en attente du réseau"
    DepotTerrain.REFUSE -> "refusé : ${e.erreur ?: "voir la file"}"
    else -> "en attente d'envoi"
}
