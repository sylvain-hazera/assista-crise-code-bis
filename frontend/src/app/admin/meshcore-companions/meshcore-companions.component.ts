import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { RelaisMeshCoreService } from '../../services/relais-meshcore.service';
import { NoeudMeshUtilisateurService } from '../../services/noeud-mesh-utilisateur.service';
import { ContactMeshCoreService } from '../../services/contact-meshcore.service';
import { UserService } from '../../services/user.service';
import { CompagnonMeshCore, MeshCoreConnexionType } from '../../shared/models/compagnon-meshcore.model';
import { RelaisMeshCore } from '../../shared/models/relais-meshcore.model';
import { NoeudMeshUtilisateur } from '../../shared/models/noeud-mesh-utilisateur.model';
import { ContactMeshCore } from '../../shared/models/contact-meshcore.model';
import { User } from '../../shared/models/user.model';

/** Page de test MeshCore : juste de quoi déclarer un companion (nom + IP/port, ou device série,
 * ou adresse BLE) sans passer par le Django admin — voir meshcore-bridge/README.md pour le
 * service qui se connecte réellement dessus. Volontairement minimal (pas de gestion
 * d'institution ici) tant que le matériel n'a pas confirmé l'usage — voir doc de conception
 * « Maillage Terrain ». Reste sur la branche feature/meshcore-poc, jamais déployée sur .114. */
@Component({
  selector: 'app-meshcore-companions',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshcore-companions.component.html',
  styleUrl: './meshcore-companions.component.scss',
})
export class MeshcoreCompanionsComponent implements OnInit {

  companions: CompagnonMeshCore[] = [];
  loading = true;
  errorMessage = '';

  nouveauNom = '';
  nouveauType: MeshCoreConnexionType = 'TCP';
  nouveauHost = '';
  nouveauPort = 5000;
  nouveauDevice = '/dev/ttyUSB0';
  nouveauBle = '';
  creating = false;

  relais: RelaisMeshCore[] = [];
  nouveauRelaisNom = '';
  nouveauRelaisLat: number | null = null;
  nouveauRelaisLon: number | null = null;
  creatingRelais = false;

  noeuds: NoeudMeshUtilisateur[] = [];
  utilisateurs: User[] = [];
  nouveauNoeudUtilisateurId = '';
  nouveauNoeudPubkey = '';
  nouveauNoeudNom = '';
  creatingNoeud = false;

  contacts: ContactMeshCore[] = [];
  contactSelectionneId = '';
  importingRelais = false;

  constructor(
    private service: CompagnonMeshCoreService,
    private relaisService: RelaisMeshCoreService,
    private noeudService: NoeudMeshUtilisateurService,
    private contactService: ContactMeshCoreService,
    private userService: UserService,
  ) {}

  ngOnInit(): void {
    this.load();
    this.loadRelais();
    this.loadNoeuds();
    this.loadContacts();
    this.userService.getAll().subscribe(data => { this.utilisateurs = data; });
  }

  loadContacts(): void {
    this.contactService.getAll().subscribe(data => { this.contacts = data; });
  }

  /** Contacts de type Companion, pas encore associés à un compte — c'est ce qui alimente le
   * sélecteur de l'étape « Associer un nœud » ci-dessous, à la place d'une saisie manuelle de
   * clé publique. Répertoire déjà tenu par le firmware, synchronisé par le pont — voir
   * bridge.py, boucle_contacts. */
  get contactsDisponibles(): ContactMeshCore[] {
    return this.contacts.filter(c => c.type_contact === 'COMPANION' && !c.deja_associe);
  }

  get relaisDetectes(): ContactMeshCore[] {
    const nomsRelaisExistants = new Set(this.relais.map(r => r.nom));
    return this.contacts.filter(c => c.type_contact === 'REPEATER' && c.latitude != null && !nomsRelaisExistants.has(c.nom));
  }

  choisirContact(): void {
    const contact = this.contacts.find(c => c.id === this.contactSelectionneId);
    if (!contact) return;
    this.nouveauNoeudPubkey = contact.pubkey_hex;
    this.nouveauNoeudNom = contact.nom;
  }

