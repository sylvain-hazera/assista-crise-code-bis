package fr.assistacrise.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.donnees.Session

private val Orange = Color(0xFFF97316)

/**
 * Le bandeau permanent de la formation (22/11/2026), en haut de tous les écrans : en pleine
 * crise, personne ne doit croire travailler sur des données réelles quand ce n'est pas le cas.
 */
@Composable
fun BandeauFormation(modele: ModeleApplication) {
    val zone by modele.zone.collectAsStateWithLifecycle()
    if (zone != Session.DEMO) return
    Text(
        "FORMATION — données fictives · la radio, elle, est réelle",
        color = Color.White, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
        style = MaterialTheme.typography.labelLarge,
        modifier = Modifier.fillMaxWidth().background(Orange).padding(vertical = 6.dp, horizontal = 8.dp),
    )
}

/**
 * La bascule « Formation », comme celle du site : proposée aux seuls comptes à qui un
 * administrateur a ouvert la démonstration, et confirmée — un doigt qui glisse en pleine crise
 * ne doit pas faire travailler sur des données fictives.
 */
@Composable
fun SectionFormation(modele: ModeleApplication) {
    val compte by modele.compte.collectAsStateWithLifecycle()
    val zone by modele.zone.collectAsStateWithLifecycle()
    if (compte?.peutSeFormer != true) return
    var confirmer by rememberSaveable { mutableStateOf<Boolean?>(null) }
    val enFormation = zone == Session.DEMO
    Spacer(Modifier.height(24.dp))
    Text("Formation", style = MaterialTheme.typography.titleMedium)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(if (enFormation) "Vous êtes en formation : données fictives de démonstration." else "Vous travaillez sur les données réelles.",
                style = MaterialTheme.typography.bodyMedium)
            Text("Missions, équipes, suivi, messages de terrain et radio fonctionnent comme en vrai, sur les équipes et canaux de démonstration.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked = enFormation, onCheckedChange = { confirmer = it })
    }
    confirmer?.let { oui ->
        AlertDialog(
            onDismissRequest = { confirmer = null },
            title = { Text(if (oui) "Passer en formation ?" else "Revenir aux données réelles ?") },
            text = {
                Text(if (oui) "Vous travaillerez sur des données fictives. Les messages radio partent quand même sur de vraies radios, sur les canaux de démonstration, préfixés « [démo] »."
                     else "Vous retrouverez vos missions et équipes réelles.")
            },
            confirmButton = { TextButton(onClick = { modele.basculerFormation(oui); confirmer = null }) { Text("Confirmer") } },
            dismissButton = { TextButton(onClick = { confirmer = null }) { Text("Annuler") } },
        )
    }
}
