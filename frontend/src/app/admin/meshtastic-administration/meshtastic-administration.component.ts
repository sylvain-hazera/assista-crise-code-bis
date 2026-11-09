import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { AdministrationMeshtasticService } from '../../services/administration-meshtastic.service';
import { CompagnonMeshtasticService } from '../../services/compagnon-meshtastic.service';
import { ContactMeshtasticService } from '../../services/contact-meshtastic.service';
import { CompagnonMeshtastic } from '../../shared/models/compagnon-meshtastic.model';
import { ContactMeshtastic } from '../../shared/models/contact-meshtastic.model';
import {
  CatalogueReglages, ChampReglage, ConfigurationNoeudMeshtastic, OPERATIONS_ADMIN_MESHTASTIC,
  SectionReglages, TacheAdminMeshtastic, TypeTacheAdminMeshtastic,
} from '../../shared/models/administration-meshtastic.model';

/** Administration à distance des nœuds Meshtastic.
 *
 * Trois choses que cette page doit rendre évidentes, parce qu'elles décident de tout :
 *
 * 1. **Seule une passerelle branchée en TCP ou en série peut administrer.** C'est le firmware de
 *    l'appareil qui chiffre le message d'administration ; un companion MQTT n'a pas d'appareil.
 * 2. **Un nœud distant doit porter la clé publique de la passerelle** dans sa liste
 *    `security.admin_key`, posée une fois avec l'application Meshtastic officielle. D'où la clé
 *    affichée en haut, prête à être recopiée : sans elle, chaque opération échouera avec
 *    « clé publique non autorisée ».
 * 3. **La passerelle elle-même s'administre sans rien poser.** C'est par là qu'il faut
 *    commencer pour vérifier que la chaîne fonctionne.
 *
 * La puissance d'émission lue ici n'est pas un détail d'inventaire : c'est elle qui permet au
 * diagnostic des liaisons de corriger l'écart de SNR, et donc de ne plus confondre un relais
 * sourd avec un voisin qui émet simplement plus fort. */
@Component({
  selector: 'app-meshtastic-administration',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshtastic-administration.component.html',
  styleUrl: './meshtastic-administration.component.scss',
})
export class MeshtasticAdministrationComponent implements OnInit {

  readonly operations = OPERATIONS_ADMIN_MESHTASTIC;

  /** Passerelles capables d'administrer : un appareil réel, et lui seul. */
  passerelles: CompagnonMeshtastic[] = [];
  contacts: ContactMeshtastic[] = [];
  taches: TacheAdminMeshtastic[] = [];
  configurations: ConfigurationNoeudMeshtastic[] = [];

  chargement = true;
  erreur: string | null = null;

  nouvelle: {
    compagnon: string;
    cible: string;            // '' = la passerelle elle-même, sinon le node_num en décimal
    type_tache: TypeTacheAdminMeshtastic;
    puissance_dbm: number;
    delai_s: number;
    mqtt_json: boolean;
  } = {
    compagnon: '', cible: '', type_tache: 'LIRE_CONFIG_LORA', puissance_dbm: 20, delai_s: 10,
    mqtt_json: true,
  };

  /** Catalogue servi par le serveur : sections, champs, types et bornes. Jamais recopié ici —
   * ce sont des contraintes du firmware, les dupliquer garantirait qu'elles divergent. */
  catalogue: CatalogueReglages = {};
  sectionChoisie = 'lora';
  /** Réglages cochés par l'exploitant, avec leur valeur. **Seuls ceux-là sont envoyés** : le
   * firmware remplace tout le bloc, donc le pont relit la section et renvoie les autres
   * inchangés. Envoyer un champ non coché l'écraserait par la valeur par défaut du formulaire —
   * sur la section LoRa, cela effacerait la région, et un nœud sans région ne transmet plus. */
  reglagesModifies: Record<string, { actif: boolean; valeur: unknown }> = {};
  nom = { nom_long: '', nom_court: '' };

  envoiEnCours = false;
  erreurEnvoi: string | null = null;
  /** Tâche dont on affiche la réponse détaillée. */
  tacheDepliee: string | null = null;
  /** Écriture en attente de confirmation : on ne reconfigure pas un relais sur un clic. */
  confirmationDemandee = false;

  constructor(
    private service: AdministrationMeshtasticService,
    private compagnons: CompagnonMeshtasticService,
    private contactsService: ContactMeshtasticService,
  ) {}

