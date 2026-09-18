import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { CONTACT_ADRESSE, CONTACT_EMAIL, CONTACT_NOM } from '../../../shared/utils/contact-obfusque.util';

/** Date de la version actuelle du texte — voir CONVENTION_VERSION côté backend
 * (core/convention_sous_traitance.py), qui DOIT rester synchronisée avec cette date : c'est
 * elle qui est enregistrée sur AcceptationConvention.version_acceptee à chaque acceptation, et
 * qui détermine si une institution doit ré-accepter après une mise à jour du texte. */
export const CONVENTION_VERSION = '2026-09-18';

@Component({
  selector: 'app-convention-sous-traitance',
  imports: [RouterLink],
  templateUrl: './convention-sous-traitance.component.html',
  styleUrl: './convention-sous-traitance.component.scss'
})
export class ConventionSousTraitanceComponent {
  readonly contactNom = CONTACT_NOM;
  readonly contactAdresse = CONTACT_ADRESSE;
  readonly contactEmail = CONTACT_EMAIL;
  readonly version = CONVENTION_VERSION;
}
