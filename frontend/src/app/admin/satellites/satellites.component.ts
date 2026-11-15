import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { SatelliteService } from '../../services/satellite.service';
import { AuthService } from '../../auth/services/auth.service';
import {
  Satellite, JetonEnrolementSatellite, IdentifiantsCompteServiceSatellite, MiseAJourSatellite,
  VersionASigner, VersionSatellite,
} from '../../shared/models/satellite.model';
import { UserRole } from '../../shared/models/user.model';

/** Boîtiers Raspberry Pi déployés sur site (pont MeshCore/Meshtastic local, et pour le profil
 * Full une instance assista-crise complète utilisable même sans internet) — voir le cadrage
 * "Chantier B". Enrôlement en 3 temps : on génère ici un jeton à usage unique pour SON
 * institution, communiqué hors-bande au responsable du satellite lors de l'installation ; le
 * satellite le consomme lui-même pour apparaître ci-dessous en attente ; on valide alors pour
 * lui créer un compte de service — les identifiants ne sont affichés qu'à cet instant précis,
 * une seule fois, jamais relisibles ensuite (voir SatelliteService.valider). */
import { NavigateurInsuffisant, PhraseIncorrecte, signerVersion } from '../../services/signature-satellite';

@Component({
  selector: 'app-satellites',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './satellites.component.html',
  styleUrl: './satellites.component.scss',
})
export class SatellitesComponent implements OnInit {

  satellites: Satellite[] = [];
  loading = true;
  errorMessage = '';

  isDemo = false;

  genererJetonEnCours = false;
  dernierJeton: JetonEnrolementSatellite | null = null;
  /** `WINDOWS` : passerelle radio sur un PC Windows (application à lancer, 15/11/2026). Côté
   * serveur c'est un satellite de profil GW comme un autre ; seule l'installation diffère. */
  profilJeton: 'GW' | 'FULL' | 'WINDOWS' = 'GW';
  /** La cible choisie au moment où le jeton affiché a été généré. */
  jetonPourWindows = false;
  messageSucces = '';
  /** Dépôt public cloné sur le satellite (voir satellite/README.md). */
  readonly depot = 'https://github.com/sylvain-hazera/assista-crise-code-bis.git';

  /** Commandes complètes à lancer sur la machine du satellite -- installation en une commande,
   * sans question (installer.sh installer, 20/10/2026). */
  get commandesInstallation(): string {
    if (!this.dernierJeton) return '';
    return [
      `git clone ${this.depot}`,
      'cd assista-crise-code-bis/satellite',
      `./installer.sh installer ${this.dernierJeton.jeton}`,
    ].join('\n');
  }

  /**
   * Le petit fichier à double-cliquer sur le PC Windows. Il ne contient que l'adresse de ce
   * site et le code d'installation : il télécharge le véritable installeur
   * (`/passerelle/installer.ps1`, servi par ce site) et le lance. Rien à saisir sur le poste.
   *
   * Le code est à usage unique et expire en 24 h : ce fichier ne vaut plus rien ensuite.
   * Jeton en `token_urlsafe` (lettres, chiffres, `-`, `_`) : aucun caractère à échapper.
   */
  get installeurWindows(): string {
    if (!this.dernierJeton) return '';
    const site = window.location.origin;
    const commande = [
      "$ProgressPreference='SilentlyContinue'",
      "[Net.ServicePointManager]::SecurityProtocol='Tls12'",
      "$s=Join-Path $env:TEMP 'assista-crise-passerelle.ps1'",
      `Invoke-WebRequest -UseBasicParsing '${site}/passerelle/installer.ps1' -OutFile $s`,
      `& $s -Central '${site}' -Jeton '${this.dernierJeton.jeton}'`,
    ].join('; ');
    return [
      '@echo off',
      'title Installation de la passerelle Assista-Crise',
      'echo Installation de la passerelle Assista-Crise. Merci de patienter, cela prend quelques minutes...',
      `powershell -NoProfile -ExecutionPolicy Bypass -Command "${commande}"`,
      'if errorlevel 1 pause',
      '',
    ].join('\r\n');
  }

