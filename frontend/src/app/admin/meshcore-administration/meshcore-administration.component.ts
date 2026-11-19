import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { AdministrationMeshCoreService } from '../../services/administration-meshcore.service';
import { RattachementNoeudRadioService } from '../../services/rattachement-noeud-radio.service';
import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { AuthService } from '../../auth/services/auth.service';
import {
  OperationMeshCore, TacheAdminMeshCore, TypeTacheAdminMeshCore,
} from '../../shared/models/administration-meshcore.model';
import { RattachementNoeudRadio } from '../../shared/models/rattachement-noeud-radio.model';
import { CompagnonMeshCore } from '../../shared/models/compagnon-meshcore.model';

/** Administration à distance des répéteurs MeshCore.
 *
 * Trois gestes, dans l'ordre où ils se font : **réclamer** un répéteur (en disant par quoi on
 * l'administre), **prouver** qu'on le contrôle, puis **opérer**.
 *
 * Ce que cette page doit dire sans détour, parce que c'est ce qui la distingue de son
 * équivalent Meshtastic :
 *
 * - **il n'y a aucun filet côté firmware.** Sur Meshtastic, une tentative non autorisée se
 *   heurte à `security.admin_key` et l'appareil refuse. Ici, qui a le mot de passe écrit — d'où
 *   la preuve exigée avant toute écriture ;
 * - **mais le firmware interdit lui-même à distance** ce qui pourrait rendre un répéteur
 *   injoignable (`erase`, `set freq`, `set prv.key`). Le risque d'une écriture est donc plus
 *   faible qu'il n'y paraît ;
 * - **et `RADIO_TEMPORAIRE` rend un essai radio réversible** : ses paramètres reviennent seuls
 *   au bout du délai. C'est la voie à prendre pour tout ce qui touche la radio. */
@Component({
  selector: 'app-meshcore-administration',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './meshcore-administration.component.html',
  styleUrl: './meshcore-administration.component.scss',
})
export class MeshcoreAdministrationComponent implements OnInit {

