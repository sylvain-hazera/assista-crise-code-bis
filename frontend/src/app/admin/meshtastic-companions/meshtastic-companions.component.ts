import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CompagnonMeshtasticService } from '../../services/compagnon-meshtastic.service';
import { MeshLocalDetecterService } from '../../services/mesh-local-detecter.service';
import { CanalMeshtasticService } from '../../services/canal-meshtastic.service';
import { ContactMeshtasticService } from '../../services/contact-meshtastic.service';
import { NoeudUtilisateurMeshtasticService } from '../../services/noeud-utilisateur-meshtastic.service';
import { UserService } from '../../services/user.service';
import { CompagnonMeshtastic } from '../../shared/models/compagnon-meshtastic.model';
import { CanalMeshtastic } from '../../shared/models/canal-meshtastic.model';
import { ContactMeshtastic } from '../../shared/models/contact-meshtastic.model';
import { NoeudUtilisateurMeshtastic } from '../../shared/models/noeud-utilisateur-meshtastic.model';
import { User } from '../../shared/models/user.model';
import { RouteMeshtastic, RoutageMeshtastic } from '../../shared/models/routage-meshtastic.model';
import { TableTriFiltre } from '../../shared/utils/table-tri-filtre';
import { ThFiltreComponent, ThTriComponent } from '../../shared/components/common/table-tri/table-tri.components';

/** Page de paramétrage Meshtastic : déclarer une identité de nœud logicielle (companion, sans
 * matériel — voir meshtastic-bridge/README.md), des canaux (PSK partagée), et associer les
 * nœuds détectés sur le mesh à des comptes utilisateurs. Le chiffrement (PSK canal, PKI) est
 * réimplémenté à la main et non fiable sur tous les brokers (ex: Gaulix, voir
 * CompagnonMeshtastic.chiffrement_supporte) : à manier avec précaution. */
@Component({
  selector: 'app-meshtastic-companions',
  standalone: true,
  imports: [CommonModule, FormsModule, ThTriComponent, ThFiltreComponent],
  templateUrl: './meshtastic-companions.component.html',
  styleUrl: './meshtastic-companions.component.scss',
})
export class MeshtasticCompanionsComponent implements OnInit {

  companions: CompagnonMeshtastic[] = [];
  loading = true;
  errorMessage = '';

  // Détection automatique (usage offline, sans internet) : on donne juste IP + port d'un vrai
  // appareil, le serveur essaie une vraie connexion Meshtastic puis MeshCore et crée le
  // companion correspondant tout seul — voir MeshLocalDetecterService.
  detectIp = '';
  detectPort = 4403;
  detectNom = '';
  detecting = false;
  detectError = '';
  detectResultat = '';

  nouveauNom = '';
  nouveauNodeNum: number | null = null;
  nouveauLongName = '';
  nouveauShortName = '';
  nouveauBrokerHost = 'mqtt.gaulix.fr';
  nouveauBrokerPort = 1883;
  // "Traitement/msh/EU_868" et pas "msh/EU_868" pour Gaulix — vérifié en sniffant leur broker
  // en direct, contrairement à leur documentation publique (voir CompagnonMeshtastic.topic_racine).
  nouveauTopicRacine = 'Traitement/msh/EU_868';
  nouveauChiffrementSupporte = false;
  nouveauMqttUsername = '';
  nouveauMqttPassword = '';
  nouveauMqttUseTls = false;
  creating = false;

  editingCompanionId: string | null = null;
  editNom = '';
  editBrokerHost = '';
  editBrokerPort = 1883;
  editTopicRacine = '';
  editChiffrementSupporte = false;
  editActif = true;
  editMqttUsername = '';
  editMqttPassword = '';
  editMqttUseTls = false;
  saving = false;

  canaux: CanalMeshtastic[] = [];
  nouveauCanalNom = '';
  nouveauCanalPsk = '';
  nouveauCanalPrincipal = false;
  nouveauCanalCompagnonId = '';
  creatingCanal = false;

  noeuds: NoeudUtilisateurMeshtastic[] = [];
  utilisateurs: User[] = [];
  nouveauNoeudUtilisateurId = '';
  nouveauNoeudNodeNum: number | null = null;
  nouveauNoeudNom = '';
  creatingNoeud = false;

  contacts: ContactMeshtastic[] = [];

