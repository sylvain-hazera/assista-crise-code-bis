/** Identifiants d'envoi d'une institution en marque blanche (email Brevo, SMS).
 *
 * Servi par `/api/institutions/<id>/configuration-envoi/`, réservé au bureau de l'institution.
 *
 * **Les clés ne sont jamais rendues par l'API** — ni en entier, ni en fragment. On ne lit que
 * `*_cle_api_renseignee`. Une clé perdue se régénère chez le fournisseur, ce qui est plus sûr
 * que de pouvoir la relire depuis l'application. */
export interface ConfigurationEnvoi {
  id: string;
  institution: string;

  brevo_actif: boolean;
  /** Présence seulement. La valeur n'est jamais servie. */
  brevo_cle_api_renseignee: boolean;
  /** Doit être un expéditeur VÉRIFIÉ dans le compte Brevo, sinon l'API refuse les envois. */
  brevo_expediteur_email: string;
  brevo_expediteur_nom: string;

  fournisseur_sms: string;
  sms_cle_api_renseignee: boolean;
  sms_expediteur: string;

  /** Actif + clé + adresse : les trois, parce qu'un seul manquant produit un refus. */
  email_configure: boolean;
  sms_configure: boolean;

  /** Le seul endroit où l'on voit qu'une clé a été révoquée : sans cette trace, le problème
   * n'apparaît que quand un destinataire signale n'avoir rien reçu. */
  dernier_envoi_email_le: string | null;
  derniere_erreur_email: string;
  dernier_envoi_sms_le: string | null;
  derniere_erreur_sms: string;
  date_modification: string;
}

/** Ce qu'on envoie pour modifier. Une clé absente est inchangée ; une chaîne vide l'effface. */
export interface ConfigurationEnvoiPatch {
  brevo_actif?: boolean;
  brevo_cle_api?: string;
  brevo_expediteur_email?: string;
  brevo_expediteur_nom?: string;
  fournisseur_sms?: string;
  sms_cle_api?: string;
  sms_expediteur?: string;
}
