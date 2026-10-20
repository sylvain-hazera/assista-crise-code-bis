#!/usr/bin/env python3
"""Rend les feuilles SCSS compatibles avec le mode sombre (voir src/styles.scss, « Thème »).

Remplace les couleurs codées en dur par `var(--ac-…, <couleur d'origine>)`. Les --ac-* ne sont
définies qu'en mode sombre : en mode clair la valeur de repli s'applique, le rendu ne change pas.

Classement selon la propriété et la couleur :
- fond : blancs et gris très clairs -> surfaces ; fonds pâles teintés -> fond teinté de la famille ;
- texte : gris foncés -> texte, moyens -> atténué, clairs -> discret ; texte de couleur trop
  sombre pour un fond sombre (contraste < 4,5) -> version claire de sa famille ;
- bordure (et stroke SVG) : gris clairs -> bordures ; bordures pâles teintées -> bordure de la famille ;
- fill SVG : gris seulement, clairs comme un fond, foncés comme un texte.
Les couleurs franches (boutons, dégradés), les textes blancs et les fonds foncés restent tels quels.
Le texte d'un bloc (ou d'un bloc imbriqué) dont le fond reste clair (badge jaune vif…) n'est pas converti.

Idempotent : une déclaration qui contient déjà var(--ac- n'est pas retouchée. Une couleur qui doit
rester la même dans les deux thèmes se marque d'un commentaire `// theme: fixe` sur sa ligne.
Usage : python3 scripts/convertir-couleurs-theme.py [--dry-run] [--annuler] [fichiers…]
        (défaut : src/**/*.scss ; --annuler remet les couleurs d'origine)
"""
import colorsys
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
EXCLUS = {'styles.scss', 'fonts.scss'}

# Surface sombre de référence pour le contraste des textes (--ac-surface).
SURFACE_SOMBRE = (0x1c, 0x1f, 0x26)