  ngOnInit(): void {
    this.charger();
    this.service.catalogueReglages().subscribe({
      next: (catalogue) => { this.catalogue = catalogue; this.reinitialiserReglages(); },
      error: () => { /* les lectures et les autres opérations restent utilisables */ },
    });
  }

  get sections(): { cle: string; libelle: string }[] {
    return Object.entries(this.catalogue)
      .map(([cle, section]) => ({ cle, libelle: section.libelle }));
  }

  /** Type explicitement optionnel : le catalogue est vide tant que la requête n'a pas répondu,
   * et la section choisie peut ne pas y figurer. */
  get sectionCourante(): SectionReglages | undefined {
    return this.catalogue[this.sectionChoisie];
  }

  get champsSection(): { cle: string; champ: ChampReglage }[] {
    const section = this.sectionCourante;
    return section ? Object.entries(section.champs).map(([cle, champ]) => ({ cle, champ })) : [];
  }

  /** Remet tous les réglages à « non coché » : changer de section ne doit pas emporter une
   * coche faite sur la précédente. */
  reinitialiserReglages(): void {
    this.reglagesModifies = {};
    for (const { cle, champ } of this.champsSection) {
      this.reglagesModifies[cle] = { actif: false, valeur: this.valeurInitiale(champ) };
    }
  }

  private valeurInitiale(champ: ChampReglage): unknown {
    if (champ.type === 'booleen') { return true; }
    if (champ.type === 'enumeration') { return champ.valeurs?.[0] ?? ''; }
    return champ.mini ?? 0;
  }

  get aucunReglageCoche(): boolean {
    return !Object.values(this.reglagesModifies).some(r => r.actif);
  }

  charger(): void {
    this.chargement = true;
    this.compagnons.getAll().subscribe({
      next: (tous) => {
        this.passerelles = tous.filter(
          (c) => c.connexion_type === 'TCP' || c.connexion_type === 'SERIE',
        );
        if (!this.nouvelle.compagnon && this.passerelles.length) {
          this.nouvelle.compagnon = this.passerelles[0].id;
        }
        this.chargerContacts();
        this.chargement = false;
      },
      error: (e: HttpErrorResponse) => {
        this.erreur = e.status === 403
          ? "L'administration des nœuds radio est réservée aux acteurs institutionnels."
          : 'Impossible de charger les passerelles.';
        this.chargement = false;
      },
    });
    this.rafraichir();
  }

  rafraichir(): void {
    this.service.taches().subscribe({
      next: (taches) => { this.taches = taches; },
      error: () => { this.erreur = 'Impossible de charger la file des opérations.'; },
    });
    this.service.configurations().subscribe({
      next: (configurations) => { this.configurations = configurations; },
      error: () => { /* la file reste utilisable sans l'inventaire */ },
    });
  }

  /** Nœuds connus de la passerelle choisie, pour ne pas saisir un numéro à la main.
   *
   * `compagnonId` est passé explicitement depuis le template : l'ordre d'exécution entre le
   * `[(ngModel)]` et un `(ngModelChange)` voisin ne mérite pas qu'on parie dessus, et se tromper
   * chargerait les nœuds de la passerelle PRÉCÉDENTE. */
  chargerContacts(compagnonId?: string): void {
    const id = compagnonId ?? this.nouvelle.compagnon;
    if (!id) { this.contacts = []; return; }
    this.contactsService.getAll(id).subscribe({
      next: (contacts) => { this.contacts = contacts; },
      error: () => { this.contacts = []; },
    });
  }

  get passerelleChoisie(): CompagnonMeshtastic | undefined {
    return this.passerelles.find((p) => p.id === this.nouvelle.compagnon);
  }

  get operationChoisie() {
    return this.operations.find((o) => o.type === this.nouvelle.type_tache);
  }

  get estEcriture(): boolean {
    return this.operationChoisie?.ecriture ?? false;
  }

  /** Vrai quand l'opération visera un nœud distant : c'est le seul cas qui exige d'avoir posé
   * la clé publique de la passerelle sur la cible. */
  get viseUnNoeudDistant(): boolean {
    return this.nouvelle.cible !== '';
  }

  demanderConfirmation(): void {
    if (this.estEcriture) { this.confirmationDemandee = true; } else { this.envoyer(); }
  }

  annulerConfirmation(): void {
    this.confirmationDemandee = false;
  }

