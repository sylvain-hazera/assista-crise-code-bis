"""Format canonique d'un numéro de téléphone, pour qu'il traverse n'importe quel fournisseur.

Demande de Sylvain du 12/11/2026 : « prévois un nouveau format d'enregistrement des numéros de
portable, et prévois le complet pour être compatible ensuite toutes solutions ».

**Le format retenu est E.164** — `+262692123456` : indicatif pays, puis le numéro national sans
son zéro de préfixe, sans espace ni ponctuation. C'est la seule écriture qu'acceptent sans
discuter Brevo, Twilio, OVH, Orange Contact Everyone et les autres. Chaque fournisseur a
ensuite sa manie (Brevo veut le même numéro **sans** le « + »), mais tous savent partir d'E.164 :
c'est au moment d'appeler l'API qu'on retire ce qu'il faut, pas au moment d'enregistrer.

**Pourquoi un format d'enregistrement et pas seulement de conversion.** Jusqu'ici chacun
saisissait « 06 12 34 56 78 » et la conversion se faisait à l'envoi. Trois ennuis :

1. on ne sait pas, en lisant la base, si « 0692… » est un portable réunionnais ou une erreur de
   saisie métropolitaine — l'information de pays est perdue à la saisie et devinée trop tard ;
2. un numéro étranger (un renfort belge, un prestataire suisse) n'avait aucune façon correcte
   d'être saisi ;
3. la même conversion devait être refaite par chaque fournisseur, avec ses propres bogues.

**L'outre-mer n'est pas en +33**, et c'est le piège qui a motivé tout ceci : un portable
réunionnais « 0692 12 34 56 » converti en « 33692… » part vers un numéro métropolitain qui
n'est pas le sien. Le projet a un satellite à La Réunion.

**On ne jette jamais ce qu'on ne sait pas lire.** Un numéro qui n'entre pas dans le moule est
conservé tel quel, et `est_canonique` dit simplement qu'il ne l'est pas : écraser la saisie de
quelqu'un par une interprétation hasardeuse ferait perdre le seul moyen de le joindre.
"""
import re

#: Indicatif pays par préfixe national français, pour les numéros saisis en dix chiffres.
#: Le préfixe est CONSERVÉ après l'indicatif (« 0692… » → « +262692… ») : le zéro initial est
#: le préfixe national, pas un chiffre du numéro.
INDICATIFS_OUTRE_MER = {
    "0590": "590", "0690": "590", "0691": "590",   # Guadeloupe, Saint-Martin, Saint-Barthélemy
    "0596": "596", "0696": "596", "0697": "596",   # Martinique
    "0594": "594", "0694": "594",                  # Guyane
    "0262": "262", "0692": "262", "0693": "262",   # La Réunion
    "0269": "262", "0639": "262",                  # Mayotte
}
INDICATIF_DEFAUT = "33"

#: Longueurs admises pour la partie chiffrée d'un E.164 (recommandation UIT : 15 au plus).
LONGUEUR_MIN, LONGUEUR_MAX = 8, 15

_NON_CHIFFRE = re.compile(r"[^0-9+]")
_E164 = re.compile(r"^\+[1-9][0-9]{%d,%d}$" % (LONGUEUR_MIN - 1, LONGUEUR_MAX - 1))


def est_canonique(numero):
    """Vrai si ce numéro est déjà en E.164 (`+` suivi de 8 à 15 chiffres)."""
    return bool(numero) and bool(_E164.match(numero.strip()))


def normaliser(numero, indicatif_defaut=INDICATIF_DEFAUT):
    """Rend le numéro en E.164, ou `None` si rien d'exploitable n'en ressort.

    `indicatif_defaut` ne sert qu'aux saisies locales sans indicatif, et seulement quand le
    préfixe n'est pas celui d'un territoire d'outre-mer — qui a le sien.
    """
    if not numero:
        return None
    brut = _NON_CHIFFRE.sub("", str(numero))
    if not brut:
        return None

    if brut.startswith("+"):
        chiffres = brut[1:]
    elif brut.startswith("00"):
        chiffres = brut[2:]
    elif brut.startswith("0") and len(brut) == 10:
        chiffres = INDICATIFS_OUTRE_MER.get(brut[:4], indicatif_defaut) + brut[1:]
    elif brut.startswith("0"):
        # Dix chiffres est la seule longueur nationale française interprétable sans risque.
        # Un « 0 » suivi d'autre chose est une saisie incomplète ou étrangère : on ne devine pas.
        return None
    else:
        chiffres = brut

    if not chiffres.isdigit() or not LONGUEUR_MIN <= len(chiffres) <= LONGUEUR_MAX:
        return None
    if chiffres.startswith("0"):
        return None
    return "+" + chiffres


def pour_fournisseur(numero, avec_plus=False):
    """Le numéro tel que l'API d'un fournisseur l'attend.

    Brevo veut les chiffres seuls ; d'autres exigent le « + ». La différence se règle ici,
    une fois, plutôt que dans chaque adaptateur."""
    canonique = normaliser(numero)
    if canonique is None:
        return None
    return canonique if avec_plus else canonique[1:]


def afficher(numero):
    """Écriture lisible : « 06 12 34 56 78 » en France, l'E.164 tel quel ailleurs.

    Un numéro stocké en E.164 ne se lit pas à l'œil sur une fiche imprimée à 3 h du matin —
    c'est l'unique raison d'être de cette fonction. Elle n'est jamais utilisée pour envoyer."""
    canonique = normaliser(numero)
    if canonique is None:
        return numero or ""
    chiffres = canonique[1:]
    for prefixe, indicatif in (("33", "33"), *((v, v) for v in sorted(set(
            INDICATIFS_OUTRE_MER.values()), key=len, reverse=True))):
        if chiffres.startswith(indicatif):
            national = "0" + chiffres[len(indicatif):]
            if len(national) == 10:
                return " ".join(national[i:i + 2] for i in range(0, 10, 2))
            break
    return canonique
