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
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
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
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.PeriodeReleve
import fr.assistacrise.mobile.Photographe
import fr.assistacrise.mobile.donnees.Reponse
import fr.assistacrise.mobile.domaine.AssociationReleve
import fr.assistacrise.mobile.domaine.BrouillonSortie
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
 * « Mon relevé » dans l'application (28/11/2026) : tout le circuit, comme sur le site.
 * - Mes sorties : la période, compléter un oubli, corriger, retirer une ligne ajoutée à la main,
 *   les justificatifs (péage, stationnement, autre), mes véhicules, mes frais de l'année, la
 *   renonciation au remboursement et son reçu, le relevé kilométrique en PDF.
 * - À valider (pour qui encadre) : valider, ou renvoyer avec ce qui est à revoir.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EcranReleve(modele: ModeleApplication) {
    val r = modele.releve
    var onglet by rememberSaveable { mutableStateOf(0) }
    var formulaire by remember { mutableStateOf<BrouillonSortie?>(null) }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { modele.aller(Ecran.COMPTE) }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            Text("Mon relevé", style = MaterialTheme.typography.titleLarge)
        }
        if (r?.encadre == true) {
            TabRow(selectedTabIndex = onglet) {
                Tab(selected = onglet == 0, onClick = { onglet = 0 }, text = { Text("Mes sorties") })
                Tab(selected = onglet == 1, onClick = { onglet = 1; modele.lireRelevesEquipe() }, text = {
                    val n = modele.relevesEquipe?.aValider ?: 0
                    Text(if (n > 0) "À valider ($n)" else "À valider")
                })
            }
        }
        FlowRow(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PeriodeReleve.entries.forEach { p ->
                FilterChip(selected = modele.periodeReleve == p, onClick = { modele.choisirPeriodeReleve(p) }, label = { Text(p.libelle) })
            }
        }
        modele.releveErreur?.let { Text(it, Modifier.padding(horizontal = 16.dp, vertical = 2.dp), color = MaterialTheme.colorScheme.error) }
        modele.releveMessage?.let { Text(it, Modifier.padding(horizontal = 16.dp, vertical = 2.dp), color = MaterialTheme.colorScheme.primary) }
        if (onglet == 1 && r?.encadre == true) RelevesAValider(modele) else MesSorties(modele) { formulaire = it }
    }
    val releve = r
    formulaire?.let { b -> if (releve != null) FormulaireSortie(modele, releve, b) { formulaire = null } }
}

// ── Mes sorties ────────────────────────────────────────────────────────────────────────────

