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
    return !!operation?.ecriture && !!rattachement && !rattachement.preuve_faite;
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
    return null;
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
