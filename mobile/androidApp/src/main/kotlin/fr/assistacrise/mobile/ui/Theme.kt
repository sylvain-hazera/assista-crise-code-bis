package fr.assistacrise.mobile.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import fr.assistacrise.mobile.R

// La palette (couleurs de la marque, jeux clair et sombre) vit dans `Marque.kt`, un fichier par
// marque : src/reserveResilience/... et src/assistaCrise/... Ce fichier-ci ne porte que ce que
// les deux applications partagent — les couleurs d'état, la typographie, le thème.

/** Couleurs d'état : elles disent quelque chose, elles ne décorent pas. */
val Attente = Color(0xFFB45309)
val Refus = Color(0xFFB91C1C)
val EnLigne = Color(0xFF15803D)

@OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)
private fun police(ressource: Int, vararg graisses: FontWeight) = FontFamily(
    graisses.map { g ->
        Font(ressource, weight = g, variationSettings = FontVariation.Settings(FontVariation.weight(g.weight)))
    },
)

private val Titres = police(R.font.quicksand, FontWeight.Medium, FontWeight.SemiBold, FontWeight.Bold)
private val Texte = police(R.font.open_sans, FontWeight.Normal, FontWeight.Medium, FontWeight.SemiBold)

private val Typo = Typography().let { base ->
    fun TextStyle.titre(graisse: FontWeight = FontWeight.Bold) = copy(fontFamily = Titres, fontWeight = graisse)
    fun TextStyle.texte() = copy(fontFamily = Texte)
    Typography(
        displaySmall = base.displaySmall.titre(),
        headlineLarge = base.headlineLarge.titre(),
        headlineMedium = base.headlineMedium.titre(),
        headlineSmall = base.headlineSmall.titre(),
        titleLarge = base.titleLarge.titre(),
        titleMedium = base.titleMedium.titre(FontWeight.SemiBold),
        titleSmall = base.titleSmall.titre(FontWeight.SemiBold),
        bodyLarge = base.bodyLarge.texte(),
        bodyMedium = base.bodyMedium.texte(),
        bodySmall = base.bodySmall.texte(),
        labelLarge = base.labelLarge.texte().copy(fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
        labelMedium = base.labelMedium.texte(),
        labelSmall = base.labelSmall.texte(),
    )
}

@Composable
fun ThemeApplication(contenu: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) PaletteSombre else PaletteClaire,
        typography = Typo,
        content = contenu,
    )
}
