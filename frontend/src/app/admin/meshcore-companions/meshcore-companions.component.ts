import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { MeshLocalDetecterService } from '../../services/mesh-local-detecter.service';
import { RelaisMeshCoreService } from '../../services/relais-meshcore.service';
import { NoeudMeshUtilisateurService } from '../../services/noeud-mesh-utilisateur.service';
import { ContactMeshCoreService } from '../../services/contact-meshcore.service';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../auth/services/auth.service';
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
  // Position du companion physique (poste de commandement, véhicule...) : optionnelle, pour
  // l'afficher sur la carte au même titre qu'un relais (voir map.component.ts).
  nouveauLat: number | null = null;
  nouveauLon: number | null = null;
  creating = false;

  // Détection automatique (usage offline, sans internet) : on donne juste IP + port d'un vrai
  // appareil, le serveur essaie une vraie connexion Meshtastic puis MeshCore et crée le
  // companion correspondant tout seul — voir MeshLocalDetecterService.
  detectIp = '';
  detectPort = 5000;
  detectNom = '';
  detecting = false;
  detectError = '';
  detectResultat = '';

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

  /** Paramétrage/affectation MeshCore jamais consultable ni modifiable depuis la zone DEMO
   * (voir BlockedInDemoMixin côté serveur, CompagnonMeshCoreViewSet/NoeudMeshUtilisateurViewSet
   * — demande explicite du 14/09) : on évite même d'émettre les requêtes (403 systématique)
   * pour afficher un message clair plutôt qu'un chargement qui échoue silencieusement. Les
   * nœuds restent néanmoins bien affectés et joignables ailleurs (carte, messagerie d'équipe),
   * seule CETTE page de configuration est bloquée. */
  isDemo = false;

  constructor(
    private service: CompagnonMeshCoreService,
    private detecterService: MeshLocalDetecterService,
    private relaisService: RelaisMeshCoreService,
    private noeudService: NoeudMeshUtilisateurService,
    private contactService: ContactMeshCoreService,
    private userService: UserService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.isDemo = this.authService.getEnvironment() === 'DEMO';
    if (this.isDemo) {
      this.loading = false;
      return;
    }
    this.load();
    this.loadRelais();
    this.loadNoeuds();
    this.loadContacts();
    this.userService.getAll().subscribe(data => { this.utilisateurs = data; });
  }

  loadContacts(): void {
    this.contactService.getAll().subscribe(data => { this.contacts = data; });
  }

  /** Contacts pas encore associés à un compte, tous rôles confondus (companion/répéteur/room
   * server/capteur — décision utilisateur du 2026-09-18 : la visibilité "dernier contact" doit
   * couvrir tout le mesh, pas seulement les companions personnels) — alimente à la fois la
   * vue de supervision et le sélecteur de l'étape « Associer un nœud » ci-dessous (attribuer
   * un rôle non-COMPANION à un utilisateur n'a pas vraiment de sens, mais rester un seul
   * tableau plutôt que d'en dupliquer un second identique était le choix retenu). Répertoire
   * déjà tenu par le firmware, synchronisé par le pont — voir bridge.py, boucle_contacts. */
  get contactsDisponibles(): ContactMeshCore[] {
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

  /** Utilisateur choisi pour chaque contact détecté non associé, en attente d'attribution —
   * un choix par ligne du tableau (voir attributionsPubkeys ci-dessous), plutôt qu'un unique
   * formulaire séquentiel (choisir un contact, puis l'utilisateur, puis valider). */
  attributionsParContact: Record<string, string> = {};
  attribuingContactId: string | null = null;

  attribuerContact(contact: ContactMeshCore): void {
    const utilisateurId = this.attributionsParContact[contact.id];
    if (!utilisateurId) return;
    this.attribuingContactId = contact.id;
    this.noeudService.create({
      utilisateur: utilisateurId, pubkey_hex: contact.pubkey_hex, nom_noeud: contact.nom,
    }).subscribe({
      next: (created) => {
        this.noeuds = [created, ...this.noeuds];
        delete this.attributionsParContact[contact.id];
        this.attribuingContactId = null;
        this.loadContacts();
      },
      error: () => {
        this.errorMessage = "Impossible d'attribuer ce nœud (clé publique déjà utilisée ?).";
        this.attribuingContactId = null;
      },
    });
  }

  typeContactLabel(type: ContactMeshCore['type_contact']): string {
    const libelles: Record<ContactMeshCore['type_contact'], string> = {
      COMPANION: 'Companion', REPEATER: 'Répéteur', ROOM: 'Room server',
      SENSOR: 'Capteur', INCONNU: 'Inconnu',
    };
    return libelles[type] ?? type;
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
        if (resultat.type === 'meshcore') {
          this.detectResultat = `Nœud MeshCore détecté et ajouté : « ${resultat.nom} ».`;
          this.detectIp = '';
          this.detectNom = '';
          this.load();
        } else {
          this.detectResultat = `Nœud Meshtastic détecté (pas MeshCore) — ajouté dans « Companions Meshtastic ».`;
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
    if (this.nouveauLat != null && this.nouveauLon != null) {
      payload.latitude = this.nouveauLat;
      payload.longitude = this.nouveauLon;
    }

    this.creating = true;
    this.service.create(payload).subscribe({
      next: (created) => {
        this.companions = [created, ...this.companions];
        this.nouveauNom = '';
        this.nouveauHost = '';
        this.nouveauBle = '';
        this.nouveauLat = null;
        this.nouveauLon = null;
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

  // Advert / flood advert : programme la commande côté API, exécutée par le pont à son
  // prochain cycle d'interrogation (quelques secondes, pas immédiat) — voir
  // CompagnonMeshCoreService.envoyerAdvert. Un seul en vol à la fois par companion pour
  // désactiver le bouton pendant l'attente, pas pour empêcher plusieurs companions en //.
  advertEnCours: string | null = null;
  advertMessage = '';
  advertErreur = '';

  envoyerAdvert(companion: CompagnonMeshCore, flood: boolean): void {
    this.advertEnCours = companion.id;
    this.advertMessage = '';
    this.advertErreur = '';
    this.service.envoyerAdvert(companion.id, flood).subscribe({
      next: () => {
        this.advertEnCours = null;
        this.advertMessage = `${flood ? 'Flood advert' : 'Advert'} programmé pour « ${companion.nom} » — exécuté par le pont dans les prochaines secondes.`;
      },
      error: (err) => {
        this.advertEnCours = null;
        this.advertErreur = err.error?.detail || "Impossible de programmer cet advert.";
      },
    });
  }
}
