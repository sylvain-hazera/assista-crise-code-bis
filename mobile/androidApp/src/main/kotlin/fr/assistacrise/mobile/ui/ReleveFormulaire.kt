package fr.assistacrise.mobile.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.content.Context
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.BrouillonSortie
import fr.assistacrise.mobile.domaine.MonReleve
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

private val AFFICHAGE = DateTimeFormatter.ofPattern("EEE d MMM yyyy, HH:mm", Locale.FRENCH)
private val ACTIVITE = DateTimeFormatter.ofPattern("d/MM HH:mm", Locale.FRENCH)

private fun versLocal(iso: String?): ZonedDateTime? =
    iso?.takeIf { it.isNotBlank() }?.let { runCatching { OffsetDateTime.parse(it).atZoneSameInstant(ZoneId.systemDefault()) }.getOrNull() }

/** Choisit une date puis une heure avec les sélecteurs du téléphone ; rend un ISO 8601 avec le
 * décalage du téléphone : le serveur n'a pas à deviner le fuseau. */
private fun choisirInstant(contexte: Context, initial: String, surChoix: (String) -> Unit) {
    val z = versLocal(initial) ?: ZonedDateTime.now().withSecond(0).withNano(0)
    DatePickerDialog(contexte, { _, annee, mois, jour ->
        TimePickerDialog(contexte, { _, heure, minute ->
            surChoix(ZonedDateTime.of(annee, mois + 1, jour, heure, minute, 0, 0, ZoneId.systemDefault())
                .toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME))
        }, z.hour, z.minute, true).show()
    }, z.year, z.monthValue - 1, z.dayOfMonth).show()
}

/**
 * Ajouter une sortie oubliée, ou corriger une sortie (28/11/2026) : comme le formulaire du site,
 * avec en bas l'activité de la période — « le dossier a été pris en charge à 14 h 10 » — pour
 * retrouver ses heures. Une correction ne change ni l'activité ni l'équipe.
 */