@Composable
private fun MesSorties(modele: ModeleApplication, ouvrirFormulaire: (BrouillonSortie) -> Unit) {
    val r = modele.releve
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    var ajoutPour by remember { mutableStateOf<LigneReleve?>(null) }
    var aRetirer by remember { mutableStateOf<LigneReleve?>(null) }
    var apercu by remember { mutableStateOf<ByteArray?>(null) }
    var nouveauVehicule by remember { mutableStateOf(false) }
    var renonciation by remember { mutableStateOf<AssociationReleve?>(null) }
    val defilement = rememberLazyListState()
    val voir: (FraisLigne) -> Unit = { f ->
        portee.launch {
            when (val o = modele.octetsJustificatif(f.id)) {
                is Reponse.Ok -> if (BitmapFactory.decodeByteArray(o.valeur, 0, o.valeur.size) != null) apercu = o.valeur
                                 else ouvrirFichier(contexte, o.valeur, f.nomJustificatif.ifBlank { "justificatif.pdf" })
                else -> Unit
            }
        }
    }

    LazyColumn(
        Modifier.fillMaxSize().ascenseur(defilement, MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)),
        state = defilement, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (r == null) {
            item { Text(if (modele.releveEnCours) "Lecture du relevé…" else "", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            return@LazyColumn
        }
        item {
            Text("${nombre(r.totalHeures)} h · ${nombre(r.totalKilometres)} km sur la période", style = MaterialTheme.typography.titleMedium)
        }
        if (r.peutAjouter) item {
            Button(onClick = {
                ouvrirFormulaire(BrouillonSortie(cible = (r.crises.map { "c:${it.id}" } + r.manifestations.map { "m:${it.id}" }).singleOrNull() ?: "",
                    equipe = r.equipes.singleOrNull()?.id ?: "", vehiculePersonnel = r.mesVehicules.singleOrNull()?.id ?: ""))
            }, modifier = Modifier.fillMaxWidth()) { Text("Ajouter une sortie oubliée") }
        }
        items(r.lignes, key = { it.id }) { l ->
            CarteLigne(l, voir = voir, actions = {
                if (l.corrigeable) TextButton(onClick = { ouvrirFormulaire(BrouillonSortie.depuis(l)) }) {
                    Text(if (l.rentreLe == null) "Compléter le retour" else "Corriger")
                }
                if (l.accepteJustificatif) TextButton(onClick = { ajoutPour = l }) { Text("Justificatif") }
                if (l.retirable) TextButton(onClick = { aRetirer = l }) { Text("Retirer") }
            }, retirerFrais = if (l.accepteJustificatif) { f -> modele.retirerFrais(l.id, f.id) } else null)
        }
        if (r.lignes.isEmpty()) item { Text("Aucune sortie sur cette période.", color = MaterialTheme.colorScheme.onSurfaceVariant) }

        item { Text("Mes véhicules", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp)) }
        items(r.mesVehicules, key = { "v-${it.id}" }) { v ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(v.designation, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                TextButton(onClick = { modele.retirerVehicule(v.id) }) { Text("Retirer") }
            }
        }
        item {
            if (r.mesVehicules.isEmpty()) Text("Déclarez votre véhicule une fois : immatriculation et puissance figurent sur le relevé à signer.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = { nouveauVehicule = true }) { Text("Déclarer un véhicule") }
        }

        if (r.frais.isNotEmpty()) {
            item { Text("Mes frais et le relevé à signer", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp)) }
            items(r.frais, key = { "a-${it.institution}" }) { a ->
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(a.nom, style = MaterialTheme.typography.titleSmall)
                        Text("${nombre(a.kilometres)} km validés en ${a.annee}" + if (a.montant != "0.00") ", soit ${a.montant} € au tarif de l'association" else "",
                            style = MaterialTheme.typography.bodySmall)
                        a.abandon?.let { ab ->
                            Text("Renonciation : ${ab.libelle}" + if (ab.motifRefus.isNotBlank()) " — ${ab.motifRefus}" else "",
                                style = MaterialTheme.typography.bodySmall, color = if (ab.recuDisponible) EnLigne else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        OutlinedButton(onClick = {
                            portee.launch {
                                (modele.releveKmPdf(a.institution) as? Reponse.Ok)?.let { ouvrirFichier(contexte, it.valeur, "releve-km-${r.du}-${r.au}.pdf") }
                            }
                        }, modifier = Modifier.fillMaxWidth()) { Text("Relevé kilométrique de la période (PDF)") }
                        a.abandon?.takeIf { it.recuDisponible }?.let { ab ->
                            OutlinedButton(onClick = {
                                portee.launch { (modele.recuFiscal(ab.id) as? Reponse.Ok)?.let { ouvrirFichier(contexte, it.valeur, "recu-${ab.numeroRecu}.pdf") } }
                            }, modifier = Modifier.fillMaxWidth()) { Text("Reçu fiscal n° ${ab.numeroRecu}") }
                        }
                        if (a.renonciationPossible) {
                            TextButton(onClick = { renonciation = a }) { Text("Renoncer au remboursement (reçu fiscal)") }
                        }
                    }
                }
            }
        }
    }

    ajoutPour?.let { l -> DialogueJustificatif(modele, l) { ajoutPour = null } }
    aRetirer?.let { l ->
        AlertDialog(onDismissRequest = { aRetirer = null }, title = { Text("Retirer cette sortie ?") },
            text = { Text("${l.activite}, ${local(l.partiLe)?.format(JOUR_HEURE) ?: ""}. Elle disparaît de votre relevé.") },
            confirmButton = { Button(onClick = { modele.retirerSortie(l.id); aRetirer = null }) { Text("Retirer") } },
            dismissButton = { TextButton(onClick = { aRetirer = null }) { Text("Annuler") } })
    }
    if (nouveauVehicule) DialogueVehicule(modele) { nouveauVehicule = false }
    renonciation?.let { a -> DialogueRenonciation(modele, a) { renonciation = null } }
    apercu?.let { octets ->
        val image = remember(octets) { BitmapFactory.decodeByteArray(octets, 0, octets.size)?.asImageBitmap() }
        AlertDialog(onDismissRequest = { apercu = null }, confirmButton = { TextButton(onClick = { apercu = null }) { Text("Fermer") } },
            text = { image?.let { Image(it, contentDescription = "Justificatif", modifier = Modifier.fillMaxWidth().heightIn(max = 480.dp)) } })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CarteLigne(l: LigneReleve, voir: (FraisLigne) -> Unit, actions: @Composable () -> Unit, retirerFrais: ((FraisLigne) -> Unit)?) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 4.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(l.activite, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                Text(l.etat.libelle, style = MaterialTheme.typography.labelMedium, color = when (l.etat) {
                    EtatLigne.VALIDEE -> EnLigne; EtatLigne.A_REVOIR -> MaterialTheme.colorScheme.error
                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                })
            }
            Text(listOfNotNull(local(l.partiLe)?.format(JOUR_HEURE), local(l.rentreLe)?.format(HEURE)).joinToString(" → ") +
                (l.heures?.let { " · ${nombre(it)} h" } ?: "") + if (l.aLaMain) " · à la main" else "", style = MaterialTheme.typography.bodyMedium)
            if (l.equipe.isNotBlank()) Text("Avec ${l.equipe}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (l.kilometres.isNotBlank() || l.trajet.isNotBlank()) {
                Text(listOfNotNull(l.kilometres.takeIf { it.isNotBlank() }?.let { "$it km" }, l.trajet.ifBlank { null }, l.vehicule.ifBlank { null })
                    .joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (l.motif.isNotBlank() && l.motif != l.activite) Text(l.motif, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (l.remarque.isNotBlank()) Text("À revoir : ${l.remarque}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            l.frais.forEach { f ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("📎 ${f.libelle}" + if (f.sansMontant) "" else " · ${f.montant} €", style = MaterialTheme.typography.bodySmall,
                        color = if (f.justificatif) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f).then(if (f.justificatif) Modifier.clickable { voir(f) } else Modifier))
                    if (retirerFrais != null) TextButton(onClick = { retirerFrais(f) }) { Text("retirer") }
                }
            }
            FlowRow { actions() }
        }
    }
}

