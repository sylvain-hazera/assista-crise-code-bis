"""Met les numéros déjà enregistrés au format E.164 (voir core/telephone.py).

Les nouveaux numéros sont normalisés à l'enregistrement (User.save,
InterlocuteurAlertePCS.save). Ceux déjà en base, eux, ont été saisis « 06 12 34 56 78 » — ils
fonctionnent encore, puisque la conversion à l'envoi sait les lire, mais ils ne disent pas de
quel pays ils sont et ne traverseront pas un futur fournisseur plus strict.

**À blanc par défaut.** Ces champs sont chiffrés : une réécriture en masse touche des données
qu'on ne peut pas relire par un `SELECT` pour vérifier après coup. On affiche donc ce qui
changerait, et `--appliquer` seul écrit.

**Ce qui n'est pas reconnu n'est pas touché**, et c'est compté à part : un numéro illisible est
peut-être une note (« voir standard »), et l'écraser ferait perdre le seul moyen de joindre
quelqu'un.
"""
from django.core.management.base import BaseCommand

from core.telephone import est_canonique, normaliser


class Command(BaseCommand):
    help = "Normalise en E.164 les numéros de téléphone déjà enregistrés."

    def add_arguments(self, parser):
        parser.add_argument(
            "--appliquer", action="store_true",
            help="Écrit réellement. Sans cette option, rien n'est modifié.")

    def handle(self, *args, **options):
        from core.models import InterlocuteurAlertePCS, User

        appliquer = options["appliquer"]
        total = {"convertis": 0, "deja": 0, "illisibles": 0}

        for modele, champ in ((User, "phone_number"),
                              (InterlocuteurAlertePCS, "telephone")):
            nom = modele.__name__
            convertis = deja = illisibles = 0
            # Les champs sont chiffrés : impossible de filtrer en SQL, on relit tout. Les
            # volumes concernés (comptes, interlocuteurs PCS) le permettent largement.
            for objet in modele.objects.exclude(**{champ: None}).iterator():
                valeur = getattr(objet, champ)
                if not valeur:
                    continue
                if est_canonique(valeur):
                    deja += 1
                    continue
                canonique = normaliser(valeur)
                if canonique is None:
                    illisibles += 1
                    self.stdout.write(f"  ? {nom} {objet.pk} : « {valeur} » non reconnu, laissé tel quel")
                    continue
                convertis += 1
                if appliquer:
                    setattr(objet, champ, canonique)
                    objet.save(update_fields=[champ])

            self.stdout.write(
                f"{nom}.{champ} : {convertis} à convertir, {deja} déjà au format, "
                f"{illisibles} non reconnu(s)")
            total["convertis"] += convertis
            total["deja"] += deja
            total["illisibles"] += illisibles

        if appliquer:
            self.stdout.write(self.style.SUCCESS(
                f"{total['convertis']} numéro(s) normalisé(s)."))
        else:
            self.stdout.write(self.style.WARNING(
                f"Essai à blanc : {total['convertis']} numéro(s) seraient normalisés. "
                "Relancer avec --appliquer pour écrire."))
