import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CompagnonMeshtasticService } from '../../services/compagnon-meshtastic.service';
import { CanalMeshtasticService } from '../../services/canal-meshtastic.service';
import { ContactMeshtasticService } from '../../services/contact-meshtastic.service';
import { NoeudUtilisateurMeshtasticService } from '../../services/noeud-utilisateur-meshtastic.service';
import { UserService } from '../../services/user.service';
import { CompagnonMeshtastic } from '../../shared/models/compagnon-meshtastic.model';
import { CanalMeshtastic } from '../../shared/models/canal-meshtastic.model';
import { ContactMeshtastic } from '../../shared/models/contact-meshtastic.model';
import { NoeudUtilisateurMeshtastic } from '../../shared/models/noeud-utilisateur-meshtastic.model';
import { User } from '../../shared/models/user.model';

/** Page de paramétrage Meshtastic : déclarer une identité de nœud logicielle (companion, sans
 * matériel — voir meshtastic-bridge/README.md), des canaux (PSK partagée), et associer les
 * nœuds détectés sur le mesh à des comptes utilisateurs. Le chiffrement (PSK canal, PKI) est
 * réimplémenté à la main et non fiable sur tous les brokers (ex: Gaulix, voir
 * CompagnonMeshtastic.chiffrement_supporte) : à manier avec précaution. */
@Component({
  selector: 'app-meshtastic-companions',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshtastic-companions.component.html',
  styleUrl: './meshtastic-companions.component.scss',
})
export class MeshtasticCompanionsComponent implements OnInit {

  companions: CompagnonMeshtastic[] = [];
  loading = true;
  errorMessage = '';

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
  creating = false;

  editingCompanionId: string | null = null;
  editNom = '';
  editBrokerHost = '';
  editBrokerPort = 1883;
  editTopicRacine = '';
  editChiffrementSupporte = false;
  editActif = true;
  saving = false;

  canaux: CanalMeshtastic[] = [];
  nouveauCanalNom = '';
  nouveauCanalPsk = '';
  nouveauCanalPrincipal = false;
  creatingCanal = false;

  noeuds: NoeudUtilisateurMeshtastic[] = [];
  utilisateurs: User[] = [];
  nouveauNoeudUtilisateurId = '';
  nouveauNoeudNodeNum: number | null = null;
  nouveauNoeudNom = '';
  creatingNoeud = false;

  contacts: ContactMeshtastic[] = [];

  constructor(
    private service: CompagnonMeshtasticService,
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
    this.userService.getAll().subscribe(data => { this.utilisateurs = data; });
  }

  loadContacts(): void {
    this.contactService.getAll().subscribe(data => { this.contacts = data; });
  }

  /** Contacts pas encore associés à un compte — alimente le sélecteur d'attribution rapide. */
  get contactsDisponibles(): ContactMeshtastic[] {
    return this.contacts.filter(c => !c.deja_associe);
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
    }).subscribe({
      next: (created) => {
        this.companions = [created, ...this.companions];
        this.nouveauNom = '';
        this.nouveauNodeNum = null;
        this.nouveauLongName = '';
        this.nouveauShortName = '';
        this.nouveauChiffrementSupporte = false;
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
  }

  annulerEdition(): void {
    this.editingCompanionId = null;
  }

  enregistrerEdition(companion: CompagnonMeshtastic): void {
    this.saving = true;
    this.service.update(companion.id, {
      nom: this.editNom.trim(),
      broker_host: this.editBrokerHost.trim(),
      broker_port: this.editBrokerPort,
      topic_racine: this.editTopicRacine.trim(),
      chiffrement_supporte: this.editChiffrementSupporte,
      actif: this.editActif,
    }).subscribe({
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
    }).subscribe({
      next: (created) => {
        this.canaux = [created, ...this.canaux];
        this.nouveauCanalNom = '';
        this.nouveauCanalPsk = '';
        this.nouveauCanalPrincipal = false;
        this.creatingCanal = false;
      },
      error: () => { this.errorMessage = 'Impossible de créer ce canal.'; this.creatingCanal = false; },
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