  telechargerInstalleurWindows(): void {
    const lien = document.createElement('a');
    lien.href = URL.createObjectURL(new Blob([this.installeurWindows], { type: 'application/octet-stream' }));
    lien.download = 'Installer la passerelle Assista-Crise.bat';
    lien.click();
    URL.revokeObjectURL(lien.href);
  }

  // Identifiants d'un compte de service, affichés une seule fois juste après validation — voir
  // SatelliteService.valider. Effacés dès qu'on quitte la page ou qu'on en valide un autre.
  identifiantsAffiches: { satelliteNom: string; identifiants: IdentifiantsCompteServiceSatellite } | null = null;

  actionEnCours: string | null = null;

  // ── Mises à jour ordonnées d'ici (14/11/2026) ────────────────────────────
  /** Versions signées. La première non retirée est la référence : c'est vers elle qu'un
   * satellite est mis à jour, et par rapport à elle qu'il est « à jour » ou « en retard ». */
  versions: VersionSatellite[] = [];
  /** Faux = le serveur n'a aucune clé publique : rien ne peut être publié. */
  cleConfiguree = true;
  estAdministrateur = false;
  /** Saisie de publication : TOUT ce qu'affiche `scripts/satellites/signer-version.sh`, collé
   * d'un bloc. La page y retrouve le numéro et la signature : deux champs à remplir
   * séparément se sont révélés impraticables au téléphone (15/11/2026) — un espace collé
   * avant le numéro suffisait à le tronquer, et le bouton restait grisé sans explication. */
  nouvelleVersion = { colle: '', libelle: '' };
  publicationEnCours = false;
  /** Satellite dont on regarde l'historique, et cet historique. */
  historiqueDe: Satellite | null = null;
  historique: MiseAJourSatellite[] = [];

  constructor(
    private service: SatelliteService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.isDemo = this.authService.getEnvironment() === 'DEMO';
    this.estAdministrateur = this.authService.getCurrentUser()?.type === UserRole.ADMIN;
    this.load();
    this.chargerVersions();
    this.chargerVersionASigner();
  }

  chargerVersions(): void {
    this.service.versions().subscribe({
      next: (reponse) => { this.versions = reponse.versions; this.cleConfiguree = reponse.cle_configuree; },
      error: () => undefined,
    });
  }

  /** La version vers laquelle on met à jour : la dernière publiée et non retirée. */
  get versionDeReference(): VersionSatellite | null {
    return this.versions.find(v => !v.retiree) ?? null;
  }

  court(commit: string | null | undefined): string {
    return (commit || '').slice(0, 10);
  }

  versionLabel(satellite: Satellite): string {
    if (satellite.etat_version === 'A_JOUR') return 'À jour';
    if (satellite.etat_version === 'EN_RETARD') return 'En retard';
    if (satellite.etat_version === 'INCONNUE') return 'Version inconnue';
    return '';
  }

  versionClass(satellite: Satellite): string {
    if (satellite.etat_version === 'A_JOUR') return 'statut-ok';
    if (satellite.etat_version === 'EN_RETARD') return 'statut-attention';
    return 'statut-inconnu';
  }

  /** Un ordre est ouvert : demandé, ou en cours sur le satellite. */
  miseAJourOuverte(satellite: Satellite): boolean {
    return ['DEMANDEE', 'EN_COURS'].includes(satellite.mise_a_jour?.statut ?? '');
  }

  /** Le bouton n'apparaît que là où l'ordre serait accepté : le serveur refuserait le reste,
   * et un bouton qui échoue à tous les coups n'apprend rien. */
  peutMettreAJour(satellite: Satellite): boolean {
    return !this.isDemo && satellite.statut_enrolement === 'APPROUVE'
      && satellite.agent_present && !!this.versionDeReference
      && satellite.etat_version !== 'A_JOUR' && !this.miseAJourOuverte(satellite);
  }

  /** Pourquoi le bouton n'est pas là, quand ce n'est pas évident. */
  raisonSansMiseAJour(satellite: Satellite): string {
    if (satellite.statut_enrolement !== 'APPROUVE' || !this.versionDeReference
        || satellite.etat_version === 'A_JOUR' || this.miseAJourOuverte(satellite)) {
      return '';
    }
    if (!satellite.agent_present) {
      return "Pas d'agent de mise à jour : sur place, une dernière fois, ./installer.sh mettre-a-jour";
    }
    return '';
  }