  /** Opérations proposées, de la plus anodine à la plus engageante. L'aide dit ce que ça coûte
   * si on se trompe — c'est la seule information qui compte au moment de cliquer. */
  readonly operations: OperationMeshCore[] = [
    { type: 'LIRE_STATUT', libelle: 'Lire le statut', ecriture: false,
      aide: "Sans effet sur le répéteur. C'est l'opération à essayer en premier : elle dit si la chaîne fonctionne." },
    { type: 'LIRE_VOISINS', libelle: 'Lire les voisins entendus', ecriture: false,
      aide: "Qui ce répéteur entend. Les voisins sont identifiés par un préfixe de clé de 4 octets, et la liste est paginée : une absence n'est pas une preuve d'absence." },
    { type: 'LIRE_REGIONS', libelle: 'Lire les portées déclarées', ecriture: false,
      aide: "Les portées que ce répéteur annonce relayer — à comparer à ce qu'il relaie vraiment." },
    { type: 'LIRE_TELEMETRIE', libelle: 'Lire la télémétrie', ecriture: false,
      aide: "Batterie, température quand le matériel les expose." },
    { type: 'ANNONCER', libelle: 'Déclencher une annonce', ecriture: true,
      aide: "Fait émettre une annonce au répéteur. Sans danger, mais consomme du temps d'antenne." },
    { type: 'RADIO_TEMPORAIRE', libelle: 'Essayer des paramètres radio (réversible)', ecriture: true,
      aide: "Applique fréquence, bande, étalement et codage pour une durée limitée, puis le répéteur revient de lui-même à ses réglages. C'est la seule façon sûre d'essayer un réglage radio." },
    { type: 'DEFINIR_REGLAGE', libelle: 'Modifier un réglage', ecriture: true,
      aide: "Pose un `set <clé> <valeur>` durable. Les clés qui transportent un secret ou changent l'identité du nœud sont refusées par le serveur, avec leur motif." },
    { type: 'REDEMARRER', libelle: 'Redémarrer', ecriture: true,
      aide: "Le répéteur se recharge avec sa configuration enregistrée. Il est muet le temps du redémarrage." },
    // 19/11/2026 : le reste de ce que MeshCore permet sur un répéteur.
    { type: 'LIRE_PROPRIETAIRE', libelle: 'Lire les informations du propriétaire', ecriture: false,
      aide: "Ce que le répéteur déclare de son propriétaire. Sans effet sur lui." },
    { type: 'LIRE_REGLAGE', libelle: 'Relire un réglage', ecriture: false, session: true,
      aide: "Lit la valeur actuelle d'un réglage (`get <clé>`) — à faire avant de le modifier. Ouvre une session avec le mot de passe : preuve exigée. Les clés secrètes ne sont jamais relues." },
    { type: 'LIRE_VERSION', libelle: 'Lire la version du firmware', ecriture: false, session: true,
      aide: "La version installée (`ver`). Ouvre une session : preuve exigée." },
    { type: 'LIRE_HORLOGE', libelle: "Lire l'horloge", ecriture: false, session: true,
      aide: "L'heure du répéteur (`clock`). Une horloge fausse fait rejeter ses messages horodatés." },
    { type: 'LIRE_ACL', libelle: 'Lire la liste des accès (ACL)', ecriture: false, session: true,
      aide: "Qui a des droits sur ce répéteur, et lesquels. Ouvre une session : preuve exigée." },
    { type: 'SYNCHRO_HORLOGE', libelle: "Remettre l'horloge à l'heure", ecriture: true,
      aide: "`clock sync` : le répéteur prend l'heure du message reçu. Sans danger." },
    { type: 'CONNEXION_ROOM', libelle: 'Se connecter (room server)', ecriture: false, session: true,
      aide: "Pour un room server : ouvre la session ; ses messages arrivent ensuite dans la messagerie comme des messages directs, et on lui écrit de la même façon." },
    { type: 'DECONNECTER', libelle: 'Fermer la session', ecriture: false, session: true,
      aide: "Ferme la session ouverte avec ce répéteur ou ce room server." },
  ];

  /** Opérations sur le nœud LOCAL : la passerelle qui exécute, réglée par l'institution qui l'a
   * déployée (ou un administrateur radio). Rien ne traverse la radio, sauf la découverte de
   * chemin, qui l'interroge justement. */
  readonly operationsLocales: OperationMeshCore[] = [
    { type: 'LOCAL_STATISTIQUES', libelle: 'Statistiques (radio, paquets, système)', ecriture: false,
      aide: "Bruit de fond, paquets reçus et émis, temps d'antenne, durée de fonctionnement." },
    { type: 'LOCAL_REGLAGES', libelle: 'Réglages et identité', ecriture: false,
      aide: "Modèle, firmware, paramètres radio, réglages fins et télémétrie du nœud." },
    { type: 'LOCAL_CHEMIN_ANNONCE', libelle: "Chemin d'annonce d'un contact", ecriture: false,
      aide: "Par quels répéteurs l'annonce de ce contact est arrivée." },
    { type: 'LOCAL_DECOUVRIR_CHEMIN', libelle: 'Découvrir le chemin vers un contact', ecriture: false,
      aide: "Interroge le réseau pour trouver un chemin direct vers ce contact. Utile quand un message direct ne passe plus." },
    { type: 'LOCAL_REINIT_CHEMIN', libelle: "Réinitialiser le chemin d'un contact", ecriture: true,
      aide: "Oublie le chemin mémorisé : le prochain message repartira en diffusion et réapprendra la route." },
    { type: 'LOCAL_SUPPRIMER_CONTACT', libelle: 'Supprimer un contact', ecriture: true,
      aide: "Retire le contact du nœud. Il reviendra à sa prochaine annonce si l'ajout automatique est actif." },
    { type: 'LOCAL_NOM', libelle: 'Changer le nom', ecriture: true,
      aide: "Le nom annoncé sur le réseau (31 octets au plus)." },
    { type: 'LOCAL_POSITION', libelle: 'Changer la position', ecriture: true,
      aide: "La position annoncée du nœud." },
    { type: 'LOCAL_PUISSANCE', libelle: "Puissance d'émission", ecriture: true,
      aide: "En dBm. Le firmware borne selon la carte ; plus fort porte plus loin et consomme plus." },
    { type: 'LOCAL_RADIO', libelle: 'Paramètres radio (durable)', ecriture: true,
      aide: "Fréquence, bande, étalement, codage — DURABLE. Sur d'autres paramètres que le réseau, le nœud n'entend plus personne ; il reste joignable par son câble pour revenir en arrière." },
  ];