@Composable
fun FormulaireSortie(modele: ModeleApplication, r: MonReleve, initial: BrouillonSortie, fermer: () -> Unit) {
    val contexte = LocalContext.current
    var b by remember { mutableStateOf(initial) }
    var envoi by remember { mutableStateOf(false) }
    val correction = initial.id != null
    val cibles = r.crises.map { "c:${it.id}" to it.nom } + r.manifestations.map { "m:${it.id}" to it.nom }
    val lieux = r.lieux.map { it.code to it.libelle.substringBefore(" (") }.ifEmpty { listOf("DOMICILE" to "Domicile", "HEBERGEMENT" to "Hébergement") }

    Dialog(onDismissRequest = { if (!envoi) fermer() }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (correction) "Corriger la sortie" else "Ajouter une sortie oubliée", style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier.weight(1f))
                    TextButton(onClick = fermer, enabled = !envoi) { Text("Annuler") }
                }
                if (!correction) {
                    ListeDeroulante("Crise ou manifestation", listOf("" to "— choisir —") + cibles, b.cible) { b = b.copy(cible = it) }
                    if (b.cible.startsWith("c:") && r.equipes.isNotEmpty()) {
                        ListeDeroulante("Équipe", listOf("" to "— sans équipe —") + r.equipes.map { it.id to it.nom }, b.equipe) { b = b.copy(equipe = it) }
                    }
                } else {
                    Text(cibles.firstOrNull { it.first == b.cible }?.second ?: "", style = MaterialTheme.typography.titleSmall)
                }

                Text("Heures", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 4.dp))
                OutlinedButton(onClick = { choisirInstant(contexte, b.partiLe) { b = b.copy(partiLe = it) } }, modifier = Modifier.fillMaxWidth()) {
                    Text("Départ : " + (versLocal(b.partiLe)?.format(AFFICHAGE) ?: "à choisir"))
                }
                ListeDeroulante("Départ de", lieux, b.departDe) { b = b.copy(departDe = it) }
                OutlinedButton(onClick = { choisirInstant(contexte, b.rentreLe.ifBlank { b.partiLe }) { b = b.copy(rentreLe = it) } }, modifier = Modifier.fillMaxWidth()) {
                    Text("Retour : " + (versLocal(b.rentreLe)?.format(AFFICHAGE) ?: "à choisir"))
                }
                ListeDeroulante("Retour à", lieux, b.retourA) { b = b.copy(retourA = it) }

                Text("Déplacement (facultatif)", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 4.dp))
                ListeDeroulante("Véhicule", listOf("" to "— aucun de mes véhicules —") + r.mesVehicules.map { it.id to it.designation }, b.vehiculePersonnel) {
                    b = b.copy(vehiculePersonnel = it)
                }
                if (b.vehiculePersonnel.isBlank()) {
                    ListeDeroulante("Type de véhicule", listOf("AUCUN" to "Sans véhicule personnel", "VOITURE" to "Voiture", "DEUX_ROUES" to "Moto, scooter"),
                        b.typeVehicule) { b = b.copy(typeVehicule = it) }
                }
                Champ(b.lieuDepart, { b = b.copy(lieuDepart = it.take(200)) }, "Lieu de départ", Modifier.fillMaxWidth())
                Champ(b.lieuArrivee, { b = b.copy(lieuArrivee = it.take(200)) }, "Lieu d'arrivée", Modifier.fillMaxWidth())
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = b.allerRetour, onCheckedChange = { b = b.copy(allerRetour = it) }); Text("Aller-retour")
                }
                Champ(b.motif, { b = b.copy(motif = it.take(300)) }, "Motif", Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Champ(b.compteurDepart, { b = b.copy(compteurDepart = it.filter(Char::isDigit).take(9)) }, "Compteur départ",
                        Modifier.weight(1f), clavier = KeyboardOptions(keyboardType = KeyboardType.Number))
                    Champ(b.compteurArrivee, { b = b.copy(compteurArrivee = it.filter(Char::isDigit).take(9)) }, "Compteur arrivée",
                        Modifier.weight(1f), clavier = KeyboardOptions(keyboardType = KeyboardType.Number))
                }
                val parCompteurs = b.kmDesCompteurs
                Champ(parCompteurs?.toString() ?: b.kilometres, { b = b.copy(kilometres = it.filter { c -> c.isDigit() || c == ',' || c == '.' }.take(7)) },
                    "Kilomètres aller-retour", Modifier.fillMaxWidth(), actif = parCompteurs == null,
                    aide = if (parCompteurs != null) "Calculés d'après les compteurs" else null,
                    clavier = KeyboardOptions(keyboardType = KeyboardType.Decimal))

                modele.releveErreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                Button(enabled = !envoi, onClick = {
                    envoi = true
                    modele.enregistrerSortie(b, if (correction) initial else null) { reussi -> envoi = false; if (reussi) fermer() }
                }, modifier = Modifier.fillMaxWidth()) { Text(if (correction) "Enregistrer la correction" else "Ajouter la sortie") }
                Text("Une ligne complétée ou corrigée à la main est marquée comme telle pour votre encadrement.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)

                val reperes = r.activite.filter { it.heure }
                if (reperes.isNotEmpty()) {
                    HorizontalDivider(Modifier.padding(vertical = 6.dp))
                    Text("Retrouver ses heures", style = MaterialTheme.typography.titleSmall)
                    Text("Touchez une ligne : elle remplit le départ, puis le retour.", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    reperes.take(80).forEach { a ->
                        val quand = versLocal(a.quand)
                        Row(Modifier.fillMaxWidth().clickable {
                            val iso = quand?.toOffsetDateTime()?.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME) ?: return@clickable
                            b = if (b.partiLe.isBlank()) b.copy(partiLe = iso) else b.copy(rentreLe = iso)
                        }.padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(quand?.format(ACTIVITE) ?: "", style = MaterialTheme.typography.bodySmall)
                            Text(a.quoi + if (a.equipe.isNotBlank()) " — ${a.equipe}" else "", style = MaterialTheme.typography.bodySmall,
                                color = if (a.source == "moi") MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}

/** Une liste déroulante : le libellé au-dessus, la valeur choisie sur le bouton. */
@Composable
fun ListeDeroulante(libelle: String, options: List<Pair<String, String>>, valeur: String, surChoix: (String) -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth()) {
        Text(libelle, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Box {
            OutlinedButton(onClick = { ouvert = true }, modifier = Modifier.fillMaxWidth()) {
                Text(options.firstOrNull { it.first == valeur }?.second ?: options.firstOrNull()?.second.orEmpty())
            }
            DropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
                options.forEach { (code, nom) -> DropdownMenuItem(text = { Text(nom) }, onClick = { surChoix(code); ouvert = false }) }
            }
        }
    }
}