  mettreAJour(satellite: Satellite, malgreCrise = false): void {
    const version = this.versionDeReference;
    if (!version) return;
    if (!malgreCrise && !confirm(
      `Mettre à jour « ${satellite.nom} » vers la version ${this.court(version.commit)} ?\n\n`
      + "Le satellite reconstruit puis redémarre : s'il sert un site local, celui-ci est "
      + "indisponible pendant ce temps. L'ordre part à son prochain contact.")) {
      return;
    }
    this.actionEnCours = satellite.id;
    this.errorMessage = '';
    this.messageSucces = '';
    this.service.mettreAJour(satellite.id, malgreCrise).subscribe({
      next: (maj) => {
        this.actionEnCours = null;
        this.remplacer(maj);
        this.messageSucces = `Mise à jour de « ${satellite.nom} » demandée : il la prendra à son prochain contact (deux minutes environ).`;
      },
      error: (err) => {
        this.actionEnCours = null;
        // Une crise est en cours : le serveur refuse tant qu'on ne l'a pas dit en toutes
        // lettres. On nomme les crises — c'est ce qui permet de décider.
        if (err.status === 409 && err.error?.code === 'CRISE_EN_COURS' && !malgreCrise) {
          const crises = (err.error.crises as string[] | undefined)?.join(', ') ?? '';
          if (confirm(`Une crise est en cours pour cette institution (${crises}).\n\n`
              + 'La mise à jour rend le satellite indisponible le temps de reconstruire. '
              + 'La lancer quand même ?')) {
            this.mettreAJour(satellite, true);
          }
          return;
        }
        this.errorMessage = err.error?.error || 'Impossible de demander la mise à jour.';
      },
    });
  }

  annulerMiseAJour(satellite: Satellite): void {
    this.actionEnCours = satellite.id;
    this.errorMessage = '';
    this.service.annulerMiseAJour(satellite.id).subscribe({
      next: (maj) => { this.actionEnCours = null; this.remplacer(maj); },
      error: (err) => {
        this.actionEnCours = null;
        this.errorMessage = err.error?.error || "Impossible d'annuler.";
        this.load();
      },
    });
  }

  private remplacer(maj: Satellite): void {
    this.satellites = this.satellites.map(s => (s.id === maj.id ? maj : s));
  }

  voirHistorique(satellite: Satellite): void {
    if (this.historiqueDe?.id === satellite.id) { this.historiqueDe = null; return; }
    this.historiqueDe = satellite;
    this.historique = [];
    this.service.misesAJour(satellite.id).subscribe({
      next: (liste) => this.historique = liste,
      error: () => this.errorMessage = "Impossible de charger l'historique des mises à jour.",
    });
  }

  miseAJourClass(maj: MiseAJourSatellite): string {
    if (maj.statut === 'REUSSIE') return 'statut-ok';
    if (maj.statut === 'ECHOUEE') return 'statut-erreur';
    if (maj.statut === 'DEMANDEE' || maj.statut === 'EN_COURS') return 'statut-attention';
    return 'statut-inconnu';
  }

  // ══ Signer la dernière version depuis la page ═══════════════════════════════════════════
  //
  // Demande du 15/11/2026 : « que je n'aie que la phrase de passe à rentrer dans la page ».
  // La signature se fait ICI, dans le navigateur (services/signature-satellite.ts) : la phrase
  // de passe n'est jamais envoyée, seuls le numéro de version et sa signature le sont.

  aSigner: VersionASigner | null = null;
  phraseDePasse = '';
  libelleASigner = '';
  signatureEnCours = false;
  erreurSignature = '';
  /** Le collage du résultat de `signer-version.sh` reste possible, replié par défaut. */
  collageOuvert = false;

  chargerVersionASigner(): void {
    if (!this.estAdministrateur || this.isDemo) return;
    this.service.versionASigner().subscribe({
      next: (aSigner) => {
        this.aSigner = aSigner;
        this.libelleASigner = aSigner.version?.titre ?? '';
      },
      error: () => { this.aSigner = null; },
    });
  }

