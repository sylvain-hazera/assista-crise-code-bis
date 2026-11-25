package fr.assistacrise.mobile.ui

import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Un ascenseur toujours visible sur une LazyColumn (25/11/2026) : Android n'en dessine pas par
 * défaut. Position et taille estimées à partir des éléments visibles (hauteurs variables).
 */
fun Modifier.ascenseur(etat: LazyListState, couleur: Color): Modifier = drawWithContent {
    drawContent()
    val info = etat.layoutInfo
    val visibles = info.visibleItemsInfo
    if (visibles.isEmpty() || info.totalItemsCount == 0) return@drawWithContent
    val vue = (info.viewportEndOffset - info.viewportStartOffset).toFloat()
    val moyenne = visibles.sumOf { it.size }.toFloat() / visibles.size
    val contenu = moyenne * info.totalItemsCount + info.beforeContentPadding + info.afterContentPadding
    if (contenu <= vue + 1f) return@drawWithContent
    val premier = visibles.first()
    val parcouru = (premier.index * moyenne - premier.offset + info.beforeContentPadding).coerceIn(0f, contenu - vue)
    val hauteur = (vue * vue / contenu).coerceAtLeast(32.dp.toPx()).coerceAtMost(vue)
    val y = parcouru / (contenu - vue) * (vue - hauteur)
    val largeur = 4.dp.toPx()
    drawRoundRect(couleur, topLeft = Offset(size.width - largeur - 2.dp.toPx(), y), size = Size(largeur, hauteur),
                  cornerRadius = CornerRadius(largeur / 2))
}