  rattachements: RattachementNoeudRadio[] = [];
  companions: CompagnonMeshCore[] = [];
  taches: TacheAdminMeshCore[] = [];
  chargement = true;
  erreur: string | null = null;

  /** Formulaire de réclamation. */
  reclamation = {
    pubkey_hex: '',
    libelle: '',
    moyen_admin: 'MOT_DE_PASSE' as 'MOT_DE_PASSE' | 'ACL',
    mot_de_passe: '',
    compagnon_meshcore: '',
  };
  erreurReclamation: string | null = null;
  envoiReclamation = false;

  /** Formulaire d'opération. */
  operation = {
    rattachement: '',
    type: 'LIRE_STATUT' as TypeTacheAdminMeshCore,
    cle: '',
    valeur: '',
    frequence_mhz: 869.525,
    bande_khz: 250,
    facteur_etalement: 11,
    taux_codage: 5,
    minutes: 10,
  };
  erreurOperation: string | null = null;
  envoiOperation = false;
  tacheDepliee: string | null = null;

  /** Formulaire d'opération sur le nœud local. */
  locale = {
    compagnon: '',
    type: 'LOCAL_STATISTIQUES' as TypeTacheAdminMeshCore,
    pubkey: '', nom: '', latitude: 0, longitude: 0, dbm: 20,
    frequence_mhz: 869.525, bande_khz: 250, facteur_etalement: 11, taux_codage: 5, confirme: false,
  };
  erreurLocale: string | null = null;
  envoiLocale = false;

  /** Relevés groupés de la flotte. */
  messageFlotte: string | null = null;
  envoiFlotte = false;

  constructor(private service: AdministrationMeshCoreService,
              private rattachementService: RattachementNoeudRadioService,
              private compagnonService: CompagnonMeshCoreService,
              private auth: AuthService) {}

  ngOnInit(): void {
    this.charger();
  }

  charger(): void {
    this.chargement = true;
    this.service.rattachements().subscribe({
      next: (tous) => {
        // Seuls les rattachements MeshCore : la même table porte aussi les nœuds Meshtastic,
        // qui s'administrent depuis leur propre page et par un tout autre mécanisme.
        this.rattachements = tous.filter(r => !!r.pubkey_hex);
        this.chargement = false;
      },
      error: () => {
        this.erreur = "Impossible de lire les répéteurs réclamés.";
        this.chargement = false;
      },
    });
    this.compagnonService.getAll().subscribe({
      next: (companions) => { this.companions = companions.filter(c => c.actif); },
      error: () => { this.companions = []; },
    });
    this.rafraichirTaches();
  }

  rafraichirTaches(): void {
    this.service.taches().subscribe({
      next: (taches) => { this.taches = taches; },
      error: () => { this.taches = []; },
    });
  }

  get monInstitutionId(): string | null {
    return this.auth.getCurrentUser()?.institution_id ?? null;
  }

  get operationChoisie(): OperationMeshCore | undefined {
    return this.operations.find(o => o.type === this.operation.type);
  }

