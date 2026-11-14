package fr.assistacrise.mobile.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import fr.assistacrise.mobile.R

// Charte Réserve Résilience, telle que le serveur la connaît (migration 0199) :
// bleu nuit #3c4d81, bleu clair #2ea3f2, Quicksand pour les titres, Open Sans pour le texte.
val BleuNuit = Color(0xFF3C4D81)
val BleuClair = Color(0xFF2EA3F2)

/** Couleurs d'état : elles disent quelque chose, elles ne décorent pas. */
val Attente = Color(0xFFB45309)
val Refus = Color(0xFFB91C1C)
val EnLigne = Color(0xFF15803D)

private val Clair = lightColorScheme(
    primary = BleuNuit,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDCE2F5),
    onPrimaryContainer = Color(0xFF1B2547),
    secondary = Color(0xFF14689F),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFD6ECFC),
    onSecondaryContainer = Color(0xFF0B3654),
    background = Color(0xFFF7F8FC),
    onBackground = Color(0xFF1A1D29),
    surface = Color.White,
    onSurface = Color(0xFF1A1D29),
    surfaceVariant = Color(0xFFE6E9F3),
    onSurfaceVariant = Color(0xFF4A5068),
    outline = Color(0xFF7C839C),
    error = Refus,
)

private val Sombre = darkColorScheme(
    primary = Color(0xFFAEBBE8),
    onPrimary = Color(0xFF16204A),
    primaryContainer = Color(0xFF2E3C68),
    onPrimaryContainer = Color(0xFFDCE2F5),
    secondary = Color(0xFF8CCBF7),
    onSecondary = Color(0xFF07304C),
    secondaryContainer = Color(0xFF12496F),
    onSecondaryContainer = Color(0xFFD6ECFC),
    background = Color(0xFF12141C),
    onBackground = Color(0xFFE4E6EF),
    surface = Color(0xFF1A1D29),
    onSurface = Color(0xFFE4E6EF),
    surfaceVariant = Color(0xFF2A2E3D),
    onSurfaceVariant = Color(0xFFC1C6D8),
    outline = Color(0xFF8B91A8),
)

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
        colorScheme = if (isSystemInDarkTheme()) Sombre else Clair,
        typography = Typo,
        content = contenu,
    )
}