  /** Routage : par quelle passerelle chaque nœud a été entendu, et par où l'atteindre. Chargé en
   * un appel pour tout le tableau (voir ContactMeshtasticService.routage). */
  routage: RoutageMeshtastic | null = null;
  routesParNoeud = new Map<number, RouteMeshtastic>();
  routageEnCours = false;
  routageErreur = '';

  /** Tri et filtrage des quatre tableaux de la page. Un objet par tableau, déclaré ici : les
   * accesseurs disent ce qu'une colonne vaut pour le tri (nombre, date, booléen) et ce qu'elle
   * vaut pour le filtre (le texte lu à l'écran) — voir shared/utils/table-tri-filtre.ts. */
  triCompagnons = new TableTriFiltre<CompagnonMeshtastic>({
    nom: { valeur: c => c.nom },
    node_num: { valeur: c => c.node_num, texte: c => this.nodeNumHex(c.node_num) },
    broker: { valeur: c => this.brokerTexte(c), texte: c => this.brokerTexte(c) },
    chiffrement: { valeur: c => c.chiffrement_supporte, texte: c => c.chiffrement_supporte ? 'Supporté' : 'Clair forcé' },
    cle: { valeur: c => c.x25519_public_key_hex || null, texte: c => c.x25519_public_key_hex || '' },
    statut: { valeur: c => c.dernier_etat || null, texte: c => c.dernier_etat || 'jamais connecté' },
    // Date de tri réelle, pas la chaîne affichée : « 09/11 » et « 10/01 » ne se trient pas
    // dans le bon ordre en texte.
    connexion: { valeur: c => this.date(c.derniere_connexion), texte: c => this.dateTexte(c.derniere_connexion) },
    id: { valeur: c => c.id },
  }, 'nom');

  triCanaux = new TableTriFiltre<CanalMeshtastic>({
    nom: { valeur: c => c.nom },
    broker: { valeur: c => c.compagnon_nom || 'Tous les brokers' },
    chiffre: { valeur: c => !!c.psk_hex, texte: c => c.psk_hex ? 'Oui' : 'Non' },
    principal: { valeur: c => !!c.principal, texte: c => c.principal ? 'Oui' : 'Non' },
    actif: { valeur: c => !!c.actif, texte: c => c.actif ? 'Oui' : 'Non' },
  }, 'nom');

  triContacts = new TableTriFiltre<ContactMeshtastic>({
    nom: { valeur: c => c.long_name || c.short_name || null, texte: c => c.long_name || c.short_name || '' },
    node_num: { valeur: c => c.node_num, texte: c => this.nodeNumHex(c.node_num) },
    materiel: { valeur: c => c.hardware_model || null, texte: c => c.hardware_model || '' },
    cle: { valeur: c => !!c.public_key_hex, texte: c => c.public_key_hex ? 'Oui (PKI possible)' : 'Non (PSK canal seulement)' },
    passerelles: { valeur: c => this.passerellesTexte(c), texte: c => this.passerellesTexte(c) },
    // Les nœuds qu'aucune passerelle n'entend ont `sauts` à null : ils finissent en dernier dans
    // les deux sens de tri, parce que « inatteignable » n'est pas « à zéro saut ».
    sauts: { valeur: c => this.routesParNoeud.get(c.node_num)?.sauts ?? null,
             texte: c => this.sautsTexte(c) },
    joindre: { valeur: c => this.routesParNoeud.get(c.node_num)?.compagnon_nom || null,
               texte: c => this.routesParNoeud.get(c.node_num)?.raison || '' },
    contact: { valeur: c => this.date(c.dernier_advert), texte: c => this.dateTexte(c.dernier_advert) },
    attribue: { valeur: c => c.deja_associe, texte: c => c.deja_associe ? 'Oui' : 'Non' },
  }, 'contact', -1);

  triNoeuds = new TableTriFiltre<NoeudUtilisateurMeshtastic>({
    utilisateur: { valeur: n => n.utilisateur_nom || null, texte: n => n.utilisateur_nom || '' },
    nom_noeud: { valeur: n => n.nom_noeud || null, texte: n => n.nom_noeud || '' },
    node_num: { valeur: n => n.node_num, texte: n => this.nodeNumHex(n.node_num) },
    actif: { valeur: n => !!n.actif, texte: n => n.actif ? 'Oui' : 'Non' },
  }, 'utilisateur');

