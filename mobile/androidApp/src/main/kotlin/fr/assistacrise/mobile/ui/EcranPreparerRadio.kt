package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication

private val LIBELLES = mapOf("crise" to "Canal de la crise", "equipe" to "Canal de l'équipe", "commune" to "Canal de la commune")

/**
 * Préparer la radio (25/11/2026) : les canaux d'urgence en 5 (crise), 6 (équipe), 7 (commune).
 * L'intervenant voit ce que chaque emplacement contient, peut en choisir un autre, valide ;
 * ce qui est remplacé est sauvegardé sur le téléphone et sera remis en fin de crise.
 */
@Composable
fun EcranPreparerRadio(modele: ModeleApplication) {
    val plan = modele.planUrgence
    val total = modele.totalEmplacements()
    // Le nom de ce qu'il y a dans chaque emplacement (25/11/2026, demande de Sylvain) : on choisit
    // un canal à remplacer, pas un numéro.
    val noms = modele.tableRadio().filter { it.actif }.associate { it.index to it.nom }
    fun libelle(i: Int) = "$i · " + (noms[i]?.ifBlank { null }?.let { "« $it »" } ?: "libre")
    var montrerQr by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (modele.preparationDedie) "Préparer un nœud de l'équipe" else "Préparer la radio",
                 style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            TextButton(onClick = { modele.aller(Ecran.COMPTE) }) { Text("Fermer") }
        }
        Text(
            if (modele.preparationDedie) "Nœud dédié : les canaux d'urgence sont écrits sans sauvegarde, puis le nœud est enregistré auprès de l'équipe."
            else "Les emplacements d'urgence reçoivent les canaux de la crise, de l'équipe et de la commune. Ce qu'ils contiennent est sauvegardé sur ce téléphone et sera remis en fin de crise.",
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (plan == null) {
            Text(if (modele.preparationEnCours) "Lecture des canaux de l'équipe et de la radio…" else "Canaux d'urgence indisponibles.")
            return@Column
        }
        Text("Équipe ${plan.nomEquipe} · @${plan.indicatif}" + (plan.nomCrise?.let { " · crise « $it »" } ?: " · hors crise"),
             style = MaterialTheme.typography.titleSmall)
        modele.propositions.forEach { p ->
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text("${LIBELLES[p.entree.role] ?: p.entree.role} : ${p.entree.nom}", style = MaterialTheme.typography.titleSmall)
                    if (p.dejaPresent != null) {
                        Text("Déjà sur la radio (emplacement ${p.dejaPresent}) : utilisé tel quel.", color = EnLigne, style = MaterialTheme.typography.bodySmall)
                    } else {
                        var ouvert by remember { mutableStateOf(false) }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("Emplacement ${p.emplacement?.let(::libelle)}", modifier = Modifier.weight(1f))
                            TextButton(onClick = { ouvert = true }) { Text("Changer") }
                            DropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
                                val prisParAutres = modele.propositions.filter { it !== p }.mapNotNull { it.emplacement ?: it.dejaPresent }.toSet()
                                (1 until total).forEach { i ->
                                    DropdownMenuItem(
                                        text = { Text(libelle(i) + if (i in prisParAutres) " (déjà choisi)" else "") },
                                        enabled = i !in prisParAutres,
                                        onClick = { ouvert = false; modele.choisirEmplacement(p.entree.role, i) })
                                }
                            }
                        }
                        Text(p.remplace?.let { "Actuellement « ${it.nom} » : sera remplacé" + (if (modele.preparationDedie) "." else " (sauvegardé).") }
                             ?: "Emplacement libre.", style = MaterialTheme.typography.bodySmall,
                             color = if (p.remplace != null) Attente else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        if (modele.propositions.isEmpty()) Text("Aucun canal d'urgence pour cette radio.", style = MaterialTheme.typography.bodySmall)
        modele.erreurPreparation()?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(enabled = !modele.preparationEnCours && modele.erreurPreparation() == null && modele.propositions.any { it.emplacement != null },
               onClick = modele::validerPreparation, modifier = Modifier.fillMaxWidth()) {
            Text(if (modele.preparationEnCours) "Écriture…" else if (modele.preparationDedie) "Écrire sur le nœud" else "Sauvegarder puis écrire")
        }
        modele.lienCanauxUrgence()?.let { lien ->
            OutlinedButton(onClick = { montrerQr = !montrerQr }, modifier = Modifier.fillMaxWidth()) {
                Text(if (montrerQr) "Masquer le QR code" else "QR code pour un boîtier sans notre application")
            }
            if (montrerQr) {
                Text("À scanner avec l'application Meshtastic officielle : elle ajoute ces canaux sans effacer les autres. Il contient la clé de l'équipe : ne le montrez qu'aux membres.",
                     style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                CodeQr(lien)
            }
        }
    }
}
