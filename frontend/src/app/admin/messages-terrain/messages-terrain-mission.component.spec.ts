import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { MessagesTerrainMissionComponent } from './messages-terrain-mission.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { MessagesTerrainService } from '../../services/messages-terrain.service';

describe('MessagesTerrainMissionComponent', () => {
  it("montre le statut de chacun et met en tête une demande de secours", () => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [MessagesTerrainMissionComponent] });
    const service = TestBed.inject(MessagesTerrainService);
    const secours = { id: '1', auteur_nom: 'Léa Martin', type_libelle: 'Demande de premiers secours', texte: 'malaise', prioritaire: true,
      canal: 'MESHCORE', emis_le: '2026-11-22T10:00:00Z', latitude: '45.5', longitude: '4.6', statut: 'Demande de secours' } as any;
    spyOn(service, 'statuts').and.returnValue(of([secours]));
    spyOn(service, 'fil').and.returnValue(of([secours]));
    const f = TestBed.createComponent(MessagesTerrainMissionComponent);
    f.componentInstance.missionId = 'm1';
    f.componentInstance.ngOnChanges();
    f.detectChanges();
    const texte: string = f.nativeElement.textContent;
    expect(texte).toContain('Demande de premiers secours');
    expect(texte).toContain('malaise');
    expect(f.nativeElement.querySelector('.alerte')).not.toBeNull();
    f.componentInstance.ngOnDestroy();
  });
});
