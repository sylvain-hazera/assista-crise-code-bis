"""Points d'entrée de la connexion en étapes et du second facteur (15/11/2026).

    POST /api/connexion/debut/   {email}                 → {etape: "code" | "mot_de_passe"}
    POST /api/connexion/code/    {email, code, appareil} → {jeton_etape}
    POST /api/connexion/envoyer-code/  {email}           renvoie le code des comptes en mode e-mail
    POST /api/token/             {email, password, jeton_etape, appareil}   (core/serializers.py)

    GET  /api/second-facteur/                  où en est mon compte
    POST /api/second-facteur/preparer/         {mode: application | email} (pas encore actif)
    POST /api/second-facteur/envoyer-code/     envoie un code par e-mail (mode e-mail)
    POST /api/second-facteur/confirmer/        l'active, rend les codes de secours
    POST /api/second-facteur/retirer/          le retire (demande un code)
    POST /api/second-facteur/codes-secours/    en tire de nouveaux (demande un code)

La logique est dans `core/connexion.py`, `core/second_facteur.py` et `core/frein_connexion.py` ;
ces vues ne font que lire la requête et tracer.
"""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import connexion, second_facteur
from . import frein_connexion as frein
from .audit import audit_log


class ConnexionDebutView(APIView):
    """Étape 1. Ne dit jamais si l'adresse est inscrite."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        if not email:
            return Response({"detail": "L'adresse e-mail est requise."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"etape": connexion.etape_apres_adresse(
            email, request, str(request.data.get("appareil") or ""))})


class ConnexionEnvoyerCodeView(APIView):
    """« Renvoyer le code par e-mail ». Même réponse pour toute adresse : elle ne dit ni si le
    compte existe, ni comment il est protégé, ni si un message est réellement parti."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        connexion.renvoyer_code((request.data.get("email") or "").strip(), request,
                                str(request.data.get("appareil") or ""))
        return Response({"detail": "Si votre compte reçoit ses codes par e-mail, un nouveau code "
                                   "vient de partir. Il est valable 5 minutes."})


class ConnexionCodeView(APIView):
    """Étape 2 des comptes protégés : le code, avant tout mot de passe."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get_authenticate_header(self, request):
        # Sans cet en-tête, DRF transforme le 401 d'un code faux en 403 (« interdit »), ce qui
        # dirait autre chose que « réessayez ». Même réglage que la vue des jetons.
        return 'Bearer realm="api"'

    def post(self, request):
        jeton = connexion.verifier_code_de_connexion(
            (request.data.get("email") or "").strip(),
            str(request.data.get("code") or ""),
            str(request.data.get("appareil") or ""),
        )
        return Response({"jeton_etape": jeton})


def _etat_public(utilisateur) -> dict:
    etat = second_facteur.etat(utilisateur)
    return {**etat, "date_limite": etat["date_limite"].isoformat() if etat["date_limite"] else None}


class _VueSecondFacteur(APIView):
    """Identifie le titulaire : par sa session, ou par le jeton d'activation remis à qui a
    prouvé son identité mais n'a pas le droit d'ouvrir de session avant d'avoir activé."""
    permission_classes = [permissions.AllowAny]

    def titulaire(self, request):
        """`(utilisateur, par_jeton)`, ou `(None, False)`."""
        if request.user and request.user.is_authenticated:
            return request.user, False
        utilisateur = connexion.utilisateur_a_enroler(str(request.data.get("jeton_enrolement") or ""))
        return utilisateur, utilisateur is not None

    def refus(self):
        return Response({"detail": "Session expirée. Reconnectez-vous."},
                        status=status.HTTP_401_UNAUTHORIZED)

    def indisponible(self):
        return Response({"detail": "Indisponible sur cette machine."},
                        status=status.HTTP_404_NOT_FOUND)


class SecondFacteurEtatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(_etat_public(request.user))