  get rattachementChoisi(): RattachementNoeudRadio | undefined {
    return this.rattachements.find(r => r.id === this.operation.rattachement);
  }

  /** Une écriture sur un répéteur dont la preuve n'est pas faite sera refusée par le serveur :
   * autant le dire avant le clic plutôt que de le faire découvrir par un 403. */
  get ecritureImpossible(): boolean {
    const operation = this.operationChoisie;
    const rattachement = this.rattachementChoisi;
    return !!(operation?.ecriture || operation?.session) && !!rattachement && !rattachement.preuve_faite;
  }

  libelleRattachement(rattachement: RattachementNoeudRadio): string {
    return rattachement.libelle || rattachement.pubkey_hex.slice(0, 12);
  }

  nomRattachementPour(pubkey: string): string {
    const rattachement = this.rattachements.find(r => r.pubkey_hex === pubkey);
    return rattachement ? this.libelleRattachement(rattachement) : pubkey.slice(0, 12);
  }

  reclamer(): void {
    if (this.envoiReclamation) return;
    this.erreurReclamation = null;
    this.envoiReclamation = true;
    const institution = this.monInstitutionId;
    this.rattachementService.rattacher({
      pubkey_hex: this.reclamation.pubkey_hex.trim().toLowerCase(),
      institution,
      utilisateur: institution ? null : (this.auth.getCurrentUser()?.id ?? null),
      libelle: this.reclamation.libelle.trim(),
      moyen_admin: this.reclamation.moyen_admin,
      // La voie ACL n'utilise pas de mot de passe : le serveur refuse les deux à la fois.
      mot_de_passe: this.reclamation.moyen_admin === 'MOT_DE_PASSE'
        ? this.reclamation.mot_de_passe : '',
      compagnon_meshcore: this.reclamation.compagnon_meshcore || null,
    }).subscribe({
      next: () => {
        this.reclamation.pubkey_hex = '';
        this.reclamation.libelle = '';
        this.reclamation.mot_de_passe = '';
        this.envoiReclamation = false;
        this.charger();
      },
      error: (e: HttpErrorResponse) => {
        this.erreurReclamation = this.message(e);
        this.envoiReclamation = false;
      },
    });
  }

  verifier(rattachement: RattachementNoeudRadio): void {
    this.erreur = null;
    this.service.verifier(rattachement.id).subscribe({
      next: () => this.charger(),
      error: (e: HttpErrorResponse) => { this.erreur = this.message(e); },
    });
  }

  detacher(rattachement: RattachementNoeudRadio): void {
    this.erreur = null;
    this.rattachementService.detacher(rattachement.id).subscribe({
      next: () => this.charger(),
      error: (e: HttpErrorResponse) => { this.erreur = this.message(e); },
    });
  }

  lancer(): void {
    const rattachement = this.rattachementChoisi;
    if (!rattachement || this.envoiOperation) return;
    this.erreurOperation = null;
    this.envoiOperation = true;

    this.service.creer({
      compagnon: rattachement.compagnon_meshcore ?? '',
      pubkey_cible: rattachement.pubkey_hex,
      type_tache: this.operation.type,
      parametres: this.parametres(),
    }).subscribe({
      next: () => {
        this.envoiOperation = false;
        this.rafraichirTaches();
      },
      error: (e: HttpErrorResponse) => {
        this.erreurOperation = this.message(e);
        this.envoiOperation = false;
      },
    });
  }

  private parametres(): Record<string, unknown> | null {
    if (this.operation.type === 'RADIO_TEMPORAIRE') {
      return {
        frequence_mhz: this.operation.frequence_mhz,
        bande_khz: this.operation.bande_khz,
        facteur_etalement: this.operation.facteur_etalement,
        taux_codage: this.operation.taux_codage,
        minutes: this.operation.minutes,
      };
    }
    if (this.operation.type === 'DEFINIR_REGLAGE') {
      return { cle: this.operation.cle.trim(), valeur: this.operation.valeur.trim() };
    }
    if (this.operation.type === 'LIRE_REGLAGE') {
      return { cle: this.operation.cle.trim() };
    }
    return null;
  }

