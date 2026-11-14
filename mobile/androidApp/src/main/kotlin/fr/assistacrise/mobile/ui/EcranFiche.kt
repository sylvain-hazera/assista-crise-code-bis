package fr.assistacrise.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Fiche

/** « Ma fiche de bénévole » : ce que la personne relit et corrige d'elle-même, et ses titres. */
@Composable
fun EcranFiche(modele: ModeleApplication) {
    val fiche by modele.fiche.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().imePadding()) {
        EnTeteRetour("Ma fiche", modele) { modele.aller(Ecran.COMPTE) }
        val f = fiche
        when {
            modele.chargement && f == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            f == null -> Text(
                if (modele.horsLigne) "Pas de réseau : votre fiche n'a pas encore été chargée sur ce téléphone." else "Vous n'avez pas de fiche de bénévole.",
                modifier = Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            // `key` sur la fiche servie : après un enregistrement, la saisie repart de ce que le serveur a gardé.
            else -> androidx.compose.runtime.key(f) { Formulaire(f, modele) }
        }
    }
}

@Composable
private fun Formulaire(fiche: Fiche, modele: ModeleApplication) {
    var saisie by remember { mutableStateOf(fiche) }
    val etat = modele.formulaireFiche
    val adresseChangee = saisie.adresse != fiche.adresse || saisie.codePostal != fiche.codePostal || saisie.ville != fiche.ville

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 32.dp)) {
        if (modele.horsLigne) {
            Text("Pas de réseau : voici votre fiche telle qu'elle était à la dernière lecture.", style = MaterialTheme.typography.bodySmall, color = Attente)
            Spacer(Modifier.height(8.dp))
        }
        fiche.avertissement?.takeIf { it.isNotBlank() }?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, color = Attente)
            Spacer(Modifier.height(8.dp))
        }

        TitreDeSection("Où vous joindre")
        Text("Votre adresse sert à vous rattacher à l'équipe de votre département. Seul votre encadrement la voit.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Champ(saisie.adresse, { saisie = saisie.copy(adresse = it) }, "Adresse", Modifier.fillMaxWidth(), erreur = etat.champs["adresse"])
        Row {
            Champ(saisie.codePostal, { saisie = saisie.copy(codePostal = it.filter(Char::isDigit).take(5)) }, "Code postal", Modifier.weight(1f), erreur = etat.champs["code_postal"], clavier = KeyboardOptions(keyboardType = KeyboardType.Number))
            Spacer(Modifier.padding(4.dp))
            Champ(saisie.ville, { saisie = saisie.copy(ville = it) }, "Commune", Modifier.weight(2f), erreur = etat.champs["ville"])
        }
        Text(
            // Le secteur ne se saisit pas : il vient de l'adresse. On prévient qu'en la changeant on change d'équipe.
            if (adresseChangee) "L'adresse a changé : à l'enregistrement, vous serez replacé dans l'équipe du département correspondant."
            else fiche.departement?.let { "Département retenu : $it." } ?: "Département non déterminé : vérifiez votre adresse.",
            style = MaterialTheme.typography.bodySmall, color = if (adresseChangee) Attente else MaterialTheme.colorScheme.onSurfaceVariant,
        )

        TitreDeSection("Vous")
        Champ(saisie.dateNaissance ?: "", { saisie = saisie.copy(dateNaissance = it.take(10)) }, "Date de naissance", Modifier.fillMaxWidth(), erreur = etat.champs["date_naissance"], aide = "Année-mois-jour, par exemple 1985-04-23")
        Champ(saisie.metier, { saisie = saisie.copy(metier = it) }, "Métier", Modifier.fillMaxWidth(), erreur = etat.champs["metier"])
        Choix("Situation", Fiche.SITUATIONS, saisie.situation) { saisie = saisie.copy(situation = it) }
        Choix("Engagement envisagé", Fiche.FREQUENCES, saisie.frequence) { saisie = saisie.copy(frequence = it) }
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().clickable { saisie = saisie.copy(premiersSecours = !saisie.premiersSecours) }) {
            Checkbox(saisie.premiersSecours, onCheckedChange = { saisie = saisie.copy(premiersSecours = it) })
            Text("J'ai un diplôme de premiers secours", style = MaterialTheme.typography.bodyLarge)
        }

        etat.erreur?.let { Spacer(Modifier.height(8.dp)); Text(it, color = Refus, style = MaterialTheme.typography.bodyMedium) }
        Spacer(Modifier.height(16.dp))
        Button(onClick = { modele.enregistrerFiche(saisie) }, enabled = !etat.enCours, modifier = Modifier.fillMaxWidth().height(50.dp)) {
            Text(if (etat.enCours) "Enregistrement…" else "Enregistrer")
        }

        Spacer(Modifier.height(16.dp))
        Text("Vos justificatifs (permis, diplômes) sont dans « Mon compte », rubrique Mes documents.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun TitreDeSection(texte: String) {
    Spacer(Modifier.height(24.dp))
    Text(texte, style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(6.dp))
}

/** Une liste déroulante : le libellé au-dessus, la valeur choisie sur le bouton. */
@Composable
private fun Choix(libelle: String, options: List<Pair<String, String>>, valeur: String, surChoix: (String) -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(libelle, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Box {
            OutlinedButton(onClick = { ouvert = true }, modifier = Modifier.fillMaxWidth()) {
                Text(options.firstOrNull { it.first == valeur }?.second ?: options.first().second)
            }
            DropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
                options.forEach { (code, nom) -> DropdownMenuItem(text = { Text(nom) }, onClick = { surChoix(code); ouvert = false }) }
            }
        }
    }
}
