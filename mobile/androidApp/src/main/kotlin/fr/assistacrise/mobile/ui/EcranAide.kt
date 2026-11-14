package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.EtatAction
import fr.assistacrise.mobile.domaine.GenreDepot
import fr.assistacrise.mobile.domaine.Information

/** Le mode citoyen : les crises en cours, ce qui s'y dit, et les trois gestes. */
@Composable
fun EcranAide(modele: ModeleApplication) {
    val crises by modele.crises.collectAsStateWithLifecycle()
    val informations by modele.informations.collectAsStateWithLifecycle()
    val file by modele.file.collectAsStateWithLifecycle()
    val lien by modele.lien.collectAsStateWithLifecycle()
    val enAttente = file.count { it.etat == EtatAction.EN_ATTENTE }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Crises en cours", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            PastilleLien(lien)
        }
        if (enAttente > 0) {
            Text(
                if (enAttente == 1) "1 envoi en attente du réseau" else "$enAttente envois en attente du réseau",
                style = MaterialTheme.typography.labelLarge, color = Attente,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
            )
        }
        if (crises.isEmpty()) {
            Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Aucune crise en cours", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Text(
                    "Quand une crise sera ouverte, vous pourrez ici vous déclarer en sécurité, demander de l'aide ou signaler un danger.\n\nEn cas d'urgence vitale, appelez le 112.",
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center,
                )
            }
        } else {
            LazyColumn(
                Modifier.fillMaxSize().padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                contentPadding = PaddingValues(vertical = 12.dp),
            ) {
                items(crises, key = { it.id }) { crise ->
                    CarteCrise(crise, informations.filter { it.crise == crise.id }) { genre -> modele.ouvrirDepot(genre, crise) }
                }
                item {
                    Text(
                        "En cas d'urgence vitale, appelez le 112.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 4.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun CarteCrise(crise: Crise, informations: List<Information>, deposer: (GenreDepot) -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(crise.typeLibelle.uppercase(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.secondary)
            Text(crise.nom, style = MaterialTheme.typography.titleLarge)
            crise.description?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 4)
            }
            Spacer(Modifier.height(12.dp))
            if (crise.accepteLesDepots) {
                Button(onClick = { deposer(GenreDepot.SECURITE) }, modifier = Modifier.fillMaxWidth()) { Text("Je suis en sécurité") }
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { deposer(GenreDepot.DEMANDE) }, modifier = Modifier.weight(1f)) { Text("Demander de l'aide") }
                    OutlinedButton(onClick = { deposer(GenreDepot.SIGNALEMENT) }, modifier = Modifier.weight(1f)) { Text("Signaler") }
                }
            } else {
                Text(
                    "Les dépôts ne sont pas encore ouverts pour cette crise : aucun responsable n'a été désigné.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (informations.isNotEmpty()) {
                Spacer(Modifier.height(14.dp))
                Text("Informations publiées", style = MaterialTheme.typography.titleSmall)
                informations.take(6).forEach { info ->
                    Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                        Text("•  ${info.titre}", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        instantDe(info.creeLe)?.let {
                            Text(ilYA(it), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}
