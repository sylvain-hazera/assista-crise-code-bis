import { Component, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { TeamService } from '../../../services/team.service';
import { NoeudMeshUtilisateurService } from '../../../services/noeud-mesh-utilisateur.service';
import { CompagnonMeshCoreService } from '../../../services/compagnon-meshcore.service';
import { MessageMeshService } from '../../../services/message-mesh.service';
import { NoeudMeshUtilisateur } from '../../../shared/models/noeud-mesh-utilisateur.model';
import { CompagnonMeshCore } from '../../../shared/models/compagnon-meshcore.model';
import { MessageMeshLog } from '../../../shared/models/canal-meshcore.model';

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

  chargement = true;
  equipee = false;
  noeudsEquipe: NoeudMeshUtilisateur[] = [];
  compagnons: CompagnonMeshCore[] = [];
  messages: MessageMeshLog[] = [];
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
              this.chargerMessages(true);
            });
          } else {
            this.chargement = false;
          }
        });
      },
      error: () => { this.erreur = "Impossible de vérifier l'équipement MeshCore de cette équipe."; this.chargement = false; },
    });
  }

  chargerMessages(avecSpinner: boolean): void {
    if (avecSpinner) this.chargement = true;
    this.messageService.getPourEquipe(this.equipeId).subscribe({
      next: (data) => { this.messages = data; this.chargement = false; },
      error: () => { if (avecSpinner) this.chargement = false; },
    });
  }

  get destinatairePubkey(): string | null {
    return this.noeudsEquipe.find(n => n.id === this.destinataireId)?.pubkey_hex || null;
  }

  envoyer(): void {
    if (!this.nouveauMessage.trim() || !this.compagnonId || !this.destinatairePubkey) return;
    this.envoiEnCours = true;
    this.messageService.envoyer(this.compagnonId, this.destinatairePubkey, this.nouveauMessage.trim()).subscribe({
      next: (message) => {
        this.messages = [...this.messages, message];
        this.nouveauMessage = '';
        this.envoiEnCours = false;
      },
      error: () => { this.erreur = "Échec de l'envoi du message."; this.envoiEnCours = false; },
    });
  }
}
