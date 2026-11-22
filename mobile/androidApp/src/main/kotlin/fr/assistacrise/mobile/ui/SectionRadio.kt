package fr.assistacrise.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.LiaisonRadio
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.lien.CadrageFlux
import fr.assistacrise.mobile.lien.Protocole

/**
 * La radio de l'intervenant : la connecter, voir ce qu'elle sait faire, la quitter.
 *
 * L'écran simple dit seulement si le canal de chaque équipe s'y trouve. « Utilisateur radio
 * avancé » (22/11/2026) ouvre l'intégralité des menus : canaux, contacts, réglages, outils.
 */
@Composable
fun SectionRadio(modele: ModeleApplication) {
    val contexte = LocalContext.current
    val etat by modele.radio.collectAsStateWithLifecycle()
    val trouvees by modele.radiosTrouvees.collectAsStateWithLifecycle()
    val equipes by modele.equipes.collectAsStateWithLifecycle()
    var choix by rememberSaveable { mutableStateOf(false) }
    var parLeReseau by rememberSaveable { mutableStateOf(false) }
    val demande = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { accordees ->
        if (accordees.values.all { it }) { choix = true; modele.chercherDesRadios() }
    }
    if (equipes.isEmpty() && etat.phase == LiaisonRadio.Phase.ABSENTE) return   // un citoyen n'a pas de canal d'équipe

    Spacer(Modifier.height(24.dp))
    Text("Radio", style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(6.dp))
    when (etat.phase) {
        LiaisonRadio.Phase.PRETE -> {
            Text("${etat.nom ?: "Radio"} · ${etat.protocole?.libelle ?: ""}${if (etat.reseau) " · par le réseau" else ""}",
                 style = MaterialTheme.typography.bodyLarge)
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
            // « Utilisateur radio avancé » : l'intégralité des menus de la radio (22/11/2026).
            androidx.compose.foundation.layout.Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
                Text("Utilisateur radio avancé", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                androidx.compose.material3.Switch(checked = modele.modeRadioAvance, onCheckedChange = modele::basculerModeRadioAvance)
            }
            if (modele.modeRadioAvance) {
                Button(onClick = { modele.aller(fr.assistacrise.mobile.Ecran.RADIO_AVANCEE) }, modifier = Modifier.padding(top = 4.dp)) {
                    Text("Canaux, contacts, réglages de la radio")
                }
            }
            OutlinedButton(onClick = modele::deconnecterLaRadio, modifier = Modifier.padding(top = 8.dp)) { Text("Déconnecter la radio") }
        }
        LiaisonRadio.Phase.CONNEXION -> {
            Text("Connexion à ${etat.nom ?: "la radio"}…", style = MaterialTheme.typography.bodyMedium, color = Attente)
            Text(
                if (etat.reseau) "La radio et le téléphone doivent être sur le même Wi-Fi."
                else "Si la radio affiche un code, saisissez-le quand le téléphone le demande.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
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
            // Une radio reliée au Wi-Fi (Heltec V3, T-Deck…) : pas de Bluetooth ni d'autorisation.
            OutlinedButton(onClick = { parLeReseau = true }, modifier = Modifier.padding(top = 4.dp)) {
                Text("Connecter par le réseau (Wi-Fi)")
            }
        }
    }

    if (parLeReseau) DialogueRadioReseau(modele) { parLeReseau = false }

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

/**
 * Joindre une radio par son adresse sur le réseau local. Le lien TCP n'est pas chiffré, à la
 * différence du Bluetooth appairé : seule une adresse locale est acceptée, et on le dit.
 */
@Composable
private fun DialogueRadioReseau(modele: ModeleApplication, fermer: () -> Unit) {
    var protocole by rememberSaveable { mutableStateOf(Protocole.MESHCORE) }
    var adresse by rememberSaveable { mutableStateOf("") }
    var refus by rememberSaveable { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text("Radio sur le réseau") },
        text = {
            Column {
                Row {
                    Protocole.entries.forEach { p ->
                        FilterChip(
                            selected = protocole == p, onClick = { protocole = p; refus = null },
                            label = { Text(p.libelle) }, modifier = Modifier.padding(end = 8.dp),
                        )
                    }
                }
                OutlinedTextField(
                    value = adresse, onValueChange = { adresse = it; refus = null },
                    label = { Text("Adresse de la radio") },
                    placeholder = { Text("192.168.1.42") },
                    supportingText = { Text("Port ${CadrageFlux.pour(protocole).portParDefaut} par défaut ; « adresse:port » pour un autre.") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                refus?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Refus, modifier = Modifier.padding(top = 4.dp)) }
                Text(
                    "Le Wi-Fi de la radio doit être activé (MeshCore : firmware « companion » Wi-Fi ; " +
                        "Meshtastic : réglage Réseau > Wi-Fi). La liaison n'est pas chiffrée : à n'utiliser que sur " +
                        "un Wi-Fi de confiance, celui de la radio ou du poste de commandement. " +
                        "Une radio MeshCore ne parle qu'à un appareil à la fois.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        },
        confirmButton = {
            Button(onClick = {
                refus = modele.connecterLaRadioParLeReseau(protocole, adresse)
                if (refus == null) fermer()
            }) { Text("Connecter") }
        },
        dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } },
    )
}
