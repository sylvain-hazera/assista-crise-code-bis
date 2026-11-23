package fr.assistacrise.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.donnees.BasculeServeur

private val Ambre = Color(0xFFB45309)

/** Sur le satellite (le central ne répond pas) : un bandeau qui le dit, et le retour au central. */
@Composable
fun BandeauSatellite(modele: ModeleApplication) {
    val etat by modele.etatServeur.collectAsStateWithLifecycle()
    val satellite by modele.satelliteActif.collectAsStateWithLifecycle()
    if (etat != BasculeServeur.Etat.SATELLITE) return
    Row(
        Modifier.fillMaxWidth().background(Ambre)
            .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
            .padding(horizontal = 12.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("Satellite « ${satellite?.nom ?: "du site"} » — central injoignable", color = Color.White,
             fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge, modifier = Modifier.weight(1f))
        TextButton(onClick = modele::revenirAuCentral) { Text("Central", color = Color.White) }
    }
}

/** Recherche en cours, ou rien trouvé : l'adresse IP du satellite est demandée. */
@Composable
fun DialogueSatellite(modele: ModeleApplication) {
    val etat by modele.etatServeur.collectAsStateWithLifecycle()
    when (etat) {
        BasculeServeur.Etat.RECHERCHE -> AlertDialog(
            onDismissRequest = {},
            title = { Text("Le central ne répond pas") },
            text = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.padding(end = 12.dp))
                    Text("Recherche du satellite sur le Wi-Fi du site…")
                }
            },
            confirmButton = {},
        )
        BasculeServeur.Etat.ADRESSE_DEMANDEE -> AlertDialog(
            onDismissRequest = modele::continuerSansReseau,
            title = { Text("Aucun satellite trouvé") },
            text = {
                Column {
                    Text("Le central ne répond pas, et aucun satellite ne s'est annoncé sur ce réseau. " +
                         "Connectez le téléphone au Wi-Fi du site, ou saisissez l'adresse IP du satellite " +
                         "(affichée sur son écran).", style = MaterialTheme.typography.bodyMedium)
                    OutlinedTextField(
                        value = modele.adresseSatellite, onValueChange = modele::saisirAdresseSatellite,
                        label = { Text("Adresse IP du satellite") }, placeholder = { Text("192.168.1.20") },
                        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                    modele.refusAdresseSatellite?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    TextButton(onClick = modele::chercherLeSatellite) { Text("Chercher à nouveau") }
                }
            },
            confirmButton = {
                Button(onClick = modele::essayerAdresseSatellite, enabled = modele.adresseSatellite.isNotBlank() && !modele.essaiSatelliteEnCours) {
                    Text(if (modele.essaiSatelliteEnCours) "Essai…" else "Se connecter")
                }
            },
            dismissButton = { TextButton(onClick = modele::continuerSansReseau) { Text("Continuer sans réseau") } },
        )
        else -> Unit
    }
}