  get peutSigner(): boolean {
    return !!this.aSigner?.version && !!this.aSigner.cle && !this.aSigner.deja_publiee
      && this.phraseDePasse.length > 0 && !this.signatureEnCours;
  }

  async signerEtPublier(): Promise<void> {
    const version = this.aSigner?.version;
    const cle = this.aSigner?.cle;
    if (!version || !cle || !this.peutSigner) return;
    this.signatureEnCours = true;
    this.erreurSignature = '';
    this.messageSucces = '';
    let signature: string;
    try {
      signature = await signerVersion(cle, this.phraseDePasse, version.commit);
    } catch (erreur) {
      this.signatureEnCours = false;
      this.erreurSignature = erreur instanceof PhraseIncorrecte || erreur instanceof NavigateurInsuffisant
        ? erreur.message : 'La signature a échoué dans ce navigateur.';
      return;
    } finally {
      // La phrase ne reste pas dans la page plus longtemps que la signature.
      this.phraseDePasse = '';
    }
    this.service.publierVersion(version.commit, signature, this.libelleASigner.trim()).subscribe({
      next: () => {
        this.signatureEnCours = false;
        this.messageSucces = `Version ${this.court(version.commit)} signée et publiée.`;
        this.chargerVersions();
        this.chargerVersionASigner();
        this.load();
      },
      error: (err) => {
        this.signatureEnCours = false;
        this.erreurSignature = err.error?.error || 'Publication refusée par le serveur.';
      },
    });
  }

  private static readonly BLOC_SIGNATURE =
    /-----BEGIN SSH SIGNATURE-----[\s\S]*?-----END SSH SIGNATURE-----/;

  /** Le bloc de signature retrouvé dans ce qui a été collé, ou null. Les retours à la ligne
   * ajoutés par un terminal étroit sont laissés tels quels : le serveur les ignore. */
  get signatureReconnue(): string | null {
    return this.nouvelleVersion.colle.match(SatellitesComponent.BLOC_SIGNATURE)?.[0] ?? null;
  }

  /** Vrai si une signature a été commencée mais que sa fin manque (collage tronqué). */
  get signatureTronquee(): boolean {
    return !this.signatureReconnue && this.nouvelleVersion.colle.includes('BEGIN SSH SIGNATURE');
  }

