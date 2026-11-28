package fr.assistacrise.mobile.ui

import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.BuildConfig
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.Photographe
import fr.assistacrise.mobile.domaine.EtatEngagement
import fr.assistacrise.mobile.domaine.ReleveKm
import fr.assistacrise.mobile.domaine.Retour
import kotlinx.coroutines.launch
import java.io.File

/**
 * « Je pars », « je rentre » en tête de « Mes missions » (28/11/2026), comme le bloc du site :
 * deux gestes, l'heure du serveur, et le déplacement — facultatif — pour le relevé kilométrique.
 * La carte ne s'affiche que s'il y a quelque chose à déclarer.
 */
@Composable
fun CarteDepartRetour(modele: ModeleApplication) {
    LaunchedEffect(Unit) { modele.lireEngagement() }
    val etat = modele.engagement ?: return
    if (etat.vide) return
    var retourOuvert by rememberSaveable { mutableStateOf(false) }

    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            val e = etat.enCours
            if (e != null) {
                Text("Parti sur ${e.nom}" + (e.equipe?.let { " avec $it" } ?: ""), style = MaterialTheme.typography.titleSmall)
                instantDe(e.partiLe)?.let {
                    Text("Depuis ${duree(it)}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Button(onClick = { modele.preparerRetour(); retourOuvert = true }, enabled = !modele.engagementEnvoi,
                    modifier = Modifier.fillMaxWidth()) { Text("Je rentre") }
            } else {
                FormulaireDepart(modele, etat)
            }
            modele.engagementErreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            modele.engagementMessage?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
    if (retourOuvert && etat.enCours != null) FeuilleRetour(modele, etat) { retourOuvert = false }
}

@Composable
private fun FormulaireDepart(modele: ModeleApplication, etat: EtatEngagement) {
    val cibles = etat.crises.map { "c:${it.id}" to it.nom } + etat.manifestations.map { "m:${it.id}" to it.nom }
    var cible by rememberSaveable(cibles) { mutableStateOf(cibles.firstOrNull()?.first ?: "") }
    var equipe by rememberSaveable { mutableStateOf(etat.equipes.singleOrNull()?.id ?: "") }
    val hebergement = etat.crises.firstOrNull { "c:${it.id}" == cible }?.hebergement.orEmpty()
    var depart by rememberSaveable(cible) { mutableStateOf(if (hebergement.isNotBlank()) "HEBERGEMENT" else "DOMICILE") }
    var vehicule by rememberSaveable { mutableStateOf(etat.vehicules.singleOrNull()?.id ?: "") }
    var compteur by rememberSaveable { mutableStateOf("") }

    Text("Déclarez votre départ : c'est ce qui compte votre temps et vos kilomètres.", style = MaterialTheme.typography.bodyMedium)
    if (cibles.size > 1) Choix("Pour", cibles, cible) { cible = it }
    if (etat.equipes.size > 1 && cible.startsWith("c:")) {
        Choix("Avec", listOf("" to "— sans équipe —") + etat.equipes.map { it.id to it.nom }, equipe) { equipe = it }
    }
    Choix("Je pars", listOf("DOMICILE" to "de mon domicile",
        "HEBERGEMENT" to ("de mon hébergement sur site" + if (hebergement.isNotBlank()) " ($hebergement)" else "")), depart) { depart = it }
    if (etat.vehicules.isNotEmpty()) {
        Choix("Véhicule", listOf("" to "— sans mon véhicule —") + etat.vehicules.map { it.id to it.designation }, vehicule) { vehicule = it }
        if (vehicule.isNotBlank()) {
            Champ(compteur, { compteur = it.filter(Char::isDigit).take(9) }, "Compteur au départ (facultatif)",
                Modifier.fillMaxWidth(), clavier = KeyboardOptions(keyboardType = KeyboardType.Number))
        }
    }
    Button(onClick = { modele.partir(cible, equipe.ifBlank { null }, depart, vehicule.ifBlank { null }, compteur) },
        enabled = cible.isNotBlank() && !modele.engagementEnvoi, modifier = Modifier.fillMaxWidth()) { Text("Je pars") }
}

/** La feuille du retour : tout est facultatif, sauf le geste. */
@Composable
private fun FeuilleRetour(modele: ModeleApplication, etat: EtatEngagement, fermer: () -> Unit) {
    val e = etat.enCours ?: return
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    var retourA by rememberSaveable { mutableStateOf(e.departDe) }
    var km by rememberSaveable { mutableStateOf("") }
    var compteur by rememberSaveable { mutableStateOf("") }
    var arrivee by rememberSaveable { mutableStateOf(e.arriveePropose) }
    var motif by rememberSaveable { mutableStateOf(e.motifPropose) }
    var allerRetour by rememberSaveable { mutableStateOf(true) }
    var peage by rememberSaveable { mutableStateOf("") }
    var stationnement by rememberSaveable { mutableStateOf("") }
    var photoPeage by remember { mutableStateOf<ByteArray?>(null) }
    var photoStationnement by remember { mutableStateOf<ByteArray?>(null) }
    // Pour quel ticket l'appareil photo est ouvert, et où il écrit.
    var pourQuoi by remember { mutableStateOf("") }
    var prise by remember { mutableStateOf<File?>(null) }
    val appareil = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { reussie ->
        val fichier = prise
        prise = null
        if (reussie && fichier != null) portee.launch {
            // Réduite, sans position : c'est un justificatif, pas un constat.
            Photographe.preparer(fichier, null, "", BuildConfig.VERSION_NAME)?.first?.let {
                if (pourQuoi == "PEAGE") photoPeage = it else photoStationnement = it
            }
        } else fichier?.delete()
    }
    val parCompteurs = ReleveKm.kmCompteurs(e.compteurDepart, compteur)

    AlertDialog(
        onDismissRequest = { if (!modele.engagementEnvoi) fermer() },
        title = { Text("Je rentre") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Choix("Je rentre", listOf("DOMICILE" to "à mon domicile", "HEBERGEMENT" to "à mon hébergement sur site"), retourA) { retourA = it }
                Text("Mon déplacement (facultatif)", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 6.dp))
                if (e.compteurDepart.isNotBlank()) {
                    Champ(compteur, { compteur = it.filter(Char::isDigit).take(9) }, "Compteur à l'arrivée",
                        Modifier.fillMaxWidth(), clavier = KeyboardOptions(keyboardType = KeyboardType.Number),
                        aide = parCompteurs?.let { "Soit $it km (départ : ${e.compteurDepart})" } ?: "Au départ : ${e.compteurDepart}")
                }
                if (parCompteurs == null) {
                    Champ(km, { km = it.filter { c -> c.isDigit() || c == ',' || c == '.' }.take(7) }, "Kilomètres aller-retour",
                        Modifier.fillMaxWidth(), clavier = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        aide = modele.distanceEstimee?.let { "≈ $it km d'après le GPS du téléphone" })
                    modele.distanceEstimee?.let { d ->
                        if (km.isBlank()) TextButton(onClick = { km = d.toString() }) { Text("Reprendre ≈ $d km") }
                    }
                }
                Champ(arrivee, { arrivee = it.take(200) }, "Arrivée", Modifier.fillMaxWidth())
                Champ(motif, { motif = it.take(300) }, "Motif", Modifier.fillMaxWidth())
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = allerRetour, onCheckedChange = { allerRetour = it })
                    Text("Aller-retour")
                }
                for ((nature, libelle) in listOf("PEAGE" to "Péage (€)", "STATIONNEMENT" to "Stationnement (€)")) {
                    val valeur = if (nature == "PEAGE") peage else stationnement
                    val photo = if (nature == "PEAGE") photoPeage else photoStationnement
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Champ(valeur, { v -> val t = v.filter { c -> c.isDigit() || c == ',' || c == '.' }.take(7)
                            if (nature == "PEAGE") peage = t else stationnement = t },
                            libelle, Modifier.weight(1f), clavier = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                        if (photo != null) {
                            val vignette = remember(photo) { BitmapFactory.decodeByteArray(photo, 0, photo.size)?.asImageBitmap() }
                            Box { vignette?.let { Image(it, contentDescription = "Ticket photographié", modifier = Modifier.size(44.dp)) } }
                        }
                        OutlinedButton(onClick = {
                            val (fichier, adresse) = Photographe.nouvellePrise(contexte)
                            prise = fichier; pourQuoi = nature
                            appareil.launch(adresse)
                        }, enabled = valeur.isNotBlank()) { Text(if (photo == null) "Ticket" else "Refaire") }
                    }
                }
                Text("Tout se complète ensuite dans Mon relevé, sur le site.", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                modele.engagementErreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = {
            Button(enabled = !modele.engagementEnvoi, onClick = {
                val retour = Retour(kilometres = if (parCompteurs != null) "" else km, compteurArrivee = compteur,
                    // Les valeurs proposées sont celles que le serveur pose de lui-même : on n'envoie que
                    // ce que la personne a changé.
                    lieuArrivee = arrivee.takeIf { it != e.arriveePropose }.orEmpty(),
                    motif = motif.takeIf { it != e.motifPropose }.orEmpty(), allerRetour = allerRetour,
                    peage = peage, stationnement = stationnement)
                modele.rentrer(retourA, retour, photoPeage?.takeIf { peage.isNotBlank() },
                    photoStationnement?.takeIf { stationnement.isNotBlank() }, fermer)
            }) { Text("Je rentre") }
        },
        dismissButton = { TextButton(onClick = fermer, enabled = !modele.engagementEnvoi) { Text("Annuler") } },
    )
}

/** Une liste déroulante : le libellé au-dessus, la valeur choisie sur le bouton. */
@Composable
private fun Choix(libelle: String, options: List<Pair<String, String>>, valeur: String, surChoix: (String) -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
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
