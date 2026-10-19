import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { MeshLocalDetecterService } from '../../services/mesh-local-detecter.service';
import { RelaisMeshCoreService } from '../../services/relais-meshcore.service';
import { NoeudMeshUtilisateurService } from '../../services/noeud-mesh-utilisateur.service';
import { ContactMeshCoreService, AnalyseSecuriteMeshCore } from '../../services/contact-meshcore.service';
import { TracerouteMeshCoreService } from '../../services/traceroute-meshcore.service';
import { AlerteMeshSOSService } from '../../services/alerte-sos-mesh.service';
import { AlerteMeshSOS } from '../../shared/models/alerte-sos-mesh.model';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../auth/services/auth.service';
import { CompagnonMeshCore, MeshCoreConnexionType } from '../../shared/models/compagnon-meshcore.model';
import { RelaisMeshCore } from '../../shared/models/relais-meshcore.model';
import { NoeudMeshUtilisateur } from '../../shared/models/noeud-mesh-utilisateur.model';
import { ContactMeshCore, TracerouteMeshCore, SautTraceroute } from '../../shared/models/contact-meshcore.model';
import { User } from '../../shared/models/user.model';

type Direction = 'asc' | 'desc';

/** Ligne de la table « Répéteurs & infrastructure » : RelaisMeshCore (position connue) et
 * ContactMeshCore non-COMPANION pas encore promus (sans GPS). */
interface LigneInfrastructure {
  id: string;
  relaisId: string | null;
  nom: string;
  typeLabel: string;
  pubkeyHex: string | null;
  latitude: number | null;
  longitude: number | null;
  dernierContact: string | null;
  nombreSauts: number | null;
  regionTag: string | null;
  actif: boolean | null;
}

/** Configuration MeshCore minimale (companions, contacts, répéteurs) sans passer par le Django
 * admin. Voir meshcore-bridge/README.md. */
@Component({
  selector: 'app-meshcore-companions',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshcore-companions.component.html',
  styleUrl: './meshcore-companions.component.scss',
})
export class MeshcoreCompanionsComponent implements OnInit, OnDestroy {

  companions: CompagnonMeshCore[] = [];
  loading = true;
  errorMessage = '';

  nouveauNom = '';
  nouveauType: MeshCoreConnexionType = 'TCP';
  nouveauHost = '';
  nouveauPort = 5000;
  nouveauDevice = '/dev/ttyUSB0';
  nouveauBle = '';
  // Position facultative du companion, affichée sur la carte.
  nouveauLat: number | null = null;
  nouveauLon: number | null = null;
  // Convention communautaire de canal régional (ex: "fr-naq"), pas une notion MeshCore.
  nouveauRegion = '';
  creating = false;

  regionEnCoursEdition: Record<string, string> = {};
  savingRegion: string | null = null;

  // Détection automatique (hors ligne) : IP + port, le serveur essaie Meshtastic puis MeshCore
  // (MeshLocalDetecterService).
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
  analyseSecurite: AnalyseSecuriteMeshCore | null = null;
  /** Admins seulement (AlerteMeshSOSViewSet) : jamais interrogé pour les autres (403). */
  alertesSOS: AlerteMeshSOS[] = [];

  companionRecherche = '';
  companionTri: 'nom' | 'derniere_connexion' = 'nom';
  companionDirection: Direction = 'asc';

  infraRecherche = '';
  infraTri: 'nom' | 'dernierContact' | 'nombreSauts' = 'nom';
  infraDirection: Direction = 'asc';

  /** Page bloquée en zone DEMO (BlockedInDemoMixin) : aucune requête émise, message affiché. */
  isDemo = false;

  constructor(
    private service: CompagnonMeshCoreService,
    private detecterService: MeshLocalDetecterService,
    private relaisService: RelaisMeshCoreService,
    private noeudService: NoeudMeshUtilisateurService,
    private contactService: ContactMeshCoreService,
    private tracerouteService: TracerouteMeshCoreService,
    private alerteSOSService: AlerteMeshSOSService,
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
    this.loadAnalyseSecurite();
    if (this.authService.isAdmin()) this.loadAlertesSOS();
    this.userService.getAll().subscribe(data => { this.utilisateurs = data; });
  }

  private loadAlertesSOS(): void {
    this.alerteSOSService.getAll().subscribe({
      next: (data) => { this.alertesSOS = data; },
      error: () => { /* non bloquant -- simple complément d'information */ },
    });
  }