// ── À valider (encadrement, bureau, mairie) ─────────────────────────────────────────────────

@Composable
private fun RelevesAValider(modele: ModeleApplication) {
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    var aRenvoyer by remember { mutableStateOf<LigneReleve?>(null) }
    var apercu by remember { mutableStateOf<ByteArray?>(null) }
    LaunchedEffect(Unit) { if (modele.relevesEquipe == null) modele.lireRelevesEquipe() }
    val equipe = modele.relevesEquipe
    val defilement = rememberLazyListState()
    LazyColumn(
        Modifier.fillMaxSize().ascenseur(defilement, MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)),
        state = defilement, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text("Vous relisez et validez ; vous ne corrigez pas. Une ligne fausse se renvoie avec une remarque : seule la personne "
                + "complète son relevé. Une ligne validée ne se modifie plus.", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (equipe == null) { item { Text("Lecture…", color = MaterialTheme.colorScheme.onSurfaceVariant) }; return@LazyColumn }
        if (equipe.fiches.isEmpty()) item { Text("Aucune sortie à relire sur cette période.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        equipe.fiches.forEach { fiche ->
            item(key = "p-${fiche.personne}") {
                Text("${fiche.personne} — ${nombre(fiche.totalHeures)} h déclarées, ${nombre(fiche.heuresValidees)} h validées",
                    style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 6.dp))
            }
            items(fiche.lignes, key = { "e-${it.id}" }) { l ->
                CarteLigne(l, voir = { f ->
                    portee.launch {
                        when (val o = modele.octetsJustificatif(f.id)) {
                            is Reponse.Ok -> if (BitmapFactory.decodeByteArray(o.valeur, 0, o.valeur.size) != null) apercu = o.valeur
                                             else ouvrirFichier(contexte, o.valeur, f.nomJustificatif.ifBlank { "justificatif.pdf" })
                            else -> Unit
                        }
                    }
                }, actions = {
                    when {
                        l.validee -> TextButton(onClick = { aRenvoyer = l }) { Text("Lever et renvoyer") }
                        l.remarque.isNotBlank() -> Unit                 // déjà renvoyée : à la personne de corriger
                        l.rentreLe != null -> {
                            Button(onClick = { modele.relire(l.id, "valider") }) { Text("Valider") }
                            TextButton(onClick = { aRenvoyer = l }) { Text("À revoir") }
                        }
                    }
                }, retirerFrais = null)
            }
        }
    }
    aRenvoyer?.let { l ->
        var remarque by remember(l.id) { mutableStateOf("") }
        AlertDialog(onDismissRequest = { aRenvoyer = null }, title = { Text("Ce qui est à revoir") },
            text = { Champ(remarque, { remarque = it.take(500) }, "Remarque pour la personne", Modifier.fillMaxWidth(), aide = "Exemple : retour à 17 h, pas 18 h") },
            confirmButton = {
                Button(enabled = remarque.isNotBlank(), onClick = { modele.relire(l.id, "renvoyer", remarque) { if (it) aRenvoyer = null } }) { Text("Renvoyer") }
            },
            dismissButton = { TextButton(onClick = { aRenvoyer = null }) { Text("Annuler") } })
    }
    apercu?.let { octets ->
        val image = remember(octets) { BitmapFactory.decodeByteArray(octets, 0, octets.size)?.asImageBitmap() }
        AlertDialog(onDismissRequest = { apercu = null }, confirmButton = { TextButton(onClick = { apercu = null }) { Text("Fermer") } },
            text = { image?.let { Image(it, contentDescription = "Justificatif", modifier = Modifier.fillMaxWidth().heightIn(max = 480.dp)) } })
    }
}