  // ── Nœud local ─────────────────────────────────────────────────────────

  get operationLocaleChoisie(): OperationMeshCore | undefined {
    return this.operationsLocales.find(o => o.type === this.locale.type);
  }

  get localeAvecContact(): boolean {
    return ['LOCAL_CHEMIN_ANNONCE', 'LOCAL_DECOUVRIR_CHEMIN', 'LOCAL_REINIT_CHEMIN',
            'LOCAL_SUPPRIMER_CONTACT'].includes(this.locale.type);
  }

  parametresLocaux(): Record<string, unknown> | null {
    const l = this.locale;
    switch (l.type) {
      case 'LOCAL_CHEMIN_ANNONCE': case 'LOCAL_DECOUVRIR_CHEMIN':
      case 'LOCAL_REINIT_CHEMIN': case 'LOCAL_SUPPRIMER_CONTACT':
        return { pubkey: l.pubkey.trim().toLowerCase() };
      case 'LOCAL_NOM': return { nom: l.nom.trim() };
      case 'LOCAL_POSITION': return { latitude: l.latitude, longitude: l.longitude };
      case 'LOCAL_PUISSANCE': return { dbm: l.dbm };
      case 'LOCAL_RADIO':
        return { frequence_mhz: l.frequence_mhz, bande_khz: l.bande_khz, facteur_etalement: l.facteur_etalement,
                 taux_codage: l.taux_codage, confirme: l.confirme };
      default: return null;
    }
  }

  lancerLocale(): void {
    if (!this.locale.compagnon || this.envoiLocale) return;
    this.erreurLocale = null;
    this.envoiLocale = true;
    this.service.creer({ compagnon: this.locale.compagnon, type_tache: this.locale.type,
                         parametres: this.parametresLocaux() }).subscribe({
      next: () => { this.envoiLocale = false; this.locale.confirme = false; this.rafraichirTaches(); },
      error: (e: HttpErrorResponse) => { this.erreurLocale = this.message(e); this.envoiLocale = false; },
    });
  }

  // ── Flotte ─────────────────────────────────────────────────────────────

  /** Le dernier résultat réussi d'un type d'opération sur ce répéteur, ou null. */
  private dernier(pubkey: string, type: TypeTacheAdminMeshCore): TacheAdminMeshCore | null {
    return this.taches
      .filter(t => t.pubkey_cible === pubkey && t.type_tache === type && t.statut === 'TERMINEE')
      .sort((a, b) => (b.date_reponse ?? '').localeCompare(a.date_reponse ?? ''))[0] ?? null;
  }

  private json(tache: TacheAdminMeshCore | null): Record<string, unknown> | null {
    if (!tache?.reponse) return null;
    try { return JSON.parse(tache.reponse); } catch { return null; }
  }

  /** Une ligne par répéteur réclamé : son dernier état connu, tiré des opérations déjà faites. */
  get flotte() {
    return this.rattachements.map(r => {
      const statut = this.json(this.dernier(r.pubkey_hex, 'LIRE_STATUT'));
      const version = this.json(this.dernier(r.pubkey_hex, 'LIRE_VERSION'));
      const horloge = this.json(this.dernier(r.pubkey_hex, 'LIRE_HORLOGE'));
      const echecs = this.taches.filter(t => t.pubkey_cible === r.pubkey_hex && t.statut === 'ECHEC')
        .sort((a, b) => (b.date_reponse ?? '').localeCompare(a.date_reponse ?? ''));
      const releve = this.dernier(r.pubkey_hex, 'LIRE_STATUT');
      return {
        rattachement: r,
        batterieV: typeof statut?.['bat'] === 'number' ? (statut['bat'] as number) / 1000 : null,
        enServiceH: typeof statut?.['uptime'] === 'number' ? Math.round((statut['uptime'] as number) / 3600) : null,
        bruitDbm: typeof statut?.['noise_floor'] === 'number' ? statut['noise_floor'] as number : null,
        version: (version?.['reponse'] as string) ?? null,
        horloge: (horloge?.['reponse'] as string) ?? null,
        releveLe: releve?.date_reponse ?? null,
        derniereErreur: echecs[0]?.erreur ?? null,
      };
    });
  }

