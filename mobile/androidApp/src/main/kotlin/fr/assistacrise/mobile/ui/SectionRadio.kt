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
    val etats by modele.radios.collectAsStateWithLifecycle()
    val trouvees by modele.radiosTrouvees.collectAsStateWithLifecycle()
    val erreurRecherche by modele.erreurRechercheRadio.collectAsStateWithLifecycle()
    val equipes by modele.equipes.collectAsStateWithLifecycle()
    var choix by rememberSaveable { mutableStateOf(false) }
    var parLeReseau by rememberSaveable { mutableStateOf(false) }
    val demande = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { accordees ->
        if (accordees.values.all { it }) { choix = true; modele.chercherDesRadios() }
    }
    val actives = etats.filter { it.phase != LiaisonRadio.Phase.ABSENTE || it.erreur != null }
    if (equipes.isEmpty() && etats.all { it.phase == LiaisonRadio.Phase.ABSENTE }) return   // un citoyen n'a pas de canal d'équipe

    Spacer(Modifier.height(24.dp))
    Text("Radio", style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(6.dp))
    // Une radio par protocole, les deux à la fois si l'intervenant les a (23/11/2026).
    Protocole.entries.forEach { protocole ->
        val etat = etats.firstOrNull { it.protocole == protocole } ?: etats[if (protocole == Protocole.MESHCORE) 1 else 0]
        BlocRadio(modele, protocole, etat, equipes)
    }
    if (etats.any { it.phase == LiaisonRadio.Phase.PRETE }) {
        if (etats.count { it.phase == LiaisonRadio.Phase.PRETE } > 1) Text(
            "Deux radios : sans réseau, chaque message d'équipe part sur les deux, pour que les deux réseaux l'entendent.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp),
        )
        // Emplacements d'urgence 5-6-7 (25/11/2026) : préparer la radio, la remettre comme avant.
        etats.filter { it.phase == LiaisonRadio.Phase.PRETE }.mapNotNull { it.protocole }.forEach { p ->
            PreparerEtRestaurer(modele, p)
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
    }
    // Un emplacement libre : on peut connecter une (autre) radio.
    if (etats.any { it.phase == LiaisonRadio.Phase.ABSENTE }) {
        if (actives.isEmpty()) Text(
            "Connectez votre radio MeshCore ou Meshtastic (ou une de chaque) : sans réseau, vos messages d'équipe passeront par elle.",
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        erreurRecherche?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Refus, modifier = Modifier.padding(top = 4.dp)) }
        Row(Modifier.padding(top = 8.dp)) {
            Button(onClick = {
                if (LiaisonRadio.autorise(contexte)) { choix = true; modele.chercherDesRadios() }
                else demande.launch(LiaisonRadio.PERMISSIONS)
            }) { Text(if (etats.any { it.phase == LiaisonRadio.Phase.PRETE }) "Connecter une seconde radio" else "Connecter une radio") }
        }
        // Une radio reliée au Wi-Fi (Heltec V3, T-Deck…) : pas de Bluetooth ni d'autorisation.
        OutlinedButton(onClick = { parLeReseau = true }, modifier = Modifier.padding(top = 4.dp)) {
            Text("Connecter par le réseau (Wi-Fi)")
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
                            val occupe = etats.firstOrNull { it.protocole == radio.protocole && it.phase != LiaisonRadio.Phase.ABSENTE }
                            Text(radio.protocole.libelle + (occupe?.let { " · remplacera ${it.nom ?: "la radio " + radio.protocole.libelle}" } ?: ""),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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

/** L'état d'une des deux radios (Meshtastic ou MeshCore), et ce qu'on peut en faire. */
@Composable
private fun BlocRadio(modele: ModeleApplication, protocole: Protocole, etat: LiaisonRadio.Etat, equipes: List<fr.assistacrise.mobile.domaine.Equipe>) {
    when (etat.phase) {
        LiaisonRadio.Phase.PRETE -> Column(Modifier.padding(bottom = 8.dp)) {
            Text("${etat.nom ?: "Radio"} · ${protocole.libelle}${if (etat.reseau) " · par le réseau" else ""}",
                 style = MaterialTheme.typography.bodyLarge)
            Text(
                "Sans réseau, vos messages d'équipe partent par cette radio, sur le canal de l'équipe.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            // Un seul canal par crise (23/11/2026) : l'équipe y est adressée par son indicatif.
            equipes.mapNotNull { it.canalCrise }.distinctBy { it.crise }.forEach { cc ->
                val nom = cc.nomPour(protocole == Protocole.MESHCORE) ?: return@forEach
                val present = modele.canalDeCriseSurLaRadio(cc, protocole) != null
                Text(
                    if (present) "Canal de la crise « $nom » présent sur la radio"
                    else "Canal de la crise « $nom » absent de cette radio : sans réseau, les messages de la crise n'y passeront pas.",
                    style = MaterialTheme.typography.bodySmall, color = if (present) EnLigne else Attente,
                    modifier = Modifier.padding(top = 4.dp),
                )
                if (!present) {
                    Button(enabled = !modele.alignementEnCours, onClick = { modele.alignerRadio(protocole, cc.crise) },
                           modifier = Modifier.padding(top = 4.dp)) {
                        Text(if (modele.alignementEnCours) "Alignement…" else "Aligner la radio sur la crise")
                    }
                    Text("Ajoute Fr_Balise, Fr_EMCOM et le canal de la crise dans des emplacements libres, sans toucher aux autres. Canal lisible par tous : rien de personnel.",
                         style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            equipes.forEach { equipe ->
                val canal = modele.canalRadioDe(equipe, protocole)
                val indicatif = equipe.canalCrise?.indicatif
                Text(
                    when {
                        canal != null && indicatif != null && canal.nom.equals(equipe.canalCrise?.nomPour(protocole == Protocole.MESHCORE), ignoreCase = true) ->
                            "${equipe.nom} : par le canal de la crise, adressée « @$indicatif »"
                        canal != null -> "${equipe.nom} : canal « ${canal.nom} » présent sur la radio"
                        else -> "${equipe.nom} : aucun canal sur cette radio — sans réseau, ses messages n'y passeront pas"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (canal != null) EnLigne else Attente,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            OutlinedButton(onClick = { modele.deconnecterLaRadio(protocole) }, modifier = Modifier.padding(top = 8.dp)) {
                Text("Déconnecter la radio ${protocole.libelle}")
            }
        }
        LiaisonRadio.Phase.CONNEXION -> Column(Modifier.padding(bottom = 8.dp)) {
            Text("Connexion à ${etat.nom ?: "la radio " + protocole.libelle}…", style = MaterialTheme.typography.bodyMedium, color = Attente)
            Text(
                if (etat.reseau) "La radio et le téléphone doivent être sur le même Wi-Fi."
                else "Si la radio affiche un code, saisissez-le quand le téléphone le demande.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            TextButton(onClick = { modele.deconnecterLaRadio(protocole) }) { Text("Annuler") }
        }
        else -> etat.erreur?.let {
            Text("${protocole.libelle} : $it", style = MaterialTheme.typography.bodySmall, color = Refus, modifier = Modifier.padding(bottom = 4.dp))
        }
    }
}

/** Préparer la radio pour l'urgence, ou la remettre comme avant (25/11/2026). */
@androidx.compose.runtime.Composable
private fun PreparerEtRestaurer(modele: fr.assistacrise.mobile.ModeleApplication, protocole: Protocole) {
    var sauvegarde by androidx.compose.runtime.remember(protocole) { androidx.compose.runtime.mutableStateOf<fr.assistacrise.mobile.domaine.SauvegardeRadio?>(null) }
    var garderEquipe by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(true) }
    var confirmer by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
    androidx.compose.runtime.LaunchedEffect(protocole, modele.preparationEnCours) { sauvegarde = modele.derniereSauvegarde(protocole) }
    Column(Modifier.padding(top = 8.dp)) {
        Button(onClick = { modele.ouvrirPreparation(protocole) }, modifier = Modifier.fillMaxWidth()) {
            Text("Préparer la radio ${protocole.libelle} pour l'urgence")
        }
        Text("Canaux de la crise, de l'équipe et de la commune en 5, 6 et 7 (modifiables) ; ce qu'ils remplacent est sauvegardé.",
             style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        val s = sauvegarde
        if (s != null) {
            val crisePassee = s.crise != null && modele.equipes.value.none { it.canalCrise?.crise == s.crise }
            if (crisePassee) Text("La crise est close : vous pouvez remettre la radio comme avant.", color = Attente,
                                  style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
            OutlinedButton(onClick = { confirmer = true }, modifier = Modifier.fillMaxWidth().padding(top = 4.dp)) {
                Text("Remettre la radio comme avant")
            }
        }
        OutlinedButton(onClick = { modele.ouvrirPreparation(protocole, dedie = true) }, modifier = Modifier.fillMaxWidth().padding(top = 4.dp)) {
            Text("Préparer un nœud dédié de l'équipe")
        }
    }
    val s = sauvegarde
    if (confirmer && s != null) androidx.compose.material3.AlertDialog(
        onDismissRequest = { confirmer = false },
        title = { Text("Remettre la radio comme avant ?") },
        text = {
            Column {
                Text("Sauvegarde du ${java.text.DateFormat.getDateTimeInstance().format(java.util.Date(s.date))}. Emplacements remis : " +
                     s.ecrits.filter { !(garderEquipe && s.roles[it.index] == "equipe") }.joinToString { "${it.index} (${it.nom})" } + ".")
                androidx.compose.foundation.layout.Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    androidx.compose.material3.Checkbox(checked = garderEquipe, onCheckedChange = { garderEquipe = it })
                    Text("Garder le canal de l'équipe (il sert hors crise)")
                }
                Text("Un emplacement modifié à la main depuis est laissé tel quel.", style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { androidx.compose.material3.TextButton(onClick = { confirmer = false; modele.restaurerRadio(protocole, garderEquipe) }) { Text("Remettre") } },
        dismissButton = { androidx.compose.material3.TextButton(onClick = { confirmer = false }) { Text("Annuler") } },
    )
}