  constructor(
    private service: CompagnonMeshtasticService,
    private detecterService: MeshLocalDetecterService,
    private canalService: CanalMeshtasticService,
    private contactService: ContactMeshtasticService,
    private noeudService: NoeudUtilisateurMeshtasticService,
    private userService: UserService,
  ) {}

  ngOnInit(): void {
    this.load();
    this.loadCanaux();
    this.loadNoeuds();
    this.loadContacts();
    this.chargerRoutage();
    this.userService.getAll().subscribe(data => { this.utilisateurs = data; });
  }

  loadContacts(): void {
    this.contactService.getAll().subscribe(data => { this.contacts = data; });
  }

  /** Relu à la demande : le calcul relit une semaine de liaisons, donc jamais en boucle. */
  chargerRoutage(): void {
    this.routageEnCours = true;
    this.routageErreur = '';
    this.contactService.routage().subscribe({
      next: resultat => {
        this.routage = resultat;
        this.routesParNoeud = new Map(resultat.routes.map(r => [r.node_num, r]));
        this.routageEnCours = false;
      },
      error: () => {
        this.routageEnCours = false;
        this.routageErreur = 'Impossible de calculer le routage des nœuds.';
      },
    });
  }

  route(contact: ContactMeshtastic): RouteMeshtastic | undefined {
    return this.routesParNoeud.get(contact.node_num);
  }

  /** Tableaux affichés : filtrés et triés. */
  get compagnonsAffiches(): CompagnonMeshtastic[] {
    return this.triCompagnons.appliquer(this.companions);
  }

  get canauxAffiches(): CanalMeshtastic[] {
    return this.triCanaux.appliquer(this.canaux);
  }

  /** TOUS les nœuds détectés, attribués ou non — la colonne « Attribué » est filtrable. Avant,
   * la page ne montrait que les non attribués : les autres devenaient invisibles, routage
   * compris, alors que ce sont justement ceux qu'on cherche à joindre. */
  get contactsAffiches(): ContactMeshtastic[] {
    return this.triContacts.appliquer(this.contacts);
  }

  get noeudsAffiches(): NoeudUtilisateurMeshtastic[] {
    return this.triNoeuds.appliquer(this.noeuds);
  }

  brokerTexte(c: CompagnonMeshtastic): string {
    if (c.connexion_type === 'TCP') return `${c.tcp_host}:${c.tcp_port}`;
    return `${c.broker_host}:${c.broker_port}`;
  }

  passerellesTexte(c: ContactMeshtastic): string {
    const route = this.routesParNoeud.get(c.node_num);
    if (!route || !route.passerelles.length) return '';
    return route.passerelles.map(p => p.nom).join(', ');
  }

  sautsTexte(c: ContactMeshtastic): string {
    const sauts = this.routesParNoeud.get(c.node_num)?.sauts;
    if (sauts === null || sauts === undefined) return 'hors de portée';
    return sauts === 1 ? 'direct' : `${sauts} sauts`;
  }

  /** Date de tri ; null quand elle manque, pour que le vide reste en dernier. */
  date(valeur: string | null | undefined): Date | null {
    return valeur ? new Date(valeur) : null;
  }

