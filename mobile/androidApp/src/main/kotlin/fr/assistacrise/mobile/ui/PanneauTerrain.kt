@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
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
import fr.assistacrise.mobile.domaine.Classement
import fr.assistacrise.mobile.domaine.EtiquetteTerrain
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.TypeMessageTerrain
import fr.assistacrise.mobile.donnees.DepotTerrain
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Les messages de terrain en un geste (22/11/2026) : de gros boutons, à portée de pouce, dans la
 * fiche du dossier (l'intervention), à l'intérieur de la mission. Un texte n'est demandé que là où il sert ; pour une demande de premiers
 * secours, le motif est demandé aussitôt.
 */
@Composable
fun PanneauTerrain(modele: ModeleApplication, dossier: Dossier) {
    var saisie by rememberSaveable { mutableStateOf<String?>(null) }
    var besoinOuvert by rememberSaveable { mutableStateOf(false) }
    val journal by modele.journalTerrain.collectAsStateWithLifecycle()

    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Column(Modifier.padding(12.dp)) {
            Text("Sur le terrain", style = MaterialTheme.typography.titleMedium)
            Text("Signalez où vous en êtes sur ce dossier, au poste de commandement.", style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(8.dp))
            // Le besoin relevé a sa propre fenêtre (famille, pour qui, animaux), plus bas.
            TypeMessageTerrain.entries.filter { it != TypeMessageTerrain.BESOIN }.chunked(2).forEach { ligne ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                    ligne.forEach { type ->
                        val geste = {
                            if (type.demandeTexte || type.demandeNombre) saisie = type.name
                            else modele.envoyerMessageTerrain(type, dossier)
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
            OutlinedButton(onClick = { besoinOuvert = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(vertical = 3.dp)) {
                Text("Signaler un besoin (évacuer, nourrir, abriter…)", textAlign = TextAlign.Center)
            }
            journal.take(3).forEach { e ->
                Text("${heure(e.emisLe)} · ${e.libelle} — ${etat(e)}", style = MaterialTheme.typography.bodySmall,
                    color = if (e.etat == DepotTerrain.REFUSE) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSecondaryContainer)
            }
        }
    }

    if (besoinOuvert) {
        DialogueBesoin(
            surEnvoi = { code, b, c, note -> modele.releverBesoin(dossier, code, b, c, note); besoinOuvert = false },
            surAbandon = { besoinOuvert = false },
        )
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
                    modele.envoyerMessageTerrain(type, dossier, texte, nombre.toIntOrNull())
                    saisie = null
                }) { Text("Envoyer") }
            },
            dismissButton = { TextButton(onClick = { saisie = null }) { Text("Annuler") } },
        )
    }
}

/**
 * Un besoin relevé sur place (27/11/2026) : la famille, pour qui, quels animaux, quelques mots.
 * Rien sur l'habitant : la radio n'emporte que l'essentiel, le PC en fait une demande.
 */
@Composable
private fun DialogueBesoin(surEnvoi: (code: String, beneficiaire: String?, categorie: String?, note: String) -> Unit, surAbandon: () -> Unit) {
    var code by rememberSaveable { mutableStateOf<String?>(null) }
    var pourQui by rememberSaveable { mutableStateOf<String?>(null) }
    var categorie by rememberSaveable { mutableStateOf<String?>(null) }
    var note by rememberSaveable { mutableStateOf("") }
    val admis = Classement.admis(code, offre = false)
    val pourQuiEffectif = pourQui?.takeIf { it in admis } ?: admis.singleOrNull()
    AlertDialog(
        onDismissRequest = surAbandon,
        title = { Text("Signaler un besoin") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text("De quoi s'agit-il ?", style = MaterialTheme.typography.labelLarge)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Classement.FAMILLES_RADIO.forEach { (c, libelle) ->
                        FilterChip(selected = code == c, onClick = { code = c; pourQui = null; categorie = null }, label = { Text(libelle) })
                    }
                }
                if (admis.size > 1) {
                    Spacer(Modifier.height(8.dp))
                    Text("Pour qui ?", style = MaterialTheme.typography.labelLarge)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        admis.forEach { b ->
                            FilterChip(selected = pourQuiEffectif == b, onClick = { pourQui = b; if (b != Classement.ANIMAUX) categorie = null },
                                label = { Text(Classement.LIBELLES[b] ?: b) })
                        }
                    }
                }
                if (pourQuiEffectif == Classement.ANIMAUX) {
                    Spacer(Modifier.height(8.dp))
                    Text("Quels animaux ?", style = MaterialTheme.typography.labelLarge)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Classement.CATEGORIES_ANIMAUX.forEach { (c, libelle) ->
                            FilterChip(selected = categorie == c, onClick = { categorie = if (categorie == c) null else c }, label = { Text(libelle) })
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(note, { note = it.take(Classement.NOTE_BESOIN_MAX) }, label = { Text("Quelques mots (facultatif)") },
                    supportingText = { Text("${note.length}/${Classement.NOTE_BESOIN_MAX} — rien sur l'habitant") }, singleLine = true)
            }
        },
        confirmButton = {
            TextButton(enabled = code != null && (admis.size < 2 || pourQuiEffectif != null), onClick = {
                surEnvoi(code!!, pourQuiEffectif, categorie, note)
            }) { Text("Envoyer") }
        },
        dismissButton = { TextButton(onClick = surAbandon) { Text("Annuler") } },
    )
}

private fun heure(millis: Long) = SimpleDateFormat("HH:mm", Locale.FRANCE).format(Date(millis))

private fun etat(e: DepotTerrain.Envoye) = when (e.etat) {
    DepotTerrain.RECU -> "reçu par le poste de commandement"
    DepotTerrain.RADIO -> "parti par radio ${e.protocole.orEmpty().split(",").joinToString(" et ") { if (it == "MESHCORE") "MeshCore" else "Meshtastic" }}, en attente du réseau"
    DepotTerrain.REFUSE -> "refusé : ${e.erreur ?: "voir la file"}"
    else -> "en attente d'envoi"
}