  ngOnDestroy(): void {
    if (this.tracerouteSondage) clearInterval(this.tracerouteSondage);
  }

  loadContacts(): void {
    this.contactService.getAll().subscribe(data => { this.contacts = data; });
  }

  loadAnalyseSecurite(): void {
    this.contactService.analyseSecurite().subscribe({
      next: (data) => { this.analyseSecurite = data; },
      error: () => { /* non bloquant -- simple complément d'information */ },
    });
  }

  /** Companions personnels non associés (type COMPANION seulement ; répéteurs dans
   * lignesInfrastructure). Synchronisés par le pont (bridge.py, boucle_contacts). */
  get contactsDisponibles(): ContactMeshCore[] {
    return this.contacts.filter(c => c.type_contact === 'COMPANION' && !c.deja_associe);
  }

  /** Tri : une valeur manquante va toujours en fin de liste, quel que soit le sens. */
  private comparer(a: string | number | null | undefined, b: string | number | null | undefined, direction: Direction): number {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    const resultat = a < b ? -1 : a > b ? 1 : 0;
    return direction === 'asc' ? resultat : -resultat;
  }

  /** Flèche de tri, seulement sur la colonne triée. */
  indicateurTri(colonneActuelle: string, colonneAffichee: string, direction: Direction): string {
    if (colonneActuelle !== colonneAffichee) return '';
    return direction === 'asc' ? '▲' : '▼';
  }

  trierCompagnons(colonne: 'nom' | 'derniere_connexion'): void {
    if (this.companionTri === colonne) {
      this.companionDirection = this.companionDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.companionTri = colonne;
      this.companionDirection = 'asc';
    }
  }

  get companionsAffiches(): CompagnonMeshCore[] {
    const recherche = this.companionRecherche.trim().toLowerCase();
    let liste = this.companions;
    if (recherche) {
      liste = liste.filter(c =>
        c.nom.toLowerCase().includes(recherche) || this.adresse(c).toLowerCase().includes(recherche),
      );
    }
    return [...liste].sort((a, b) => {
      if (this.companionTri === 'nom') return this.comparer(a.nom.toLowerCase(), b.nom.toLowerCase(), this.companionDirection);
      return this.comparer(a.derniere_connexion, b.derniere_connexion, this.companionDirection);
    });
  }

  trierInfrastructure(colonne: 'nom' | 'dernierContact' | 'nombreSauts'): void {
    if (this.infraTri === colonne) {
      this.infraDirection = this.infraDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.infraTri = colonne;
      this.infraDirection = 'asc';
    }
  }

  /** Répéteurs promus enrichis par le ContactMeshCore de même pubkey_hex ; les non promus
   * apparaissent sans position. */
  get lignesInfrastructure(): LigneInfrastructure[] {
    const parPubkey = new Map<string, ContactMeshCore>();
    for (const c of this.contacts) {
      if (c.type_contact !== 'COMPANION' && c.pubkey_hex) parPubkey.set(c.pubkey_hex, c);
    }
    const pubkeysCouverts = new Set<string>();
    const lignes: LigneInfrastructure[] = [];

    for (const r of this.relais) {
      const contact = r.pubkey_hex ? parPubkey.get(r.pubkey_hex) : undefined;
      if (r.pubkey_hex) pubkeysCouverts.add(r.pubkey_hex);
      lignes.push({
        id: r.id,
        relaisId: r.id,
        nom: r.nom,
        typeLabel: contact ? this.typeContactLabel(contact.type_contact) : 'Répéteur',
        pubkeyHex: r.pubkey_hex ?? null,
        latitude: r.latitude ?? null,
        longitude: r.longitude ?? null,
        dernierContact: contact?.dernier_advert ?? null,
        nombreSauts: contact?.nombre_sauts ?? null,
        regionTag: contact?.region_tag ?? null,
        actif: r.actif,
      });
    }

    for (const c of this.contacts) {
      if (c.type_contact === 'COMPANION') continue;
      if (c.pubkey_hex && pubkeysCouverts.has(c.pubkey_hex)) continue;
      lignes.push({
        id: c.id,
        relaisId: null,
        nom: c.nom || '(sans nom annoncé)',
        typeLabel: this.typeContactLabel(c.type_contact),
        pubkeyHex: c.pubkey_hex,
        latitude: c.latitude ?? null,
        longitude: c.longitude ?? null,
        dernierContact: c.dernier_advert ?? null,
        nombreSauts: c.nombre_sauts ?? null,
        regionTag: c.region_tag ?? null,
        actif: null,
      });
    }

    const recherche = this.infraRecherche.trim().toLowerCase();
    let filtrees = lignes;
    if (recherche) {
      filtrees = filtrees.filter(l =>
        l.nom.toLowerCase().includes(recherche)
        || (l.pubkeyHex || '').toLowerCase().includes(recherche)
        || (l.regionTag || '').toLowerCase().includes(recherche),
      );
    }
    return filtrees.sort((a, b) => {
      if (this.infraTri === 'nom') return this.comparer(a.nom.toLowerCase(), b.nom.toLowerCase(), this.infraDirection);
      if (this.infraTri === 'nombreSauts') return this.comparer(a.nombreSauts, b.nombreSauts, this.infraDirection);
      return this.comparer(a.dernierContact, b.dernierContact, this.infraDirection);
    });
  }

