import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { OfferReponseService } from '../../services/offer-reponse.service';
import { Offer } from '../../shared/models/offer.model';
import { OfferMessage } from '../../shared/models/offer-message.model';
import { TYPE_LOGEMENT_LABELS, TYPE_LOYER_LABELS } from '../../pages/hebergement-matching/hebergement-matching.component';

/** Page publique atteinte via le lien reçu par email (Offer.reponse_token) — permet au
 * propriétaire d'une offre (en général sans compte) de consulter/répondre aux messages de
 * l'équipe et d'éditer directement son offre, sans repasser par le formulaire complet. */
@Component({
  selector: 'app-offer-reponse',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './offer-reponse.component.html',
  styleUrl: './offer-reponse.component.scss',
})
export class OfferReponseComponent implements OnInit {
  loading = true;
  notFound = false;

  offer: Offer | null = null;
  messages: OfferMessage[] = [];

  readonly typeLogementLabels = TYPE_LOGEMENT_LABELS;
  readonly typeLoyerLabels = TYPE_LOYER_LABELS;

  editing = false;
  editForm: Partial<Offer> = {};
  saving = false;
  saveError = '';
  saveSuccess = false;

  newMessageContenu = '';
  sendingMessage = false;
  messageError = '';

  private token = '';

  constructor(
    private route: ActivatedRoute,
    private offerReponseService: OfferReponseService,
  ) {}

  ngOnInit(): void {
    this.token = this.route.snapshot.paramMap.get('token') || '';
    this.charger();
  }

  private charger(): void {
    this.loading = true;
    this.offerReponseService.getByToken(this.token).subscribe({
      next: ({ offer, messages }) => {
        this.offer = offer;
        this.messages = messages;
        this.loading = false;
      },
      error: () => { this.notFound = true; this.loading = false; },
    });
  }

  startEditing(): void {
    if (!this.offer) return;
    this.editForm = {
      description: this.offer.description,
      type_logement: this.offer.type_logement,
      type_loyer: this.offer.type_loyer,
      loyer_montant_min: this.offer.loyer_montant_min,
      loyer_montant_max: this.offer.loyer_montant_max,
      nombre_pieces: this.offer.nombre_pieces,
      nombre_chambres: this.offer.nombre_chambres,
      capacite_adultes: this.offer.capacite_adultes,
      capacite_enfants: this.offer.capacite_enfants,
      animaux_acceptes: this.offer.animaux_acceptes,
      jardin: this.offer.jardin,
      pmr_compatible: this.offer.pmr_compatible,
      status: this.offer.status,
    };
    this.editing = true;
    this.saveSuccess = false;
  }

  cancelEditing(): void {
    this.editing = false;
  }

  saveEdits(): void {
    this.saving = true;
    this.saveError = '';
    this.offerReponseService.updateOffer(this.token, this.editForm).subscribe({
      next: (offer) => {
        this.offer = offer;
        this.saving = false;
        this.editing = false;
        this.saveSuccess = true;
      },
      error: () => { this.saveError = "Erreur lors de l'enregistrement."; this.saving = false; },
    });
  }

  sendReply(): void {
    if (!this.newMessageContenu.trim()) return;
    this.sendingMessage = true;
    this.messageError = '';
    this.offerReponseService.reply(this.token, this.newMessageContenu.trim()).subscribe({
      next: (msg) => {
        this.messages = [...this.messages, msg];
        this.newMessageContenu = '';
        this.sendingMessage = false;
      },
      error: () => { this.messageError = "Erreur lors de l'envoi."; this.sendingMessage = false; },
    });
  }
}