COULEUR = re.compile(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|\b(?:white|black)\b')
DECLARATION = re.compile(r'^(\s*)(--[a-z0-9-]+|[a-z-]+)(\s*:\s*)(.+?)(\s*)$', re.S)
# Fonctions Sass sur les couleurs : var() y casserait la compilation.
FONCTION_INTERDITE = re.compile(r'\b(?:darken|lighten|mix|rgba?|hsla?|transparentize|opacify|'
                                r'fade-(?:in|out)|adjust-color|scale-color|color\.[a-z-]+)\s*\(|#\{|\$')

# Noms des variables locales de certains composants (:host { --surface: … }).
VARIABLES_LOCALES = {'--bg': 'ac-bg', '--surface': 'bg', '--border': 'bordure', '--text': 'texte', '--muted': 'texte'}


def rgb(couleur):
    couleur = couleur.lower()
    if couleur == 'white':
        return (255, 255, 255)
    if couleur == 'black':
        return (0, 0, 0)
    h = couleur[1:]
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(c):
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def analyser(c):
    """(teinte en degrés, luminosité HSL, est neutre)."""
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    teinte = h * 360
    chroma = max(c) - min(c)
    # Les gris-bleus (« slate ») sont légèrement teintés mais servent de gris.
    neutre = chroma <= 10 or s < 0.15 or (190 <= teinte <= 235 and s < 0.5)
    return teinte, l, neutre


def famille(teinte):
    for limite, nom in ((15, 'red'), (40, 'orange'), (65, 'amber'), (170, 'green'), (195, 'teal'),
                        (235, 'blue'), (260, 'indigo'), (300, 'purple'), (345, 'pink')):
        if teinte < limite:
            return nom
    return 'red'


def jeton(type_propriete, couleur):
    """Variable --ac-* pour cette couleur dans ce type de propriété, ou None (inchangée)."""
    c = rgb(couleur)
    teinte, l, neutre = analyser(c)
    if type_propriete == 'bg':
        if neutre:
            if l >= 0.995:
                return 'ac-surface'
            if l >= 0.93:
                return 'ac-surface-2'
            if l >= 0.84:
                return 'ac-surface-3'
            return None
        return f'ac-{famille(teinte)}-bg' if l >= 0.8 else None
    if type_propriete == 'texte':
        if neutre:
            if l <= 0.3:
                return 'ac-text'
            if l <= 0.5:
                return 'ac-text-muted'
            if l <= 0.72:
                return 'ac-text-subtle'
            return None
        return f'ac-{famille(teinte)}-text' if contraste(c, SURFACE_SOMBRE) < 4.5 else None
    if type_propriete == 'remplissage':  # SVG : formes claires comme un fond, textes foncés comme un texte
        if not neutre:
            return None
        return jeton('bg', couleur) if l >= 0.84 else jeton('texte', couleur)
    if type_propriete == 'bordure':
        if neutre:
            if l >= 0.86:
                return 'ac-border'
            if l >= 0.7:
                return 'ac-border-strong'
            return None
        return f'ac-{famille(teinte)}-border' if l >= 0.75 else None
    return None


def type_de(propriete):
    if propriete.startswith('background'):
        return 'bg'
    if propriete == 'color':
        return 'texte'
    if propriete.startswith('border') or propriete.startswith('outline') or propriete == 'stroke':
        return 'bordure'
    if propriete == 'fill':
        return 'remplissage'
    if propriete in VARIABLES_LOCALES:
        return VARIABLES_LOCALES[propriete]
    return None


def declarations(texte):
    """Découpe le SCSS en (début, fin, n° de bloc) pour chaque segment terminé par ; ou }.
    Ignore commentaires et chaînes ; les segments terminés par { sont des sélecteurs."""
    segments, pile, compteur, parents = [], [0], 0, {}
    debut, i, n = 0, 0, len(texte)
    while i < n:
        c = texte[i]
        commentaire = None
        if texte.startswith('//', i) and (i == 0 or texte[i - 1] != ':'):
            fin = texte.find('\n', i)
            commentaire = n if fin < 0 else fin
        elif texte.startswith('/*', i):
            fin = texte.find('*/', i)
            commentaire = n if fin < 0 else fin + 2
        if commentaire is not None:
            # Commentaire avant une déclaration : la déclaration commence après lui.
            if not texte[debut:i].strip():
                debut = commentaire
            i = commentaire
            continue
        if c in '"\'':
            fin = texte.find(c, i + 1)
            i = n if fin < 0 else fin + 1
            continue
        if c == '{':
            compteur += 1
            parents[compteur] = pile[-1]
            pile.append(compteur)
            debut = i + 1
        elif c in ';}':
            segments.append((debut, i, pile[-1]))
            if c == '}' and len(pile) > 1:
                pile.pop()
            debut = i + 1
        i += 1
    return segments, parents


def sous_fond_clair(bloc, parents, fonds_clairs):
    """Le bloc ou un bloc parent (élément englobant, modificateur &.x) garde un fond clair."""
    while bloc:
        if bloc in fonds_clairs:
            return True
        bloc = parents.get(bloc)
    return False


ANNULATION = re.compile(r'var\(--ac-[a-z0-9-]+, ([^()]+?)\)')


def annuler(texte):
    """Inverse exact de convertir() : var(--ac-x, couleur) -> couleur."""
    return ANNULATION.subn(r'\1', texte)


def convertir(texte):
    segments, parents = declarations(texte)
    analyses = []
    fonds_clairs = set()
    for debut, fin, bloc in segments:
        m = DECLARATION.match(texte[debut:fin])
        if not m:
            analyses.append(None)
            continue
        propriete, valeur = m.group(2), m.group(4)
        analyses.append(m)
        if type_de(propriete) == 'bg':
            for couleur in COULEUR.findall(valeur):
                # Fond qui restera clair en mode sombre : son texte foncé doit le rester aussi.
                if not jeton('bg', couleur) and luminance(rgb(couleur)) > 0.3:
                    fonds_clairs.add(bloc)

    remplacements, nombre = [], 0
    for (debut, fin, bloc), m in zip(segments, analyses):
        if not m:
            continue
        propriete, valeur = m.group(2), m.group(4)
        type_propriete = type_de(propriete)
        if not type_propriete or 'var(--ac-' in valeur or FONCTION_INTERDITE.search(valeur):
            continue
        if type_propriete == 'texte' and sous_fond_clair(bloc, parents, fonds_clairs):
            continue
        fin_ligne = texte.find('\n', fin)
        if 'theme: fixe' in texte[fin:fin_ligne if fin_ligne >= 0 else len(texte)]:
            continue

        if type_propriete == 'ac-bg':  # --bg local : fond de page
            seule = COULEUR.fullmatch(valeur.replace('!important', '').strip())
            if not seule:
                continue
            nouvelle = valeur.replace(seule.group(0), f'var(--ac-bg, {seule.group(0)})')
        else:
            def remplacer(couleur_trouvee):
                nom = jeton(type_propriete, couleur_trouvee.group(0))
                return f'var(--{nom}, {couleur_trouvee.group(0)})' if nom else couleur_trouvee.group(0)
            nouvelle = COULEUR.sub(remplacer, valeur)
        if nouvelle != valeur:
            debut_valeur = debut + m.start(4)
            remplacements.append((debut_valeur, debut_valeur + len(valeur), nouvelle))
            nombre += 1

    for debut, fin, nouvelle in reversed(remplacements):
        texte = texte[:debut] + nouvelle + texte[fin:]
    return texte, nombre


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    simulation = '--dry-run' in sys.argv
    operation = annuler if '--annuler' in sys.argv else convertir
    fichiers = [Path(a) for a in args] or sorted((RACINE / 'src').rglob('*.scss'))
    total = 0
    for fichier in fichiers:
        if fichier.name in EXCLUS:
            continue
        avant = fichier.read_text(encoding='utf-8')
        apres, nombre = operation(avant)
        if nombre:
            total += nombre
            print(f'{nombre:4d}  {fichier.relative_to(RACINE) if fichier.is_absolute() else fichier}')
            if not simulation:
                fichier.write_text(apres, encoding='utf-8')
    verbe = 'restaurées' if operation is annuler else 'converties'
    print(f'{total} couleurs {verbe}{" (simulation)" if simulation else ""}')


if __name__ == '__main__':
    main()
