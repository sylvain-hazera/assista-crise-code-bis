import { Component, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TeamService } from '../../../services/team.service';
import { NoeudMeshUtilisateurService } from '../../../services/noeud-mesh-utilisateur.service';
import { CompagnonMeshCoreService } from '../../../services/compagnon-meshcore.service';
import { MessageMeshService } from '../../../services/message-mesh.service';
import { CanalMeshCoreService } from '../../../services/canal-meshcore.service';
import { NoeudMeshUtilisateur } from '../../../shared/models/noeud-mesh-utilisateur.model';
import { CompagnonMeshCore } from '../../../shared/models/compagnon-meshcore.model';
import { MessageMeshLog, MessageCanalMeshCore } from '../../../shared/models/canal-meshcore.model';

/** DM privés régulateur <-> équipe, uniquement si au moins un membre de l'équipe a un
 * companion MeshCore personnel associé (voir /admin/meshcore-companions, section « Nœuds »).
 * La visibilité réelle de ces messages est imposée côté serveur (leader/régulateur de CETTE
 * équipe uniquement, voir MessageMeshLogViewSet) — ce composant se contente d'afficher ce que
 * l'API accepte de renvoyer, il n'invente pas de restriction supplémentaire côté client. */
@Component({
  selector: 'app-equipe-messagerie-mesh',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './equipe-messagerie-mesh.component.html',
  styleUrl: './equipe-messagerie-mesh.component.scss',
})
export class EquipeMessagerieMeshComponent implements OnChanges, OnDestroy {

  @Input() equipeId!: string;
  /** Canal d'équipe (voir TeamViewSet.provisionner_canal_meshcore) — ses messages sont
   * fusionnés avec les DM dans le même fil, si fourni. */
  @Input() canalId?: string | null;

  chargement = true;
  equipee = false;
  noeudsEquipe: NoeudMeshUtilisateur[] = [];
  compagnons: CompagnonMeshCore[] = [];
  messagesDm: MessageMeshLog[] = [];
  messagesCanal: MessageCanalMeshCore[] = [];
  erreur = '';

  destinataireId = '';
  compagnonId = '';
  nouveauMessage = '';
  envoiEnCours = false;

  private intervalRafraichissement: ReturnType<typeof setInterval> | null = null;

  constructor(
    private teamService: TeamService,
    private noeudService: NoeudMeshUtilisateurService,
    private compagnonService: CompagnonMeshCoreService,
    private messageService: MessageMeshService,
    private canalService: CanalMeshCoreService,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['equipeId'] && this.equipeId) {
      this.charger();
      if (this.intervalRafraichissement) clearInterval(this.intervalRafraichissement);
      this.intervalRafraichissement = setInterval(() => this.chargerMessages(false), 8000);
    }
  }

  ngOnDestroy(): void {
    if (this.intervalRafraichissement) clearInterval(this.intervalRafraichissement);
  }

  private charger(): void {
    this.chargement = true;
    this.teamService.getById(this.equipeId).subscribe({
      next: (equipe) => {
        const membresIds = new Set((equipe.members_info || []).map(m => m.id));
        this.noeudService.getAll().subscribe(noeuds => {
          this.noeudsEquipe = noeuds.filter(n => n.actif && membresIds.has(n.utilisateur));
          this.equipee = this.noeudsEquipe.length > 0;
          if (this.equipee) {
            this.destinataireId = this.noeudsEquipe[0].id;
            this.compagnonService.getAll().subscribe(compagnons => {
              this.compagnons = compagnons.filter(c => c.actif);
              this.compagnonId = this.compagnons.find(c => c.principal)?.id || this.compagnons[0]?.id || '';
            });
          }
          // Le canal d'équipe reste affiché même sans membre équipé d'un nœud personnel —
          // seule la composition d'un DM (destinataire) en dépend.
          this.chargerMessages(true);
        });
      },
      error: () => { this.erreur = "Impossible de vérifier l'équipement MeshCore de cette équipe."; this.chargement = false; },
    });
  }

  chargerMessages(avecSpinner: boolean): void {
    if (avecSpinner) this.chargement = true;
    this.messageService.getPourEquipe(this.equipeId).subscribe({
      next: (data) => { this.messagesDm = data; if (!this.canalId) this.chargement = false; },
      error: () => { if (avecSpinner && !this.canalId) this.chargement = false; },
    });
    if (this.canalId) {
      this.canalService.getMessages(this.canalId).subscribe({
        next: (data) => { this.messagesCanal = data; this.chargement = false; },
        error: () => { this.chargement = false; },
      });
    }
  }

  get destinatairePubkey(): string | null {
    return this.noeudsEquipe.find(n => n.id === this.destinataireId)?.pubkey_hex || null;
  }

  /** Nom lisible de la personne de terrain associée à ce nœud — utilisé pour afficher
   * clairement "à qui" un DM sortant a été adressé et "qui" a répondu, un fil de DM
   * d'équipe mélangeant potentiellement plusieurs membres équipés d'un nœud personnel. */
  private nomPourPubkey(pubkeyHex: string): string {
    const noeud = this.noeudsEquipe.find(n => n.pubkey_hex === pubkeyHex);
    return noeud?.utilisateur_nom || noeud?.nom_noeud || pubkeyHex.slice(0, 8);
  }

  /** Ligne d'attribution d'un DM : "Moi → <destinataire>" (sortant) ou "<expéditeur> → Moi"
   * (entrant) — remarque explicite : sans ça, impossible de savoir à qui un message sortant
   * était adressé, ou qui a répondu, dès que l'équipe a plus d'un membre équipé. */
  attributionDm(m: MessageMeshLog): string {
    const autre = this.nomPourPubkey(m.contact_pubkey_hex);
    return m.direction === 'SORTANT' ? `Moi → ${autre}` : `${m.expediteur_nom || autre} → Moi`;
  }

  envoyer(): void {
    if (!this.nouveauMessage.trim() || !this.compagnonId || !this.destinatairePubkey) return;
    this.envoiEnCours = true;
    this.messageService.envoyer(this.compagnonId, this.destinatairePubkey, this.nouveauMessage.trim()).subscribe({
      next: (message) => {
        this.messagesDm = [...this.messagesDm, message];
        this.nouveauMessage = '';
        this.envoiEnCours = false;
      },
      error: () => { this.erreur = "Échec de l'envoi du message."; this.envoiEnCours = false; },
    });
  }
}
