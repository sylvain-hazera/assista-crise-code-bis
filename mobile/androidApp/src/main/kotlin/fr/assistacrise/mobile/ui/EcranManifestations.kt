package fr.assistacrise.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.ManifestationAsso
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val JOUR = DateTimeFormatter.ofPattern("EEEE d MMMM", Locale.FRANCE)
private val HEURE = DateTimeFormatter.ofPattern("HH'h'mm", Locale.FRANCE)

private fun local(iso: String) = runCatching { OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()) }.getOrNull()
private fun jour(iso: String) = local(iso)?.format(JOUR)?.replaceFirstChar { it.uppercase() } ?: iso
private fun heure(iso: String) = local(iso)?.format(HEURE) ?: ""
private fun passe(iso: String) = local(iso)?.isBefore(java.time.ZonedDateTime.now()) == true

/**
 * Les manifestations de mes associations (26/11/2026) : courses à baliser, dispositifs de
 * signalisation radio, exercices. Je déplie, je m'inscris sur un poste ; complet, je passe en
 * liste d'attente et je suis prévenu si une place se libère. L'organisation (créer, pointer)
 * se fait sur le site.
 */
@Composable
fun EcranManifestations(modele: ModeleApplication) {
    val aVenir = modele.manifestations.filter { !passe(it.fin) }
    val defilement = rememberLazyListState()
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { modele.aller(Ecran.COMPTE) }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            Text("Manifestations", style = MaterialTheme.typography.titleLarge)
        }
        modele.message?.let {
            Text(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), color = MaterialTheme.colorScheme.primary)
        }
        if (modele.horsLigne) {
            Text("Pas de réseau : la liste n'a pas pu être chargée.", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.error)
        }
        LazyColumn(
            Modifier.fillMaxSize().ascenseur(defilement, MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)),
            state = defilement, contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (aVenir.isEmpty() && !modele.chargement) {
                item {
                    Text("Aucune manifestation prévue. Celles de vos associations s'affichent ici dès que leur bureau les publie.",
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            items(aVenir, key = { it.id }) { m ->
                CarteManifestation(m, modele.manifestationOuverte?.takeIf { it.id == m.id }, modele)
            }
        }
    }
}

@Composable
private fun CarteManifestation(m: ManifestationAsso, detail: ManifestationAsso?, modele: ModeleApplication) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = Modifier.fillMaxWidth().clickable { modele.deplierManifestation(m.id) },
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(jour(m.debut), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            Text(m.titre, style = MaterialTheme.typography.titleMedium)
            Text(listOf("${heure(m.debut)} – ${heure(m.fin)}", m.type, m.lieu).filter { it.isNotBlank() }.joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(m.association, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.weight(1f))
                if (m.statut == "ANNULEE") Text("Annulée", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelMedium)
                else Text((if (m.inscrit) "Inscrit · " else "") + "${m.occupes}/${m.places}", style = MaterialTheme.typography.labelMedium)
            }
            if (detail != null) {
                if (detail.organisateur.isNotBlank()) Text("Pour : ${detail.organisateur}", style = MaterialTheme.typography.bodySmall)
                if (detail.consignes.isNotBlank()) {
                    Spacer(Modifier.padding(top = 6.dp))
                    Text("Consignes", style = MaterialTheme.typography.labelLarge)
                    Text(detail.consignes, style = MaterialTheme.typography.bodyMedium)
                }
                Spacer(Modifier.padding(top = 6.dp))
                detail.postes.forEach { p ->
                    HorizontalDivider(Modifier.padding(vertical = 6.dp))
                    Text(p.intitule, style = MaterialTheme.typography.bodyLarge)
                    Text("${heure(p.debut)} – ${heure(p.fin)} · ${p.etat()}", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (p.remarque.isNotBlank()) Text(p.remarque, style = MaterialTheme.typography.bodySmall)
                    Row {
                        when {
                            p.engage && !passe(p.debut) -> OutlinedButton(onClick = { modele.inscriptionPoste(p, false) }) { Text("Me désister") }
                            p.monStatut == null || p.monStatut == "DESISTE" -> if (detail.statut == "PUBLIEE" && !passe(p.fin)) {
                                Button(onClick = { modele.inscriptionPoste(p, true) }) { Text(if (p.complet) "Liste d'attente" else "M'inscrire") }
                            }
                        }
                        Spacer(Modifier.width(8.dp))
                    }
                }
            }
        }
    }
}