// ── Fenêtres ──────────────────────────────────────────────────────────────────────────────

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

@Composable
private fun DialogueVehicule(modele: ModeleApplication, fermer: () -> Unit) {
    var genre by remember { mutableStateOf("VOITURE") }
    var libelle by remember { mutableStateOf("") }
    var immat by remember { mutableStateOf("") }
    var cv by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = fermer, title = { Text("Déclarer un véhicule") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = genre == "VOITURE", onClick = { genre = "VOITURE" }, label = { Text("Voiture") })
                FilterChip(selected = genre == "DEUX_ROUES", onClick = { genre = "DEUX_ROUES" }, label = { Text("Moto, scooter") })
            }
            Champ(libelle, { libelle = it.take(80) }, "Nom (Clio grise)", Modifier.fillMaxWidth())
            Champ(immat, { immat = it.take(20).uppercase() }, "Immatriculation", Modifier.fillMaxWidth())
            Champ(cv, { cv = it.filter(Char::isDigit).take(2) }, "Puissance fiscale (CV)", Modifier.fillMaxWidth(),
                aide = "Case P.6 de la carte grise", clavier = KeyboardOptions(keyboardType = KeyboardType.Number))
            modele.releveErreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        }
    }, confirmButton = {
        Button(enabled = libelle.isNotBlank() || immat.isNotBlank(), onClick = {
            modele.ajouterVehicule(genre, libelle, immat, cv) { if (it) fermer() }
        }) { Text("Enregistrer") }
    }, dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } })
}

@Composable
private fun DialogueRenonciation(modele: ModeleApplication, a: AssociationReleve, fermer: () -> Unit) {
    var adresse by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = fermer, title = { Text("Renoncer au remboursement") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Renoncer au remboursement de vos frais validés (${a.montant} €) est un don à ${a.nom} : elle vous délivre un reçu fiscal "
                + "qui ouvre droit à une réduction d'impôt, selon votre situation.", style = MaterialTheme.typography.bodySmall)
            Champ(adresse, { adresse = it.take(300) }, "Votre adresse (figure sur le reçu)", Modifier.fillMaxWidth())
            modele.releveErreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        }
    }, confirmButton = {
        Button(enabled = adresse.isNotBlank(), onClick = { modele.renoncer(a, adresse) { if (it) fermer() } }) { Text("Je renonce") }
    }, dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } })
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
        contexte.startActivity(Intent.createChooser(envoi, "Ouvrir le document"))
    }
}
