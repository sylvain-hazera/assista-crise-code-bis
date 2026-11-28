package fr.assistacrise.mobile.ui

import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.PeriodeReleve
import fr.assistacrise.mobile.Photographe
import fr.assistacrise.mobile.donnees.Reponse
import fr.assistacrise.mobile.domaine.EtatLigne
import fr.assistacrise.mobile.domaine.FraisLigne
import fr.assistacrise.mobile.domaine.LigneReleve
import kotlinx.coroutines.launch
import java.io.File
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val JOUR_HEURE = DateTimeFormatter.ofPattern("EEE d MMM, HH:mm", Locale.FRENCH)
private val HEURE = DateTimeFormatter.ofPattern("HH:mm", Locale.FRENCH)
private fun local(iso: String?) = iso?.let { runCatching { OffsetDateTime.parse(it).atZoneSameInstant(ZoneId.systemDefault()) }.getOrNull() }
private fun nombre(x: Double) = if (x == kotlin.math.floor(x)) x.toLong().toString() else String.format(Locale.FRENCH, "%.1f", x)

/**
 * « Mon relevé » dans l'application (28/11/2026) : mes sorties de la période — heures,
 * kilomètres, trajet, frais, validées ou non —, l'ajout d'un justificatif (péage,
 * stationnement, ou autre : photo du tableau de bord…) et le relevé kilométrique en PDF.
 * Corriger une heure ou ajouter un oubli se fait sur le site, où l'activité de l'équipe aide à
 * retrouver les heures.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EcranReleve(modele: ModeleApplication) {
    val r = modele.releve
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    var ajoutPour by remember { mutableStateOf<LigneReleve?>(null) }
    var apercu by remember { mutableStateOf<ByteArray?>(null) }
    val defilement = rememberLazyListState()

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { modele.aller(Ecran.COMPTE) }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            Text("Mon relevé", style = MaterialTheme.typography.titleLarge)
        }
        FlowRow(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PeriodeReleve.entries.forEach { p ->
                FilterChip(selected = modele.periodeReleve == p, onClick = { modele.choisirPeriodeReleve(p) }, label = { Text(p.libelle) })
            }
        }
        modele.releveErreur?.let { Text(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), color = MaterialTheme.colorScheme.error) }
        modele.releveMessage?.let { Text(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), color = MaterialTheme.colorScheme.primary) }

        LazyColumn(
            Modifier.fillMaxSize().ascenseur(defilement, MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)),
            state = defilement, contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (r != null) {
                item {
                    Text("${nombre(r.totalHeures)} h · ${nombre(r.totalKilometres)} km sur la période",
                        style = MaterialTheme.typography.titleMedium)
                }
                items(r.lignes, key = { it.id }) { l ->
                    CarteLigne(l, surAjout = { ajoutPour = l }, surJustificatif = { f ->
                        portee.launch {
                            when (val o = modele.octetsJustificatif(f.id)) {
                                is Reponse.Ok -> if (BitmapFactory.decodeByteArray(o.valeur, 0, o.valeur.size) != null) apercu = o.valeur
                                                 else ouvrirFichier(contexte, o.valeur, f.nomJustificatif.ifBlank { "justificatif.pdf" })
                                else -> Unit
                            }
                        }
                    })
                }
                if (r.lignes.isEmpty() && !modele.releveEnCours) {
                    item { Text("Aucune sortie sur cette période.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
                if (r.frais.isNotEmpty()) {
                    item {
                        Text("Relevé kilométrique à signer (PDF)", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp))
                    }
                    items(r.frais, key = { "pdf-${it.institution}" }) { a ->
                        OutlinedButton(onClick = {
                            portee.launch {
                                when (val pdf = modele.releveKmPdf(a.institution)) {
                                    is Reponse.Ok -> ouvrirFichier(contexte, pdf.valeur, "releve-km-${r.du}-${r.au}.pdf")
                                    else -> Unit
                                }
                            }
                        }, modifier = Modifier.fillMaxWidth()) { Text(a.nom) }
                    }
                }
                item {
                    Text("Corriger une heure ou ajouter une sortie oubliée : page Mon relevé, sur le site.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else if (modele.releveEnCours) {
                item { Text("Lecture du relevé…", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
        }
    }

    ajoutPour?.let { l -> DialogueJustificatif(modele, l) { ajoutPour = null } }
    apercu?.let { octets ->
        val image = remember(octets) { BitmapFactory.decodeByteArray(octets, 0, octets.size)?.asImageBitmap() }
        AlertDialog(onDismissRequest = { apercu = null }, confirmButton = { TextButton(onClick = { apercu = null }) { Text("Fermer") } },
            text = { image?.let { Image(it, contentDescription = "Justificatif", modifier = Modifier.fillMaxWidth().heightIn(max = 480.dp)) } })
    }
}

@Composable
private fun CarteLigne(l: LigneReleve, surAjout: () -> Unit, surJustificatif: (FraisLigne) -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(l.activite, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                Text(l.etat.libelle, style = MaterialTheme.typography.labelMedium, color = when (l.etat) {
                    EtatLigne.VALIDEE -> EnLigne; EtatLigne.A_REVOIR -> MaterialTheme.colorScheme.error
                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                })
            }
            val depart = local(l.partiLe)
            val retour = local(l.rentreLe)
            Text(listOfNotNull(depart?.format(JOUR_HEURE), retour?.format(HEURE)).joinToString(" → ") +
                (l.heures?.let { " · ${nombre(it)} h" } ?: ""), style = MaterialTheme.typography.bodyMedium)
            if (l.kilometres.isNotBlank() || l.trajet.isNotBlank()) {
                Text(listOfNotNull(l.kilometres.takeIf { it.isNotBlank() }?.let { "$it km" }, l.trajet.ifBlank { null }, l.vehicule.ifBlank { null })
                    .joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (l.remarque.isNotBlank()) Text("À revoir : ${l.remarque}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            l.frais.forEach { f ->
                Text("📎 ${f.libelle}" + if (f.sansMontant) "" else " · ${f.montant} €",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (f.justificatif) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = if (f.justificatif) Modifier.clickable { surJustificatif(f) } else Modifier)
            }
            if (l.accepteJustificatif) {
                TextButton(onClick = surAjout, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) { Text("Ajouter un justificatif") }
            }
        }
    }
}

/** Péage, stationnement (montant) ou autre justificatif (photo seule : tableau de bord…). */
@Composable
private fun DialogueJustificatif(modele: ModeleApplication, l: LigneReleve, fermer: () -> Unit) {
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    var nature by rememberSaveable { mutableStateOf("AUTRE") }
    var montant by rememberSaveable { mutableStateOf("") }
    var photo by remember { mutableStateOf<ByteArray?>(null) }
    var prise by remember { mutableStateOf<File?>(null) }
    var envoi by remember { mutableStateOf(false) }
    val appareil = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { reussie ->
        val fichier = prise
        prise = null
        if (reussie && fichier != null) portee.launch {
            // Réduite, sans position : c'est un justificatif, pas un constat.
            photo = Photographe.preparer(fichier, null, "", BuildConfig.VERSION_NAME)?.first
        } else fichier?.delete()
    }
    val pret = !envoi && (if (nature == "AUTRE") photo != null else montant.isNotBlank())
    AlertDialog(
        onDismissRequest = { if (!envoi) fermer() },
        title = { Text("Ajouter un justificatif") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(l.activite, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("AUTRE" to "Autre", "PEAGE" to "Péage", "STATIONNEMENT" to "Stationnement").forEach { (code, nom) ->
                        FilterChip(selected = nature == code, onClick = { nature = code }, label = { Text(nom) })
                    }
                }
                if (nature == "AUTRE") {
                    Text("Une photo sans montant : le compteur au départ ou à l'arrivée, ou toute autre preuve du trajet.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    Champ(montant, { montant = it.filter { c -> c.isDigit() || c == ',' || c == '.' }.take(7) }, "Montant (€)",
                        Modifier.fillMaxWidth(), clavier = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    photo?.let { o ->
                        val vignette = remember(o) { BitmapFactory.decodeByteArray(o, 0, o.size)?.asImageBitmap() }
                        vignette?.let { Image(it, contentDescription = "Photo prise", modifier = Modifier.size(56.dp)) }
                    }
                    OutlinedButton(onClick = {
                        val (fichier, adresse) = Photographe.nouvellePrise(contexte)
                        prise = fichier
                        appareil.launch(adresse)
                    }) { Text(if (photo == null) "Prendre la photo" else "Reprendre") }
                }
                modele.releveErreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = {
            Button(enabled = pret, onClick = {
                envoi = true
                // En cas d'échec, le message s'affiche et la fenêtre reste ouverte.
                modele.ajouterJustificatif(l.id, nature, montant, photo) { reussi -> envoi = false; if (reussi) fermer() }
            }) { Text("Ajouter") }
        },
        dismissButton = { TextButton(onClick = fermer, enabled = !envoi) { Text("Annuler") } },
    )
}

/** Ouvre un PDF (ou un justificatif qui n'est pas une image) dans l'application du téléphone ;
 * à défaut de lecteur, propose de le partager. */
private fun ouvrirFichier(contexte: Context, octets: ByteArray, nom: String) {
    val dossier = File(contexte.cacheDir, "partages").apply { mkdirs() }
    val fichier = File(dossier, nom.replace(Regex("[^A-Za-z0-9._-]"), "_"))
    fichier.writeBytes(octets)
    val uri = androidx.core.content.FileProvider.getUriForFile(contexte, "${contexte.packageName}.prises", fichier)
    val voir = Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/pdf").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    runCatching { contexte.startActivity(voir) }.onFailure {
        val envoi = Intent(Intent.ACTION_SEND).apply {
            type = "application/pdf"; putExtra(Intent.EXTRA_STREAM, uri); addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        contexte.startActivity(Intent.createChooser(envoi, "Ouvrir le relevé"))
    }
}