  /** Une ligne non promue est un ContactMeshCore synchronisé, jamais supprimé par le pont :
   * pas de bouton Supprimer. */
  supprimerLigneInfrastructure(ligne: LigneInfrastructure): void {
    if (!ligne.relaisId) return;
    const relais = this.relais.find(r => r.id === ligne.relaisId);
    if (relais) this.supprimerRelais(relais);
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

  /** Utilisateur choisi par contact non associé, un choix par ligne. */
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
    if (this.nouveauRegion.trim()) {
      payload.region_tag = this.nouveauRegion.trim();
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
        this.nouveauRegion = '';
        this.creating = false;
      },
      error: () => { this.errorMessage = "Impossible de créer ce companion."; this.creating = false; },
    });
  }

  /** Édition en ligne de la région d'un companion. */
  regionEditee(companion: CompagnonMeshCore): string {
    return this.regionEnCoursEdition[companion.id] ?? companion.region_tag ?? '';
  }

  enregistrerRegion(companion: CompagnonMeshCore): void {
    const valeur = (this.regionEnCoursEdition[companion.id] ?? '').trim();
    this.savingRegion = companion.id;
    this.service.update(companion.id, { region_tag: valeur }).subscribe({
      next: (mis_a_jour) => {
        companion.region_tag = mis_a_jour.region_tag;
        delete this.regionEnCoursEdition[companion.id];
        this.savingRegion = null;
      },
      error: () => {
        this.errorMessage = "Impossible d'enregistrer la région de ce companion.";
        this.savingRegion = null;
      },
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

  // Advert : commande mise en file, exécutée par le pont à son prochain cycle (quelques secondes).
  // Un seul en vol par companion.
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

  // Traceroute : même file d'attente ; historique relu toutes les 4 s jusqu'à la réponse ou
  // une limite de tentatives (pont hors ligne).
  tracerouteCompagnonId: string | null = null;
  tracerouteResultats: TracerouteMeshCore[] = [];
  tracerouteEnCours: string | null = null;
  tracerouteErreur = '';
  private tracerouteSondage: ReturnType<typeof setInterval> | null = null;

  lancerTraceroute(companion: CompagnonMeshCore): void {
    this.tracerouteCompagnonId = companion.id;
    this.tracerouteEnCours = companion.id;
    this.tracerouteErreur = '';
    this.tracerouteResultats = [];
    if (this.tracerouteSondage) clearInterval(this.tracerouteSondage);

    this.tracerouteService.lancer(companion.id).subscribe({
      next: () => {
        let tentatives = 0;
        this.tracerouteSondage = setInterval(() => {
          tentatives++;
          this.tracerouteService.getHistorique(companion.id).subscribe({
            next: (data) => {
              this.tracerouteResultats = data;
              const enCours = data[0]?.statut === 'EN_ATTENTE';
              if (!enCours || tentatives >= 10) {
                this.tracerouteEnCours = null;
                if (this.tracerouteSondage) clearInterval(this.tracerouteSondage);
              }
            },
            error: () => { /* on retentera au prochain cycle */ },
          });
        }, 4000);
      },
      error: (err) => {
        this.tracerouteEnCours = null;
        this.tracerouteErreur = err.error?.detail || "Impossible de lancer ce traceroute.";
      },
    });
  }

  libelleChemin(chemin: SautTraceroute[]): string {
    // Le dernier saut n'a pas de hash (réception par notre companion, TracerouteMeshCore.chemin).
    return chemin
      .map(saut => saut.hash ? `#${saut.hash} (${saut.snr.toFixed(1)} dB)` : `Companion (${saut.snr.toFixed(1)} dB)`)
      .join(' → ');
  }
}