  envoyer(): void {
    if (!this.nouvelle.compagnon) { return; }
    this.confirmationDemandee = false;
    this.envoiEnCours = true;
    this.erreurEnvoi = null;

    let parametres: Record<string, unknown> | null = null;
    if (this.nouvelle.type_tache === 'LIRE_REGLAGES') {
      parametres = { section: this.sectionChoisie };
    } else if (this.nouvelle.type_tache === 'DEFINIR_REGLAGES') {
      const valeurs: Record<string, unknown> = {};
      for (const [cle, etat] of Object.entries(this.reglagesModifies)) {
        if (etat.actif) { valeurs[cle] = etat.valeur; }
      }
      parametres = { section: this.sectionChoisie, valeurs };
    } else if (this.nouvelle.type_tache === 'DEFINIR_NOM') {
      parametres = {};
      if (this.nom.nom_long.trim()) { parametres['nom_long'] = this.nom.nom_long.trim(); }
      if (this.nom.nom_court.trim()) { parametres['nom_court'] = this.nom.nom_court.trim(); }
    } else if (this.nouvelle.type_tache === 'DEFINIR_PUISSANCE') {
      parametres = { puissance_dbm: Number(this.nouvelle.puissance_dbm) };
    } else if (this.nouvelle.type_tache === 'REDEMARRER') {
      parametres = { delai_s: Number(this.nouvelle.delai_s) };
    } else if (this.nouvelle.type_tache === 'DEFINIR_MQTT_JSON') {
      parametres = { actif: this.nouvelle.mqtt_json };
    }

    this.service.creer({
      compagnon: this.nouvelle.compagnon,
      node_num_cible: this.nouvelle.cible === '' ? null : Number(this.nouvelle.cible),
      type_tache: this.nouvelle.type_tache,
      parametres,
    }).subscribe({
      next: () => { this.envoiEnCours = false; this.rafraichir(); },
      error: (e: HttpErrorResponse) => {
        this.envoiEnCours = false;
        this.erreurEnvoi = this.messageDErreur(e) ?? "Mise en file impossible.";
      },
    });
  }

  /** Taille en OCTETS d'un nom : c'est la limite du firmware, et quatre lettres accentuées en
   * font huit. Compter les caractères laisserait le firmware tronquer en silence. */
  octets(valeur: string): number {
    return new TextEncoder().encode(valeur).length;
  }

  basculerDetail(id: string): void {
    this.tacheDepliee = this.tacheDepliee === id ? null : id;
  }

  /** Réponse du pont, remise en forme pour la lecture. Elle arrive en JSON sérialisé. */
  reponseLisible(tache: TacheAdminMeshtastic): string {
    if (!tache.reponse) { return ''; }
    try {
      return JSON.stringify(JSON.parse(tache.reponse), null, 2);
    } catch {
      return tache.reponse;
    }
  }

  nomNoeud(nodeNum: number | null): string {
    if (nodeNum === null) { return 'la passerelle elle-même'; }
    const contact = this.contacts.find((c) => c.node_num === nodeNum);
    const nom = contact?.long_name || contact?.short_name;
    return nom ? `${nom} (${this.hexa(nodeNum)})` : this.hexa(nodeNum);
  }

  hexa(nodeNum: number): string {
    return `!${nodeNum.toString(16).padStart(8, '0')}`;
  }

  /** Puissance affichée. 0 n'est pas « 0 dBm » : le firmware applique alors le maximum de la
   * région, c'est donc une puissance qu'on ne connaît pas — et le diagnostic des liaisons la
   * traite comme absente. L'afficher « 0 dBm » tromperait sur la foi qu'on peut y mettre. */
  puissanceLisible(config: ConfigurationNoeudMeshtastic): string {
    if (config.puissance_emission_dbm === null) { return 'inconnue'; }
    if (config.puissance_emission_dbm === 0) { return 'maximum de la région (inconnue)'; }
    return `${config.puissance_emission_dbm} dBm`;
  }

  private messageDErreur(e: HttpErrorResponse): string | null {
    const corps = e.error;
    if (typeof corps === 'string') { return corps; }
    if (Array.isArray(corps)) { return String(corps[0]); }
    if (corps && typeof corps === 'object') {
      if (corps['detail']) { return String(corps['detail']); }
      const premier = Object.values(corps)[0];
      if (Array.isArray(premier)) { return String(premier[0]); }
      if (premier) { return String(premier); }
    }
    return null;
  }
}