  dateTexte(valeur: string | null | undefined): string {
    return valeur ? new Date(valeur).toLocaleString('fr-FR') : '';
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.getAll().subscribe({
      next: (data) => { this.companions = data; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les companions.'; this.loading = false; },
    });
  }

  loadCanaux(): void {
    this.canalService.getAll().subscribe(data => { this.canaux = data; });
  }

  loadNoeuds(): void {
    this.noeudService.getAll().subscribe(data => { this.noeuds = data; });
  }

  /** Identifiant 32 bits aléatoire — cette identité n'a pas de matériel dont dériver un
   * node_num, contrairement à un vrai appareil (voir docstring du modèle CompagnonMeshtastic). */
  genererNodeNum(): void {
    this.nouveauNodeNum = Math.floor(Math.random() * 0xFFFFFFFF);
  }

  get formValide(): boolean {
    return !!this.nouveauNom.trim() && this.nouveauNodeNum != null && !!this.nouveauBrokerHost.trim();
  }

  get formDetectValide(): boolean {
    return !!this.detectIp.trim() && this.detectPort > 0;
  }

  detecterEtCreer(): void {
    if (!this.formDetectValide) return;
    this.detecting = true;
    this.detectError = '';
    this.detectResultat = '';
    this.detecterService.detecter(this.detectIp.trim(), this.detectPort, this.detectNom.trim()).subscribe({
      next: resultat => {
        this.detecting = false;
        if (resultat.type === 'meshtastic') {
          this.detectResultat = `Nœud Meshtastic détecté et ajouté : « ${resultat.nom} ».`;
          this.detectIp = '';
          this.detectNom = '';
          this.load();
        } else {
          this.detectResultat = `Nœud MeshCore détecté (pas Meshtastic) — ajouté dans « Companions MeshCore ».`;
        }
      },
      error: err => {
        this.detecting = false;
        this.detectError = err.error?.detail || "Aucun protocole n'a pu être identifié sur cette adresse.";
      },
    });
  }

  ajouter(): void {
    if (!this.formValide) return;
    this.creating = true;
    this.service.create({
      nom: this.nouveauNom.trim(),
      node_num: this.nouveauNodeNum!,
      long_name: this.nouveauLongName.trim(),
      short_name: this.nouveauShortName.trim(),
      broker_host: this.nouveauBrokerHost.trim(),
      broker_port: this.nouveauBrokerPort,
      topic_racine: this.nouveauTopicRacine.trim(),
      chiffrement_supporte: this.nouveauChiffrementSupporte,
      mqtt_username: this.nouveauMqttUsername.trim(),
      mqtt_password: this.nouveauMqttPassword,
      mqtt_use_tls: this.nouveauMqttUseTls,
    }).subscribe({
      next: (created) => {
        this.companions = [created, ...this.companions];
        this.nouveauNom = '';
        this.nouveauNodeNum = null;
        this.nouveauLongName = '';
        this.nouveauShortName = '';
        this.nouveauChiffrementSupporte = false;
        this.nouveauMqttUsername = '';
        this.nouveauMqttPassword = '';
        this.nouveauMqttUseTls = false;
        this.creating = false;
      },
      error: () => { this.errorMessage = 'Impossible de créer ce companion (node_num déjà utilisé ?).'; this.creating = false; },
    });
  }

  supprimer(companion: CompagnonMeshtastic): void {
    if (!confirm(`Supprimer le companion « ${companion.nom} » ?`)) return;
    this.service.delete(companion.id).subscribe(() => {
      this.companions = this.companions.filter(c => c.id !== companion.id);
    });
  }

  commencerEdition(c: CompagnonMeshtastic): void {
    this.editingCompanionId = c.id;
    this.editNom = c.nom;
    this.editBrokerHost = c.broker_host;
    this.editBrokerPort = c.broker_port;
    this.editTopicRacine = c.topic_racine;
    this.editChiffrementSupporte = c.chiffrement_supporte;
    this.editActif = c.actif;
    this.editMqttUsername = c.mqtt_username || '';
    // Le mot de passe n'est jamais renvoyé par l'API (write_only) — laissé vide, non modifié
    // à l'enregistrement sauf saisie explicite (voir enregistrerEdition).
    this.editMqttPassword = '';
    this.editMqttUseTls = c.mqtt_use_tls;
  }

  annulerEdition(): void {
    this.editingCompanionId = null;
  }

  enregistrerEdition(companion: CompagnonMeshtastic): void {
    this.saving = true;
    const payload: Partial<CompagnonMeshtastic> = {
      nom: this.editNom.trim(),
      broker_host: this.editBrokerHost.trim(),
      broker_port: this.editBrokerPort,
      topic_racine: this.editTopicRacine.trim(),
      chiffrement_supporte: this.editChiffrementSupporte,
      actif: this.editActif,
      mqtt_username: this.editMqttUsername.trim(),
      mqtt_use_tls: this.editMqttUseTls,
    };
    // Omis si non ressaisi : un PATCH sans la clé laisse le mot de passe enregistré inchangé
    // côté serveur, plutôt que de l'écraser par une chaîne vide à chaque édition.
    if (this.editMqttPassword) payload.mqtt_password = this.editMqttPassword;
    this.service.update(companion.id, payload).subscribe({
      next: (updated) => {
        this.companions = this.companions.map(c => c.id === updated.id ? updated : c);
        this.editingCompanionId = null;
        this.saving = false;
      },
      error: () => { this.errorMessage = 'Impossible de modifier ce companion.'; this.saving = false; },
    });
  }

  get formCanalValide(): boolean {
    return !!this.nouveauCanalNom.trim();
  }

  ajouterCanal(): void {
    if (!this.formCanalValide) return;
    this.creatingCanal = true;
    this.canalService.create({
      nom: this.nouveauCanalNom.trim(),
      psk_hex: this.nouveauCanalPsk.trim() || undefined,
      principal: this.nouveauCanalPrincipal,
      compagnon: this.nouveauCanalCompagnonId || null,
    }).subscribe({
      next: (created) => {
        this.canaux = [created, ...this.canaux];
        this.nouveauCanalNom = '';
        this.nouveauCanalPsk = '';
        this.nouveauCanalPrincipal = false;
        this.nouveauCanalCompagnonId = '';
        this.creatingCanal = false;
      },
      error: () => { this.errorMessage = 'Impossible de créer ce canal.'; this.creatingCanal = false; },
    });
  }

  supprimerCanal(canal: CanalMeshtastic): void {
    if (!confirm(`Supprimer le canal « ${canal.nom} » ?`)) return;
    this.canalService.delete(canal.id).subscribe({
      next: () => { this.canaux = this.canaux.filter(c => c.id !== canal.id); },
      error: () => { this.errorMessage = 'Impossible de supprimer ce canal.'; },
    });
  }

  get formNoeudValide(): boolean {
    return !!this.nouveauNoeudUtilisateurId && this.nouveauNoeudNodeNum != null;
  }

  attributionsParContact: Record<string, string> = {};
  attribuingContactId: string | null = null;

  attribuerContact(contact: ContactMeshtastic): void {
    const utilisateurId = this.attributionsParContact[contact.id];
    if (!utilisateurId) return;
    this.attribuingContactId = contact.id;
    this.noeudService.create({
      utilisateur: utilisateurId, node_num: contact.node_num, nom_noeud: contact.long_name,
    }).subscribe({
      next: (created) => {
        this.noeuds = [created, ...this.noeuds];
        delete this.attributionsParContact[contact.id];
        this.attribuingContactId = null;
        this.loadContacts();
      },
      error: () => {
        this.errorMessage = "Impossible d'attribuer ce nœud (déjà associé ?).";
        this.attribuingContactId = null;
      },
    });
  }

  ajouterNoeud(): void {
    if (!this.formNoeudValide) return;
    this.creatingNoeud = true;
    this.noeudService.create({
      utilisateur: this.nouveauNoeudUtilisateurId, node_num: this.nouveauNoeudNodeNum!, nom_noeud: this.nouveauNoeudNom.trim(),
    }).subscribe({
      next: (created) => {
        this.noeuds = [created, ...this.noeuds];
        this.nouveauNoeudUtilisateurId = '';
        this.nouveauNoeudNodeNum = null;
        this.nouveauNoeudNom = '';
        this.creatingNoeud = false;
        this.loadContacts();
      },
      error: () => { this.errorMessage = "Impossible d'associer ce nœud (déjà associé ?)."; this.creatingNoeud = false; },
    });
  }

  supprimerNoeud(noeud: NoeudUtilisateurMeshtastic): void {
    if (!confirm(`Retirer le nœud de « ${noeud.utilisateur_nom} » ?`)) return;
    this.noeudService.delete(noeud.id).subscribe(() => {
      this.noeuds = this.noeuds.filter(n => n.id !== noeud.id);
    });
  }

  statutClass(c: CompagnonMeshtastic): string {
    if (c.dernier_etat === 'CONNECTE') return 'statut-ok';
    if (c.dernier_etat === 'ERREUR') return 'statut-erreur';
    return 'statut-inconnu';
  }

  copierId(c: CompagnonMeshtastic): void {
    navigator.clipboard?.writeText(c.id).catch(() => {});
  }

  copierClePublique(c: CompagnonMeshtastic): void {
    if (c.x25519_public_key_hex) navigator.clipboard?.writeText(c.x25519_public_key_hex).catch(() => {});
  }

  nodeNumHex(n: number): string {
    return '!' + n.toString(16).padStart(8, '0');
  }
}