  importerRelaisDetectes(): void {
    const aImporter = this.relaisDetectes;
    if (aImporter.length === 0) return;
    this.importingRelais = true;
    let restant = aImporter.length;
    aImporter.forEach(contact => {
      this.relaisService.create({
        nom: contact.nom || `Relais ${contact.pubkey_hex.slice(0, 8)}`,
        latitude: contact.latitude!, longitude: contact.longitude!,
        pubkey_hex: contact.pubkey_hex,
      }).subscribe({
        next: (created) => {
          this.relais = [created, ...this.relais];
          restant--;
          if (restant === 0) this.importingRelais = false;
        },
        error: () => {
          restant--;
          if (restant === 0) this.importingRelais = false;
        },
      });
    });
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.getAll().subscribe({
      next: (data) => { this.companions = data; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les companions.'; this.loading = false; },
    });
  }

  loadRelais(): void {
    this.relaisService.getAll().subscribe(data => { this.relais = data; });
  }

  loadNoeuds(): void {
    this.noeudService.getAll().subscribe(data => { this.noeuds = data; });
  }

  get formRelaisValide(): boolean {
    return !!this.nouveauRelaisNom.trim() && this.nouveauRelaisLat != null && this.nouveauRelaisLon != null;
  }

  ajouterRelais(): void {
    if (!this.formRelaisValide) return;
    this.creatingRelais = true;
    this.relaisService.create({
      nom: this.nouveauRelaisNom.trim(), latitude: this.nouveauRelaisLat!, longitude: this.nouveauRelaisLon!,
    }).subscribe({
      next: (created) => {
        this.relais = [created, ...this.relais];
        this.nouveauRelaisNom = '';
        this.nouveauRelaisLat = null;
        this.nouveauRelaisLon = null;
        this.creatingRelais = false;
      },
      error: () => { this.errorMessage = 'Impossible de créer ce relais.'; this.creatingRelais = false; },
    });
  }

  supprimerRelais(relais: RelaisMeshCore): void {
    if (!confirm(`Supprimer le relais « ${relais.nom} » ?`)) return;
    this.relaisService.delete(relais.id).subscribe(() => {
      this.relais = this.relais.filter(r => r.id !== relais.id);
    });
  }

  get formNoeudValide(): boolean {
    return !!this.nouveauNoeudUtilisateurId && !!this.nouveauNoeudPubkey.trim();
  }

  ajouterNoeud(): void {
    if (!this.formNoeudValide) return;
    this.creatingNoeud = true;
    this.noeudService.create({
      utilisateur: this.nouveauNoeudUtilisateurId, pubkey_hex: this.nouveauNoeudPubkey.trim(), nom_noeud: this.nouveauNoeudNom.trim(),
    }).subscribe({
      next: (created) => {
        this.noeuds = [created, ...this.noeuds];
        this.nouveauNoeudUtilisateurId = '';
        this.nouveauNoeudPubkey = '';
        this.nouveauNoeudNom = '';
        this.contactSelectionneId = '';
        this.creatingNoeud = false;
        this.loadContacts();
      },
      error: () => { this.errorMessage = "Impossible d'associer ce nœud (clé publique déjà utilisée ?)."; this.creatingNoeud = false; },
    });
  }

  supprimerNoeud(noeud: NoeudMeshUtilisateur): void {
    if (!confirm(`Retirer le nœud de « ${noeud.utilisateur_nom} » ?`)) return;
    this.noeudService.delete(noeud.id).subscribe(() => {
      this.noeuds = this.noeuds.filter(n => n.id !== noeud.id);
    });
  }

  get formValide(): boolean {
    if (!this.nouveauNom.trim()) return false;
    if (this.nouveauType === 'TCP') return !!this.nouveauHost.trim() && !!this.nouveauPort;
    if (this.nouveauType === 'SERIE') return !!this.nouveauDevice.trim();
    if (this.nouveauType === 'BLE') return !!this.nouveauBle.trim();
    return false;
  }

  ajouter(): void {
    if (!this.formValide) return;

    const payload: Partial<CompagnonMeshCore> = {
      nom: this.nouveauNom.trim(),
      connexion_type: this.nouveauType,
    };
    if (this.nouveauType === 'TCP') {
      payload.tcp_host = this.nouveauHost.trim();
      payload.tcp_port = this.nouveauPort;
    } else if (this.nouveauType === 'SERIE') {
      payload.serie_device = this.nouveauDevice.trim();
    } else if (this.nouveauType === 'BLE') {
      payload.ble_adresse = this.nouveauBle.trim();
    }

    this.creating = true;
    this.service.create(payload).subscribe({
      next: (created) => {
        this.companions = [created, ...this.companions];
        this.nouveauNom = '';
        this.nouveauHost = '';
        this.nouveauBle = '';
        this.creating = false;
      },
      error: () => { this.errorMessage = "Impossible de créer ce companion."; this.creating = false; },
    });
  }

  supprimer(companion: CompagnonMeshCore): void {
    if (!confirm(`Supprimer le companion « ${companion.nom} » ?`)) return;
    this.service.delete(companion.id).subscribe(() => {
      this.companions = this.companions.filter(c => c.id !== companion.id);
    });
  }

  adresse(c: CompagnonMeshCore): string {
    if (c.connexion_type === 'TCP') return `${c.tcp_host}:${c.tcp_port}`;
    if (c.connexion_type === 'SERIE') return c.serie_device || '—';
    return c.ble_adresse || '—';
  }

  statutClass(c: CompagnonMeshCore): string {
    if (c.dernier_etat === 'CONNECTE') return 'statut-ok';
    if (c.dernier_etat === 'ERREUR') return 'statut-erreur';
    return 'statut-inconnu';
  }

  copierId(c: CompagnonMeshCore): void {
    navigator.clipboard?.writeText(c.id).catch(() => {});
  }
}
