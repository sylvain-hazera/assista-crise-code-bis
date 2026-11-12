import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BandeauMarqueBlancheComponent } from '../../../shared/components/common/bandeau-marque-blanche/bandeau-marque-blanche.component';

@Component({
  selector: 'app-cgu',
  imports: [RouterLink, BandeauMarqueBlancheComponent],
  templateUrl: './cgu.component.html',
  styleUrl: './cgu.component.scss'
})
export class CguComponent {

}
