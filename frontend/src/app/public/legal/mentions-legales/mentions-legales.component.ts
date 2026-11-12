import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  CONTACT_ADRESSE, CONTACT_EMAIL, CONTACT_NOM, CONTACT_TELEPHONE,
} from '../../../shared/utils/contact-obfusque.util';

import { BandeauMarqueBlancheComponent } from '../../../shared/components/common/bandeau-marque-blanche/bandeau-marque-blanche.component';

@Component({
  selector: 'app-mentions-legales',
  imports: [RouterLink, BandeauMarqueBlancheComponent],
  templateUrl: './mentions-legales.component.html',
  styleUrl: './mentions-legales.component.scss'
})
export class MentionsLegalesComponent {
  readonly contactNom = CONTACT_NOM;
  readonly contactAdresse = CONTACT_ADRESSE;
  readonly contactEmail = CONTACT_EMAIL;
  readonly contactTelephone = CONTACT_TELEPHONE;
}
