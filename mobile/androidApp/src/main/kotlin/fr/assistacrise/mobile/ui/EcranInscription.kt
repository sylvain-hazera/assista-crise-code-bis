package fr.assistacrise.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.BuildConfig
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.R
import fr.assistacrise.mobile.domaine.Champs
import fr.assistacrise.mobile.domaine.ForceMotDePasse
import fr.assistacrise.mobile.domaine.Inscription

@Composable
fun EcranInscription(modele: ModeleApplication) {
    var prenom by rememberSaveable { mutableStateOf("") }
    var nom by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var telephone by rememberSaveable { mutableStateOf("") }
    var codePostal by rememberSaveable { mutableStateOf("") }
    var motDePasse by rememberSaveable { mutableStateOf("") }
    var visible by rememberSaveable { mutableStateOf(false) }
    // Cochée par défaut, comme sur le site : qui installe cette application vient pour
    // l'association. Le texte dessous dit ce que la case engage, et qu'on peut la décocher.
    var reserve by rememberSaveable { mutableStateOf(true) }
    var conditions by rememberSaveable { mutableStateOf(false) }

    val etat = modele.inscription
    val liens = LocalUriHandler.current
    val marque = stringResource(R.string.nom_application)
    val suivant = ImeAction.Next

    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, top = 4.dp)) {
            IconButton(onClick = { modele.aller(Ecran.CONNEXION) }) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour à la connexion")
            }
            Text("Créer un compte", style = MaterialTheme.typography.titleLarge)
        }

        Column(Modifier.padding(horizontal = 24.dp).widthIn(max = 480.dp).fillMaxWidth()) {
            Text(
                "Ce compte est personnel. Les mairies et les services de secours créent le leur sur le site.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(16.dp))

            Champ(prenom, { prenom = it }, "Prénom", Modifier.fillMaxWidth(), erreur = etat.champs[Champs.PRENOM],
                clavier = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = suivant), actif = !etat.enCours)
            Champ(nom, { nom = it }, "Nom", Modifier.fillMaxWidth(), erreur = etat.champs[Champs.NOM],
                clavier = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = suivant), actif = !etat.enCours)
            Champ(email, { email = it }, "Adresse e-mail", Modifier.fillMaxWidth(), erreur = etat.champs[Champs.EMAIL],
                clavier = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = suivant), actif = !etat.enCours)
            Champ(telephone, { telephone = it }, "Téléphone", Modifier.fillMaxWidth(), erreur = etat.champs[Champs.TELEPHONE],
                aide = "Pour vous joindre en cas de mobilisation.",
                clavier = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = suivant), actif = !etat.enCours)
            Champ(codePostal, { codePostal = it.filter(Char::isDigit).take(5) }, "Code postal", Modifier.fillMaxWidth(),
                erreur = etat.champs[Champs.CODE_POSTAL],
                clavier = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = suivant), actif = !etat.enCours)
            Champ(
                motDePasse, { motDePasse = it }, "Mot de passe", Modifier.fillMaxWidth(), erreur = etat.champs[Champs.MOT_DE_PASSE],
                clavier = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                transformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
                actif = !etat.enCours,
                fin = { TextButton(onClick = { visible = !visible }) { Text(if (visible) "Masquer" else "Afficher") } },
            )
            ConditionsMotDePasse(ForceMotDePasse.de(motDePasse))
            Spacer(Modifier.height(12.dp))

            CaseACocher(reserve, { reserve = it }, !etat.enCours) {
                Text("Je souhaite rejoindre $marque", style = MaterialTheme.typography.bodyLarge)
                Text(
                    "L'association verra votre nom, votre téléphone et votre adresse e-mail pour examiner votre candidature. Vous pouvez décocher cette case.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(4.dp))
            CaseACocher(conditions, { conditions = it }, !etat.enCours) {
                Text("J'accepte les conditions générales d'utilisation", style = MaterialTheme.typography.bodyLarge)
                Text(
                    "Lire les conditions",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.secondary,
                    modifier = Modifier.clickable { liens.openUri(BuildConfig.URL_SITE + "/cgu") }.padding(vertical = 4.dp),
                )
                etat.champs[Champs.CONDITIONS]?.let {
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
            }

            etat.erreur?.let {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 12.dp))
            }
            Spacer(Modifier.height(16.dp))
            Button(
                onClick = {
                    modele.inscrire(Inscription(prenom, nom, email, telephone, codePostal, motDePasse, reserve, conditions))
                },
                enabled = !etat.enCours,
                modifier = Modifier.fillMaxWidth().height(52.dp),
            ) {
                if (etat.enCours) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                else Text("Créer mon compte")
            }
        }
    }
}

@Composable
private fun CaseACocher(cochee: Boolean, surChangement: (Boolean) -> Unit, active: Boolean, texte: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = active) { surChangement(!cochee) }.padding(vertical = 4.dp)) {
        Checkbox(checked = cochee, onCheckedChange = surChangement, enabled = active)
        Column(Modifier.padding(top = 12.dp)) { texte() }
    }
}

/** Les conditions du mot de passe, cochées une à une pendant la frappe. */
@Composable
private fun ConditionsMotDePasse(force: ForceMotDePasse) {
    Column(Modifier.padding(start = 4.dp, top = 2.dp)) {
        Condition(force.longueur, "8 caractères au moins")
        Condition(force.majuscule && force.minuscule, "une majuscule et une minuscule")
        Condition(force.chiffre, "un chiffre")
        Condition(force.special, "un caractère spécial, par exemple ! ? . ,")
    }
}

@Composable
private fun Condition(remplie: Boolean, texte: String) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 1.dp)) {
        Icon(
            if (remplie) Icons.Filled.Check else Icons.Filled.Close,
            contentDescription = if (remplie) "Rempli" else "À remplir",
            tint = if (remplie) EnLigne else MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(6.dp))
        Text(texte, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