  /** Met en file, pour chaque répéteur réclamé qui a une passerelle, les lectures qui
   * renseignent la flotte : statut et télémétrie pour tous, version et horloge pour ceux dont
   * la preuve est faite (elles ouvrent une session). */
  releverLaFlotte(): void {
    const demandes: { compagnon: string; pubkey_cible: string; type_tache: TypeTacheAdminMeshCore }[] = [];
    for (const r of this.rattachements) {
      if (!r.compagnon_meshcore) continue;
      const types: TypeTacheAdminMeshCore[] = ['LIRE_STATUT', 'LIRE_TELEMETRIE'];
      if (r.preuve_faite) types.push('LIRE_VERSION', 'LIRE_HORLOGE');
      for (const t of types) demandes.push({ compagnon: r.compagnon_meshcore, pubkey_cible: r.pubkey_hex, type_tache: t });
    }
    this.envoyerEnLot(demandes, 'relevés');
  }

  /** `clock sync` sur chaque répéteur dont la preuve est faite. */
  remettreLesHorloges(): void {
    if (!confirm("Remettre à l'heure l'horloge de chaque répéteur dont la preuve est faite ?")) return;
    const demandes = this.rattachements.filter(r => r.preuve_faite && r.compagnon_meshcore)
      .map(r => ({ compagnon: r.compagnon_meshcore!, pubkey_cible: r.pubkey_hex,
                   type_tache: 'SYNCHRO_HORLOGE' as TypeTacheAdminMeshCore }));
    this.envoyerEnLot(demandes, 'remises à l\'heure');
  }

  private envoyerEnLot(demandes: { compagnon: string; pubkey_cible: string; type_tache: TypeTacheAdminMeshCore }[],
                       quoi: string): void {
    if (!demandes.length) { this.messageFlotte = "Aucun répéteur concerné (passerelle ou preuve manquante)."; return; }
    this.envoiFlotte = true;
    let restantes = demandes.length, refusees = 0;
    for (const d of demandes) {
      this.service.creer(d).subscribe({
        next: () => { if (--restantes === 0) this.finLot(demandes.length, refusees, quoi); },
        error: () => { refusees++; if (--restantes === 0) this.finLot(demandes.length, refusees, quoi); },
      });
    }
  }

  private finLot(total: number, refusees: number, quoi: string): void {
    this.envoiFlotte = false;
    this.messageFlotte = `${total - refusees} ${quoi} mis en file` + (refusees ? `, ${refusees} refusé(s).` : '.');
    this.rafraichirTaches();
  }

  basculerTache(id: string): void {
    this.tacheDepliee = this.tacheDepliee === id ? null : id;
  }

  /** Réponse du pont, mise en forme. Elle arrive en JSON sérialisé ; si ce n'est pas du JSON,
   * on l'affiche telle quelle plutôt que de la masquer — c'est souvent là qu'est l'indice. */
  reponseLisible(tache: TacheAdminMeshCore): string {
    if (!tache.reponse) return '';
    try {
      return JSON.stringify(JSON.parse(tache.reponse), null, 2);
    } catch {
      return tache.reponse;
    }
  }

  private message(e: HttpErrorResponse): string {
    const corps = e?.error;
    if (typeof corps === 'string') return corps;
    if (corps && typeof corps === 'object') {
      const premier = Object.values(corps)[0];
      if (Array.isArray(premier) && premier.length) return String(premier[0]);
      if (typeof premier === 'string') return premier;
    }
    return "L'opération a échoué.";
  }
}
