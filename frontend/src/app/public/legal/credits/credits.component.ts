import { Component } from '@angular/core';
import { CONTACT_NOM } from '../../../shared/utils/contact-obfusque.util';

import { BandeauMarqueBlancheComponent } from '../../../shared/components/common/bandeau-marque-blanche/bandeau-marque-blanche.component';

@Component({
  selector: 'app-credits',
  imports: [BandeauMarqueBlancheComponent],
  templateUrl: './credits.component.html',
  styleUrl: './credits.component.scss'
})
export class CreditsComponent {
  readonly contactNom = CONTACT_NOM;
}
