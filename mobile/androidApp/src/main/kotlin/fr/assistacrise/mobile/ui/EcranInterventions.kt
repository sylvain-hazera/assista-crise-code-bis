package fr.assistacrise.mobile.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Dossier

/**
 * « Mes interventions » : les dossiers confiés à mes équipes, l'urgent d'abord. Tout le monde
 * les lit, hors réseau compris ; seuls le chef et le régulateur de l'équipe en changent le statut.
 */
@Composable
fun EcranInterventions(modele: ModeleApplication) {
    val dossiers by modele.dossiers.collectAsStateWithLifecycle()
    val equipes by modele.equipes.collectAsStateWithLifecycle()
    val compte by modele.compte.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize()) {
        EnTeteRetour("Mes interventions", modele) { modele.aller(Ecran.COMPTE) }
        when {
            modele.chargement && dossiers.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            dossiers.isEmpty() -> Text(
                when {
                    modele.horsLigne -> "Pas de réseau : les dossiers n'ont pas encore été chargés sur ce téléphone."
                    equipes.isEmpty() -> "Vous n'êtes membre d'aucune équipe pour l'instant."
                    else -> "Aucun dossier n'est confié à vos équipes."
                },
                modifier = Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            else -> LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
                if (modele.horsLigne) item {
                    Text("Pas de réseau : voici les dossiers tels qu'ils étaient à la dernière lecture.", style = MaterialTheme.typography.bodySmall, color = Attente, modifier = Modifier.padding(4.dp))
                }
                items(dossiers, key = { it.id }) { d ->
                    val jeDirige = equipes.firstOrNull { it.id == d.equipe }?.estDirigeePar(compte?.id) == true
                    CarteDossier(d, jeDirige, { modele.ouvrirDossier(d.id) }) { modele.definirStatutDossier(d, it) }
                }
                item { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}

@Composable
private fun CarteDossier(d: Dossier, jeDirige: Boolean, ouvrir: () -> Unit, surStatut: (String) -> Unit) {
    val contexte = LocalContext.current
    Card(onClick = ouvrir, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(d.titre.ifBlank { "Dossier ${d.numero}" }, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                if (d.priorite == "URGENTE" && !d.clos) Text("Urgent", style = MaterialTheme.typography.labelMedium, color = Refus)
            }
            Text(
                listOfNotNull(d.statutLibelle, d.equipeNom, d.commune, d.criseNom).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            (d.description.ifBlank { d.descriptionOrigine ?: "" }).takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, style = MaterialTheme.typography.bodyMedium)
            }
            d.contactNom?.takeIf { it.isNotBlank() }?.let { nom ->
                Spacer(Modifier.height(8.dp))
                Text("Sur place : $nom", style = MaterialTheme.typography.bodyMedium)
            }
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                d.contactTelephone?.takeIf { it.isNotBlank() }?.let { numero ->
                    // Ouvre le composeur, n'appelle pas : c'est la personne qui décroche le geste.
                    TextButton(onClick = { runCatching { contexte.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$numero"))) } }) { Text("Appeler") }
                }
                if (d.latitude != null && d.longitude != null) {
                    // `geo:` laisse le téléphone choisir son application de cartes, quelle qu'elle soit.
                    TextButton(onClick = {
                        runCatching { contexte.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("geo:${d.latitude},${d.longitude}?q=${d.latitude},${d.longitude}"))) }
                    }) { Text("Itinéraire") }
                }
                Spacer(Modifier.weight(1f))
                if (jeDirige && !d.clos) {
                    val suivant = if (d.statut == "EN_COURS") "AFFECTE" else "EN_COURS"
                    OutlinedButton(onClick = { surStatut(suivant) }) { Text(if (suivant == "EN_COURS") "Nous y sommes" else "Pas encore commencé") }
                    Spacer(Modifier.width(4.dp))
                }
            }
        }
    }
}