class SecondFacteurPreparerView(_VueSecondFacteur):
    def post(self, request):
        if not second_facteur.applicable():
            return self.indisponible()
        utilisateur, par_jeton = self.titulaire(request)
        if utilisateur is None:
            return self.refus()

        # Depuis une session ouverte, le mot de passe est redemandé : sinon un poste laissé
        # ouvert suffirait à poser SON second facteur sur le compte d'un autre, et à l'en
        # chasser. Un compte sans mot de passe (créé par import, connecté par lien) n'en a
        # aucun à donner ; le jeton d'activation, lui, vient d'une preuve d'identité fraîche.
        if not par_jeton and utilisateur.has_usable_password():
            compteur = frein.cle(frein.ETAPE_MOT_DE_PASSE, utilisateur.email, voie="session")
            connexion.exiger_libre(compteur)
            if not utilisateur.check_password(str(request.data.get("mot_de_passe") or "")):
                frein.echec(compteur)
                return Response({"detail": "Mot de passe incorrect."},
                                status=status.HTTP_400_BAD_REQUEST)
            frein.reussite(compteur)

        mode = "email" if request.data.get("mode") == "email" else "application"
        try:
            return Response(second_facteur.preparer(utilisateur, mode, request))
        except second_facteur.ModeImpossible as erreur:
            return Response({"detail": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as erreur:
            return Response({"detail": str(erreur)}, status=status.HTTP_409_CONFLICT)


class SecondFacteurConfirmerView(_VueSecondFacteur):
    def post(self, request):
        if not second_facteur.applicable():
            return self.indisponible()
        utilisateur, par_jeton = self.titulaire(request)
        if utilisateur is None:
            return self.refus()

        compteur = frein.cle(frein.ETAPE_CODE, utilisateur.email, voie="activation")
        connexion.exiger_libre(compteur)
        codes = second_facteur.confirmer(utilisateur, str(request.data.get("code") or ""))
        if codes is None:
            frein.echec(compteur)
            return Response(
                {"detail": "Code incorrect. Vérifiez l'heure de votre téléphone et réessayez."},
                status=status.HTTP_400_BAD_REQUEST)
        frein.reussite(compteur)
        audit_log(request=request, action_code="MODIFICATION", objet_type="User",
                  objet_id=utilisateur.id,
                  commentaire="Second facteur de connexion activé par son titulaire.")

        reponse = {"codes_secours": codes, "etat": _etat_public(utilisateur)}
        if par_jeton:
            # La personne s'est identifiée juste avant et n'attendait que cela : sa session
            # s'ouvre, sans lui faire tout recommencer.
            reponse["session"] = connexion.ouvrir_session(
                request, utilisateur, str(request.data.get("appareil") or ""))
        return Response(reponse)


class SecondFacteurEnvoyerCodeView(_VueSecondFacteur):
    """Envoie un code par e-mail au titulaire, quand son compte fonctionne ainsi : pendant
    l'activation (« je n'ai rien reçu »), ou avant de retirer ou de renouveler, qui demandent
    un code."""

    def post(self, request):
        utilisateur, _ = self.titulaire(request)
        if utilisateur is None:
            return self.refus()
        parti = second_facteur.envoyer_code_par_mail(request, utilisateur)
        return Response({
            "envoye": parti,
            "detail": ("Un code vient de partir vers votre adresse. Il est valable 5 minutes."
                       if parti else "Un code vous a déjà été envoyé. Attendez une minute "
                                     "avant d'en demander un autre."),
        })


class SecondFacteurRetirerView(APIView):
    """Changer de téléphone : on retire, puis on réactive. Demande un code valide (ou un code
    de secours) — sans quoi une session volée suffirait à ôter la protection."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        compteur = frein.cle(frein.ETAPE_CODE, request.user.email, voie="session")
        connexion.exiger_libre(compteur)
        if not second_facteur.verifier_code(request.user, str(request.data.get("code") or "")):
            frein.echec(compteur)
            return Response({"detail": "Code incorrect."}, status=status.HTTP_400_BAD_REQUEST)
        frein.reussite(compteur)
        second_facteur.retirer(request.user, exiger_tout_de_suite=True)
        audit_log(request=request, action_code="MODIFICATION", objet_type="User",
                  objet_id=request.user.id,
                  commentaire="Second facteur de connexion retiré par son titulaire.")
        return Response({"etat": _etat_public(request.user)})


class SecondFacteurCodesSecoursView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        compteur = frein.cle(frein.ETAPE_CODE, request.user.email, voie="session")
        connexion.exiger_libre(compteur)
        if not second_facteur.verifier_code(request.user, str(request.data.get("code") or "")):
            frein.echec(compteur)
            return Response({"detail": "Code incorrect."}, status=status.HTTP_400_BAD_REQUEST)
        frein.reussite(compteur)
        codes = second_facteur.renouveler_codes_secours(request.user)
        audit_log(request=request, action_code="MODIFICATION", objet_type="User",
                  objet_id=request.user.id,
                  commentaire="Codes de secours du second facteur renouvelés par leur titulaire.")
        return Response({"codes_secours": codes, "etat": _etat_public(request.user)})
