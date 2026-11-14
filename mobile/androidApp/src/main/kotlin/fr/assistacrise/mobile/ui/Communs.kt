package fr.assistacrise.mobile.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.R
import fr.assistacrise.mobile.domaine.EtatLien

/** Le logo, toujours sur un disque blanc : il est dessiné pour un fond clair. */
@Composable
fun Logo(taille: Dp, modifier: Modifier = Modifier) {
    Box(modifier.size(taille).clip(CircleShape).background(Color.White), contentAlignment = Alignment.Center) {
        Image(
            painter = painterResource(R.drawable.logo),
            contentDescription = stringResource(R.string.nom_application),
            modifier = Modifier.size(taille * 0.94f),
        )
    }
}

/** Un champ de saisie avec son erreur dessous — la seule façon d'afficher une erreur de champ. */
@Composable
fun Champ(
    valeur: String,
    surChangement: (String) -> Unit,
    libelle: String,
    modifier: Modifier = Modifier,
    erreur: String? = null,
    aide: String? = null,
    clavier: KeyboardOptions = KeyboardOptions.Default,
    transformation: VisualTransformation = VisualTransformation.None,
    actif: Boolean = true,
    fin: @Composable (() -> Unit)? = null,
) {
    OutlinedTextField(
        value = valeur,
        onValueChange = surChangement,
        label = { Text(libelle) },
        modifier = modifier,
        singleLine = true,
        enabled = actif,
        isError = erreur != null,
        supportingText = (erreur ?: aide)?.let { texte -> { Text(texte) } },
        keyboardOptions = clavier,
        visualTransformation = transformation,
        trailingIcon = fin,
    )
}

/**
 * L'état du lien, affiché en permanence (dossier § 4) : par où part ce que je déclare,
 * maintenant ? Une pastille et un mot — jamais la couleur seule.
 */
@Composable
fun PastilleLien(etat: EtatLien, modifier: Modifier = Modifier) {
    val (couleur, mot) = when (etat) {
        EtatLien.INTERNET -> EnLigne to "En ligne"
        EtatLien.MESH -> Attente to "Radio"
        EtatLien.AUCUN -> Refus to "Hors ligne"
    }
    Row(
        modifier
            .clip(RoundedCornerShape(50))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(9.dp).clip(CircleShape).background(couleur))
        Spacer(Modifier.width(6.dp))
        Text(mot, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