  /** Le numéro de version (40 caractères hexadécimaux) retrouvé hors de la signature, ou
   * null. Un numéro coupé en deux lignes par un terminal étroit est recollé. */
  get commitReconnu(): string | null {
    const hors = this.nouvelleVersion.colle
      .replace(SatellitesComponent.BLOC_SIGNATURE, '\n')
      .replace(/-----BEGIN SSH SIGNATURE-----[\s\S]*$/, '\n')
      .toLowerCase();
    const entier = hors.match(/(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])/);
    if (entier) return entier[0];
    let suite = '';
    for (const ligne of hors.split('\n').map(l => l.trim())) {
      if (/^[0-9a-f]+$/.test(ligne)) {
        suite += ligne;
        if (suite.length === 40) return suite;
        if (suite.length > 40) suite = '';
      } else {
        suite = '';
      }
    }
    return null;
  }

  get peutPublier(): boolean {
    return !!this.commitReconnu && !!this.signatureReconnue;
  }

  publierVersion(): void {
    if (!this.peutPublier) return;
    this.publicationEnCours = true;
    this.errorMessage = '';
    this.service.publierVersion(
      this.commitReconnu!, this.signatureReconnue!, this.nouvelleVersion.libelle.trim(),
    ).subscribe({
      next: () => {
        this.publicationEnCours = false;
        this.nouvelleVersion = { colle: '', libelle: '' };
        this.messageSucces = 'Version publiée : signature vérifiée.';
        this.chargerVersions();
        this.load();
      },
      error: (err) => {
        this.publicationEnCours = false;
        this.errorMessage = err.error?.error || 'Publication refusée.';
      },
    });
  }

  retirerVersion(version: VersionSatellite): void {
    if (!confirm(`Retirer la version ${this.court(version.commit)} ? Elle ne sera plus proposée, et les mises à jour demandées vers elle mais pas encore commencées seront annulées.`)) return;
    this.service.retirerVersion(version.id).subscribe({
      next: () => { this.chargerVersions(); this.load(); },
      error: (err) => this.errorMessage = err.error?.error || 'Retrait impossible.',
    });
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.getAll().subscribe({
      next: (data) => { this.satellites = data; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les satellites.'; this.loading = false; },
    });
  }

  genererJeton(): void {
    this.genererJetonEnCours = true;
    this.errorMessage = '';
    const pourWindows = this.profilJeton === 'WINDOWS';
    this.service.genererJeton(pourWindows ? 'GW' : this.profilJeton as 'GW' | 'FULL').subscribe({
      next: (jeton) => {
        this.dernierJeton = jeton;
        this.jetonPourWindows = pourWindows;
        this.genererJetonEnCours = false;
      },
      error: (err) => {
        this.errorMessage = err.error?.error || "Impossible de générer un jeton d'enrôlement.";
        this.genererJetonEnCours = false;
      },
    });
  }

  valider(satellite: Satellite): void {
    this.actionEnCours = satellite.id;
    this.errorMessage = '';
    this.identifiantsAffiches = null;
    this.messageSucces = '';
    this.service.valider(satellite.id).subscribe({
      next: (resultat) => {
        this.actionEnCours = null;
        if (resultat.recuperation_automatique || !resultat.identifiants_compte_service) {
          // Installeur récent : le satellite récupère seul ses identifiants, rien à recopier.
          this.messageSucces = `Satellite « ${satellite.nom} » validé : il récupère ses identifiants et démarre tout seul (environ une minute).`;
        } else {
          this.identifiantsAffiches = { satelliteNom: satellite.nom, identifiants: resultat.identifiants_compte_service };
        }
        this.load();
      },
      error: (err) => {
        this.actionEnCours = null;
        this.errorMessage = err.error?.error || 'Impossible de valider ce satellite.';
      },
    });
  }

  regenererIdentifiants(satellite: Satellite): void {
    if (!confirm(`Générer de nouveaux identifiants pour « ${satellite.nom} » ? Les actuels cesseront aussitôt de fonctionner : il faudra reporter les nouveaux dans la configuration du satellite.`)) return;
    this.actionEnCours = satellite.id;
    this.errorMessage = '';
    this.service.regenererIdentifiants(satellite.id).subscribe({
      next: (resultat) => {
        this.actionEnCours = null;
        this.identifiantsAffiches = { satelliteNom: satellite.nom, identifiants: resultat.identifiants_compte_service };
      },
      error: (err) => {
        this.actionEnCours = null;
        this.errorMessage = err.error?.error || 'Impossible de régénérer les identifiants.';
      },
    });
  }

  revoquer(satellite: Satellite): void {
    if (!confirm(`Révoquer le satellite « ${satellite.nom} » ? Son compte de service sera immédiatement désactivé.`)) return;
    this.actionEnCours = satellite.id;
    this.errorMessage = '';
    this.service.revoquer(satellite.id).subscribe({
      next: () => { this.actionEnCours = null; this.load(); },
      error: (err) => {
        this.actionEnCours = null;
        this.errorMessage = err.error?.error || 'Impossible de révoquer ce satellite.';
      },
    });
  }

  fermerIdentifiants(): void {
    this.identifiantsAffiches = null;
  }

  copier(texte: string): void {
    navigator.clipboard?.writeText(texte).catch(() => {});
  }

  etatClass(satellite: Satellite): string {
    if (satellite.etat === 'ACTIF') return 'statut-ok';
    if (satellite.etat === 'PERDU') return 'statut-erreur';
    if (satellite.etat === 'INACTIF') return 'statut-attention';
    return 'statut-inconnu';
  }

  etatLabel(satellite: Satellite): string {
    if (satellite.etat === 'ACTIF') return 'Actif';
    if (satellite.etat === 'INACTIF') return 'Inactif';
    if (satellite.etat === 'PERDU') return 'Perdu';
    return 'Jamais contacté';
  }
}
